"""Auth routes — login, callback, logout, me, switch-org, WorkOS webhooks."""

from __future__ import annotations

import hashlib
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.deps import CurrentUser, Session
from app.api.responses import problem_response
from app.auth.adapters import DevAuthAdapter, get_auth_adapter
from app.auth.errors import (
    AuthExchangeError,
    AuthMisconfiguredError,
    MembershipForbiddenError,
    WeakSessionSecretError,
)
from app.auth.session import get_session_store, sign_oauth_state, verify_oauth_state
from app.auth.webhooks import handle_workos_event, verify_workos_webhook
from app.config import get_settings
from app.models.identity import User
from app.schemas.identity import SwitchOrganizationRequest
from app.services.identity import (
    build_me_payload,
    establish_session_for_identity,
    resolve_active_organization,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _problem(
    request: Request,
    *,
    status_code: int,
    detail: str,
    error: str | None = None,
) -> JSONResponse:
    return problem_response(
        status_code=status_code,
        detail=detail,
        instance=str(request.url.path),
        error=error,
        request_id=_request_id(request),
    )


def _frontend_base() -> str:
    settings = get_settings()
    return settings.effective_public_app_url.rstrip("/") or ""


def _login_error_redirect(error_code: str) -> RedirectResponse:
    base = _frontend_base()
    return RedirectResponse(
        url=f"{base}/login?error={error_code}",
        status_code=status.HTTP_302_FOUND,
    )


def validate_return_to(value: str | None) -> str | None:
    """Accept only safe relative paths; silently drop invalid values."""
    if not value:
        return None
    if not value.startswith("/") or value.startswith("//"):
        return None
    if "://" in value or "\\" in value:
        return None
    if any(ord(c) < 32 for c in value):
        return None
    return value


def _redirect_after_auth(return_to: str | None) -> str:
    base = _frontend_base()
    if return_to:
        return f"{base}{return_to}"
    return base or "/"


def _user_agent_hash(request: Request) -> str | None:
    ua = request.headers.get("user-agent")
    if not ua:
        return None
    return hashlib.sha256(ua.encode("utf-8")).hexdigest()


@router.get("/login")
async def login(
    request: Request,
    db: Session,
    return_to: str | None = None,
) -> Response:
    """Start login: WorkOS redirect, or establish a DB session when bypass is on."""
    settings = get_settings()
    validated_return_to = validate_return_to(return_to)

    try:
        adapter = get_auth_adapter(settings)
    except AuthMisconfiguredError as exc:
        return _problem(
            request,
            status_code=exc.status_code,
            detail=exc.detail,
            error=exc.error,
        )

    if isinstance(adapter, DevAuthAdapter):
        identity = adapter.identity()
        _, cookie_value = await establish_session_for_identity(
            db,
            settings,
            identity,
            user_agent_hash=_user_agent_hash(request),
        )
        response = RedirectResponse(
            url=_redirect_after_auth(validated_return_to),
            status_code=status.HTTP_302_FOUND,
        )
        get_session_store(settings, db).apply_session_cookie(response, cookie_value)
        return response

    state = sign_oauth_state(settings, redirect_to=validated_return_to)
    authorization_url = adapter.get_authorization_url(
        state=state,
        redirect_uri=settings.workos_redirect_uri,
    )
    return RedirectResponse(url=authorization_url, status_code=status.HTTP_302_FOUND)


@router.get("/callback")
async def callback(
    request: Request,
    db: Session,
    code: str | None = None,
    state: str | None = None,
) -> Response:
    """Complete OAuth: verify state, exchange code, mint DB session, redirect."""
    settings = get_settings()
    state_payload = verify_oauth_state(settings, state or "")
    if state_payload is None:
        return _login_error_redirect("invalid_state")

    if not code:
        return _login_error_redirect("auth_failed")

    try:
        adapter = get_auth_adapter(settings)
    except AuthMisconfiguredError:
        return _login_error_redirect("provider_error")

    try:
        identity = await adapter.exchange_code(code=code)
    except AuthExchangeError:
        return _login_error_redirect("auth_failed")
    except Exception:
        return _login_error_redirect("provider_error")

    try:
        _, cookie_value = await establish_session_for_identity(
            db,
            settings,
            identity,
            user_agent_hash=_user_agent_hash(request),
        )
    except WeakSessionSecretError:
        return _login_error_redirect("provider_error")
    except Exception:
        return _login_error_redirect("provider_error")

    return_to = validate_return_to(state_payload.get("r"))
    response = RedirectResponse(
        url=_redirect_after_auth(return_to),
        status_code=status.HTTP_302_FOUND,
    )
    get_session_store(settings, db).apply_session_cookie(response, cookie_value)
    return response


@router.post("/logout")
async def logout(request: Request, db: Session) -> Response:
    """Revoke DB session if present and clear cookie. Idempotent."""
    settings = get_settings()
    try:
        store = get_session_store(settings, db)
    except WeakSessionSecretError:
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        return response

    cookie_value = request.cookies.get(settings.session_cookie_name)
    if cookie_value:
        session_id = store.parse_session_id(cookie_value)
        if session_id is not None:
            await store.revoke_session(session_id)
            await db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    store.clear_session_cookie(response)
    return response


@router.get("/me")
async def me(request: Request, db: Session) -> Response:
    """Return the current identity, memberships, active org, and capabilities."""
    settings = get_settings()

    if settings.is_production:
        try:
            get_auth_adapter(settings)
        except AuthMisconfiguredError as exc:
            return _problem(
                request,
                status_code=exc.status_code,
                detail=exc.detail,
                error=exc.error,
            )

    cookie_value = request.cookies.get(settings.session_cookie_name)
    if not cookie_value:
        return _problem(
            request,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        store = get_session_store(settings, db)
        session_row = await store.read_session(cookie_value)
    except WeakSessionSecretError:
        session_row = None

    if session_row is None:
        return _problem(
            request,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    user = await db.get(User, session_row.user_id)
    if user is None:
        return _problem(
            request,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    payload = await build_me_payload(db, user, session_row)
    return JSONResponse(content=payload)


@router.post("/switch-organization")
async def switch_organization(
    request: Request,
    body: SwitchOrganizationRequest,
    principal: CurrentUser,
    db: Session,
) -> Response:
    """Set active org after membership re-validation; rotate session; return /me."""
    settings = get_settings()
    if principal.session_id is None:
        raise MembershipForbiddenError("No active session to rotate.")

    user = await db.get(User, UUID(principal.user_id))
    if user is None:
        return _problem(
            request,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    active = await resolve_active_organization(db, user, body.organization_id)
    if active is None:
        raise MembershipForbiddenError("You do not have an active membership in that organization.")

    store = get_session_store(settings, db)
    cookie_value = await store.rotate_session(
        old_session_id=UUID(principal.session_id),
        user_id=user.id,
        active_organization_id=body.organization_id,
        user_agent_hash=_user_agent_hash(request),
    )
    await db.commit()

    # Load the new session row for /me payload.
    new_session = await store.read_session(cookie_value)
    if new_session is None:
        # Should not happen immediately after rotate; fail closed.
        return _problem(
            request,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    payload = await build_me_payload(db, user, new_session)
    response = JSONResponse(content=payload, status_code=status.HTTP_200_OK)
    store.apply_session_cookie(response, cookie_value)
    return response


@router.post("/webhooks/workos")
async def workos_webhook(request: Request, db: Session) -> Response:
    """Ingest WorkOS events verified by signature (no session cookie)."""
    settings = get_settings()
    if not settings.workos_webhook_secret:
        return _problem(
            request,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook secret is not configured.",
            error="WebhookUnauthorized",
        )

    signature = request.headers.get("WorkOS-Signature") or request.headers.get("workos-signature")
    if not signature:
        return _problem(
            request,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing WorkOS signature.",
            error="WebhookUnauthorized",
        )

    body = await request.body()
    try:
        event = verify_workos_webhook(
            body=body,
            signature=signature,
            settings=settings,
        )
    except ValueError:
        return _problem(
            request,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or stale WorkOS signature.",
            error="WebhookUnauthorized",
        )

    await handle_workos_event(db, event)
    return Response(status_code=status.HTTP_200_OK)
