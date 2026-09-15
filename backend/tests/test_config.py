"""Tests for application settings validation."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def _set_base_env(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://accord@localhost:5432/accord_test",
    )
    monkeypatch.delenv("DEV_AUTH_BYPASS", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("WORKOS_CLIENT_ID", raising=False)
    monkeypatch.delenv("WORKOS_API_KEY", raising=False)
    monkeypatch.delenv("WORKOS_REDIRECT_URI", raising=False)
    monkeypatch.delenv("WORKOS_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("SESSION_SECRET_KEY", raising=False)
    monkeypatch.delenv("MIGRATIONS_DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_POOL_SIZE", raising=False)
    monkeypatch.delenv("DB_MAX_OVERFLOW", raising=False)
    monkeypatch.delenv("DB_POOL_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("DB_POOL_RECYCLE_SECONDS", raising=False)
    monkeypatch.delenv("DB_STATEMENT_TIMEOUT_MS", raising=False)
    monkeypatch.delenv("ACCORD_ALLOW_WEAK_SECRETS", raising=False)


def test_dev_defaults(monkeypatch):
    _set_base_env(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.dev_auth_bypass is False
    assert settings.session_cookie_name == "accord_session"
    assert settings.workos_client_id == ""
    assert settings.migrations_database_url == ""
    assert settings.db_pool_size == 5
    assert settings.db_statement_timeout_ms == 60_000


def test_database_runtime_settings_are_clamped(monkeypatch):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("DB_POOL_SIZE", "0")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "-1")
    monkeypatch.setenv("DB_POOL_TIMEOUT_SECONDS", "0")
    monkeypatch.setenv("DB_POOL_RECYCLE_SECONDS", "-5")
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "-10")

    settings = Settings(_env_file=None)

    assert settings.db_pool_size == 1
    assert settings.db_max_overflow == 0
    assert settings.db_pool_timeout_seconds == 1.0
    assert settings.db_pool_recycle_seconds == 0
    assert settings.db_statement_timeout_ms == 0


def test_dev_auth_bypass_rejected_in_production(monkeypatch):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEV_AUTH_BYPASS", "true")
    monkeypatch.setenv("WORKOS_CLIENT_ID", "client")
    monkeypatch.setenv("WORKOS_API_KEY", "key")
    monkeypatch.setenv("WORKOS_REDIRECT_URI", "https://example.com/callback")
    monkeypatch.setenv("WORKOS_WEBHOOK_SECRET", "whsec")
    monkeypatch.setenv("SESSION_SECRET_KEY", "session-secret")
    monkeypatch.setenv("MIGRATIONS_DATABASE_URL", "postgresql+asyncpg://migrator@localhost/accord")

    with pytest.raises(ValidationError, match="DEV_AUTH_BYPASS cannot be enabled in production"):
        Settings(_env_file=None)


def test_production_requires_workos_and_session_and_migrations_dsn(monkeypatch):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(ValidationError, match="Missing required production settings") as exc_info:
        Settings(_env_file=None)
    assert "WORKOS_CLIENT_ID" in str(exc_info.value)


def test_production_accepts_complete_auth_and_db_seams(monkeypatch):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("WORKOS_CLIENT_ID", "client")
    monkeypatch.setenv("WORKOS_API_KEY", "key")
    monkeypatch.setenv("WORKOS_REDIRECT_URI", "https://example.com/callback")
    monkeypatch.setenv("WORKOS_WEBHOOK_SECRET", "whsec")
    monkeypatch.setenv("SESSION_SECRET_KEY", "session-secret-of-adequate-length")
    monkeypatch.setenv(
        "MIGRATIONS_DATABASE_URL",
        "postgresql+asyncpg://accord_migrator@localhost/accord",
    )

    settings = Settings(_env_file=None)

    assert settings.is_production is True
    assert settings.workos_client_id == "client"
    assert settings.migrations_database_url.startswith("postgresql+asyncpg://")


@pytest.mark.parametrize("bad_env", ["prod", "STAGINGGG", "", "local", "prd"])
def test_environment_allowlist_rejects_unknown_values(monkeypatch, bad_env):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", bad_env)

    with pytest.raises(ValidationError, match="ENVIRONMENT must be one of"):
        Settings(_env_file=None)


@pytest.mark.parametrize("good_env", ["development", "staging", "production", "Production "])
def test_environment_allowlist_accepts_known_values(monkeypatch, good_env):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", good_env)
    if good_env.strip().lower() != "development":
        monkeypatch.setenv("WORKOS_CLIENT_ID", "client")
        monkeypatch.setenv("WORKOS_API_KEY", "key")
        monkeypatch.setenv("WORKOS_REDIRECT_URI", "https://example.com/callback")
        monkeypatch.setenv("WORKOS_WEBHOOK_SECRET", "whsec")
        monkeypatch.setenv("SESSION_SECRET_KEY", "session-secret-of-adequate-length")
        monkeypatch.setenv("MIGRATIONS_DATABASE_URL", "postgresql+asyncpg://m@localhost/accord")

    settings = Settings(_env_file=None)

    assert settings.environment == good_env.strip().lower()
    assert settings.is_development is (good_env.strip().lower() == "development")


def test_staging_is_production_class(monkeypatch):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("DEV_AUTH_BYPASS", "true")

    with pytest.raises(ValidationError, match="DEV_AUTH_BYPASS cannot be enabled in production"):
        Settings(_env_file=None)


def test_production_rejects_allow_weak_secrets(monkeypatch):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ACCORD_ALLOW_WEAK_SECRETS", "true")
    monkeypatch.setenv("WORKOS_CLIENT_ID", "client")
    monkeypatch.setenv("WORKOS_API_KEY", "key")
    monkeypatch.setenv("WORKOS_REDIRECT_URI", "https://example.com/callback")
    monkeypatch.setenv("WORKOS_WEBHOOK_SECRET", "whsec")
    monkeypatch.setenv("SESSION_SECRET_KEY", "session-secret-of-adequate-length")
    monkeypatch.setenv("MIGRATIONS_DATABASE_URL", "postgresql+asyncpg://m@localhost/accord")

    with pytest.raises(
        ValidationError, match="ACCORD_ALLOW_WEAK_SECRETS cannot be enabled in production"
    ):
        Settings(_env_file=None)


def test_production_rejects_short_session_secret(monkeypatch):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("WORKOS_CLIENT_ID", "client")
    monkeypatch.setenv("WORKOS_API_KEY", "key")
    monkeypatch.setenv("WORKOS_REDIRECT_URI", "https://example.com/callback")
    monkeypatch.setenv("WORKOS_WEBHOOK_SECRET", "whsec")
    monkeypatch.setenv("SESSION_SECRET_KEY", "short")
    monkeypatch.setenv("MIGRATIONS_DATABASE_URL", "postgresql+asyncpg://m@localhost/accord")

    with pytest.raises(ValidationError, match="SESSION_SECRET_KEY must be at least"):
        Settings(_env_file=None)
