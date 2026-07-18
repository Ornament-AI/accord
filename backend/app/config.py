"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(alias="DATABASE_URL")
    migrations_database_url: str = Field(default="", alias="MIGRATIONS_DATABASE_URL")
    cors_origins: str = Field(
        default=(
            "http://localhost:5173,http://127.0.0.1:5173,"
            "http://localhost:5174,http://127.0.0.1:5174,"
            "http://localhost:5175,http://127.0.0.1:5175,"
            "http://localhost:5176,http://127.0.0.1:5176"
        ),
        alias="CORS_ORIGINS",
    )
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    app_version: str = Field(default="dev", alias="APP_VERSION")
    base_url: str = Field(default="http://localhost:5173", alias="BASE_URL")
    public_app_url: str = Field(default="", alias="PUBLIC_APP_URL")
    max_request_body_bytes: int = Field(default=10 * 1024 * 1024, alias="MAX_REQUEST_BODY_BYTES")

    # WorkOS auth seam (wired by a later lane; no WorkOS SDK usage here).
    workos_client_id: str = Field(default="", alias="WORKOS_CLIENT_ID")
    workos_api_key: str = Field(default="", alias="WORKOS_API_KEY")
    workos_redirect_uri: str = Field(
        default="http://localhost:8000/api/auth/callback",
        alias="WORKOS_REDIRECT_URI",
    )
    workos_webhook_secret: str = Field(default="", alias="WORKOS_WEBHOOK_SECRET")

    # Session cookie seam (wired by a later lane).
    session_secret_key: str = Field(default="", alias="SESSION_SECRET_KEY")
    session_cookie_name: str = Field(default="accord_session", alias="SESSION_COOKIE_NAME")
    session_idle_timeout_seconds: int = Field(default=7200, alias="SESSION_IDLE_TIMEOUT_SECONDS")
    workos_webhook_tolerance_seconds: int = Field(
        default=300,
        alias="WORKOS_WEBHOOK_TOLERANCE_SECONDS",
    )

    # Dev-only test-identity bypass (fails closed in production).
    dev_auth_bypass: bool = Field(default=False, alias="DEV_AUTH_BYPASS")
    # Optional overrides for DevAuthAdapter identity (non-production only).
    dev_auth_email: str = Field(default="dev@accord.local", alias="DEV_AUTH_EMAIL")
    dev_auth_name: str = Field(default="Dev Test User", alias="DEV_AUTH_NAME")

    # Allow short SESSION_SECRET_KEY in local/test (checked lazily by session signer).
    accord_allow_weak_secrets: bool = Field(default=False, alias="ACCORD_ALLOW_WEAK_SECRETS")

    # Object storage seam (wired when storage is adopted).
    object_storage_endpoint: str = Field(default="", alias="OBJECT_STORAGE_ENDPOINT")
    object_storage_bucket: str = Field(default="", alias="OBJECT_STORAGE_BUCKET")
    object_storage_access_key: str = Field(default="", alias="OBJECT_STORAGE_ACCESS_KEY")
    object_storage_secret_key: str = Field(default="", alias="OBJECT_STORAGE_SECRET_KEY")

    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=5, alias="DB_MAX_OVERFLOW")
    db_pool_timeout_seconds: float = Field(default=30.0, alias="DB_POOL_TIMEOUT_SECONDS")
    db_pool_recycle_seconds: int = Field(default=1800, alias="DB_POOL_RECYCLE_SECONDS")
    db_statement_timeout_ms: int = Field(default=60_000, alias="DB_STATEMENT_TIMEOUT_MS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("db_pool_size", mode="after")
    @classmethod
    def _clamp_db_pool_size(cls, v: int) -> int:
        return max(1, min(100, v))

    @field_validator("db_max_overflow", mode="after")
    @classmethod
    def _clamp_db_max_overflow(cls, v: int) -> int:
        return max(0, min(100, v))

    @field_validator("db_pool_timeout_seconds", mode="after")
    @classmethod
    def _clamp_db_pool_timeout(cls, v: float) -> float:
        return max(1.0, min(300.0, v))

    @field_validator("db_pool_recycle_seconds", mode="after")
    @classmethod
    def _clamp_db_pool_recycle(cls, v: int) -> int:
        return max(0, min(86_400, v))

    @field_validator("db_statement_timeout_ms", mode="after")
    @classmethod
    def _clamp_db_statement_timeout(cls, v: int) -> int:
        return max(0, min(3_600_000, v))

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def effective_public_app_url(self) -> str:
        return self.public_app_url or self.base_url

    @model_validator(mode="after")
    def _validate_production_invariants(self) -> "Settings":
        if self.is_production and self.dev_auth_bypass:
            raise ValueError("DEV_AUTH_BYPASS cannot be enabled in production.")
        if self.is_production:
            required = {
                "WORKOS_CLIENT_ID": self.workos_client_id,
                "WORKOS_API_KEY": self.workos_api_key,
                "WORKOS_REDIRECT_URI": self.workos_redirect_uri,
                "WORKOS_WEBHOOK_SECRET": self.workos_webhook_secret,
                "SESSION_SECRET_KEY": self.session_secret_key,
                "MIGRATIONS_DATABASE_URL": self.migrations_database_url,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError("Missing required production settings: " + ", ".join(missing))
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
