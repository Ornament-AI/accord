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


class OrganizationContextRequiredError(AccordError):
    """Authenticated but no active organization is selected for the request."""

    status_code = 409
    error_code = "OrganizationContextRequired"


class CapabilityDeniedError(AccordError):
    """Caller lacks a required capability in the active organization."""

    status_code = 403

    def __init__(self, capability: str, message: str | None = None):
        super().__init__(message or f"Missing required capability: {capability}")
        self.error_code = f"urn:accord:capability:{capability}"


class MembershipForbiddenError(AccordError):
    """Switch-org / inactive membership denied."""

    status_code = 403
    error_code = "MembershipForbidden"
