"""Auth adapter Protocol and WorkOS / Dev implementations.

WorkOS SDK usage is isolated to ``WorkOSAuthAdapter``. WorkOS access, refresh,
and id tokens must never be copied into cookies or response bodies — only the
``AuthenticatedIdentity`` fields (subject id, email, name) leave this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

from app.auth.errors import AuthExchangeError, AuthMisconfiguredError
from app.config import Settings


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    """Identity returned by an auth-code exchange (no provider tokens)."""

    subject_id: str
    email: str
    name: str | None


class AuthAdapter(Protocol):
    """Provider seam matching ADR-0002 section 6 (identity only)."""

    def get_authorization_url(self, *, state: str, redirect_uri: str) -> str: ...

    async def exchange_code(self, *, code: str) -> AuthenticatedIdentity: ...


class WorkOSAuthAdapter:
    """Thin wrapper around the official ``workos`` SDK (AuthKit user management)."""

    def __init__(self, settings: Settings) -> None:
        # Imported here so non-WorkOS paths (and OpenAPI export) do not require
        # a configured client at import time.
        from workos import WorkOSClient

        self._redirect_uri = settings.workos_redirect_uri
        self._client = WorkOSClient(
            api_key=settings.workos_api_key,
            client_id=settings.workos_client_id,
        )

    def get_authorization_url(self, *, state: str, redirect_uri: str) -> str:
        # WorkOS User Management AuthKit authorize URL.
        return self._client.user_management.get_authorization_url(
            redirect_uri=redirect_uri,
            state=state,
            provider="authkit",
        )

    async def exchange_code(self, *, code: str) -> AuthenticatedIdentity:
        try:
            # Synchronous SDK call — isolate and map to identity-only fields.
            response = self._client.user_management.authenticate_with_code(code=code)
        except Exception as exc:  # noqa: BLE001 — normalize any SDK/network failure
            raise AuthExchangeError("Failed to exchange authorization code.") from exc

        user = response.user
        email = (user.email or "").strip()
        if not user.id or not email:
            raise AuthExchangeError("WorkOS identity is missing required fields.")

        name = user.name
        if not name:
            parts = [p for p in (user.first_name, user.last_name) if p]
            name = " ".join(parts) if parts else None

        # Intentionally discard access_token / refresh_token / oauth_tokens.
        return AuthenticatedIdentity(
            subject_id=user.id,
            email=email,
            name=name,
        )


class DevAuthAdapter:
    """Local test identity — structurally unreachable when ``environment=production``."""

    DEV_SUBJECT_ID = "dev-test-subject"

    def __init__(self, settings: Settings) -> None:
        self._email = settings.dev_auth_email
        self._name = settings.dev_auth_name

    def get_authorization_url(self, *, state: str, redirect_uri: str) -> str:
        # Same-app path so callers can round-trip without an external IdP.
        query = urlencode({"code": "dev-login", "state": state})
        separator = "&" if "?" in redirect_uri else "?"
        return f"{redirect_uri}{separator}{query}"

    async def exchange_code(self, *, code: str) -> AuthenticatedIdentity:
        _ = code  # any code is accepted in dev bypass mode
        return AuthenticatedIdentity(
            subject_id=self.DEV_SUBJECT_ID,
            email=self._email,
            name=self._name,
        )

    def identity(self) -> AuthenticatedIdentity:
        """Return the configured dev identity without a code exchange."""
        return AuthenticatedIdentity(
            subject_id=self.DEV_SUBJECT_ID,
            email=self._email,
            name=self._name,
        )


def _workos_configured(settings: Settings) -> bool:
    return bool(
        settings.workos_client_id and settings.workos_api_key and settings.workos_redirect_uri
    )


def get_auth_adapter(settings: Settings) -> AuthAdapter:
    """Select the auth adapter. Fail closed in production; never select Dev there.

    Belt-and-suspenders: even if ``dev_auth_bypass=True`` is forced on a Settings
    instance (bypassing model validation), production always requires WorkOS and
    never returns ``DevAuthAdapter``.
    """
    if settings.is_production:
        if not _workos_configured(settings):
            raise AuthMisconfiguredError(
                "WorkOS authentication is not configured.",
            )
        return WorkOSAuthAdapter(settings)

    # Non-production: DevAuth only when explicitly enabled.
    if settings.dev_auth_bypass:
        return DevAuthAdapter(settings)

    if _workos_configured(settings):
        return WorkOSAuthAdapter(settings)

    raise AuthMisconfiguredError(
        "Authentication is not configured "
        "(set WorkOS credentials or enable DEV_AUTH_BYPASS in non-production).",
    )
