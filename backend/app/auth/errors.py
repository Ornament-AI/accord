"""Auth-domain errors serialized via the AccordError → Problem Detail pipeline."""

from __future__ import annotations

from app.exceptions import AccordError


class AuthMisconfiguredError(AccordError):
    """Auth provider configuration is missing or unusable (fail closed)."""

    status_code = 503
    error_code = "AuthMisconfigured"


class WeakSessionSecretError(AccordError):
    """SESSION_SECRET_KEY is too short and weak secrets are not allowed."""

    status_code = 500
    error_code = "WeakSessionSecret"


class AuthExchangeError(AccordError):
    """Identity-provider code exchange failed."""

    status_code = 502
    error_code = "AuthExchangeFailed"
