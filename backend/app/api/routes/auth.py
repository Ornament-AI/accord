"""Auth routes — login, callback, logout, me, WorkOS webhooks."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.deps import Session
from app.api.responses import problem_response
from app.auth.adapters import (
    AuthenticatedIdentity,
    DevAuthAdapter,
    get_auth_adapter,
)
from app.auth.errors import (
    AuthExchangeError,
    AuthMisconfiguredError,
    WeakSessionSecretError,
)
from app.auth.session import get_session_store, sign_oauth_state, verify_oauth_state
from app.auth.webhooks import handle_workos_event, verify_workos_webhook
from app.config import get_settings
from app.models.identity import User
from app.middleware.rate_limit import get_auth_client_ip, get_auth_rate_limit_key, limiter
from app.schemas.identity import MagicCodeLoginRequest, MagicCodeRequest, PasswordLoginRequest
from app.services.identity import (
    build_me_payload,
    establish_session_for_identity,
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


async def _complete_headless_login(
    request: Request,
    db: Session,
    identity: AuthenticatedIdentity,
) -> Response:
    settings = get_settings()
    _, cookie_value = await establish_session_for_identity(
        db,
        settings,
        identity,
        user_agent_hash=_user_agent_hash(request),
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    get_session_store(settings, db).apply_session_cookie(response, cookie_value)
    return response


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


@router.post("/login/password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute", key_func=get_auth_rate_limit_key)
async def login_with_password(
    request: Request,
    body: PasswordLoginRequest,
    db: Session,
) -> Response:
    """Authenticate in Accord's UI while keeping WorkOS credentials server-side."""
    settings = get_settings()
    try:
        adapter = get_auth_adapter(settings)
    except AuthMisconfiguredError as exc:
        return _problem(
            request,
            status_code=exc.status_code,
            detail=exc.detail,
            error=exc.error,
        )
    identity = await adapter.authenticate_with_password(
        email=body.email,
        password=body.password.get_secret_value(),
        ip_address=get_auth_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return await _complete_headless_login(request, db, identity)


@router.post("/magic-code", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("3/10minutes", key_func=get_auth_rate_limit_key)
async def request_magic_code(
    request: Request,
    body: MagicCodeRequest,
) -> Response:
    """Send an email sign-in code without revealing whether an account exists."""
    settings = get_settings()
    try:
        adapter = get_auth_adapter(settings)
    except AuthMisconfiguredError as exc:
        return _problem(
            request,
            status_code=exc.status_code,
            detail=exc.detail,
            error=exc.error,
        )
    await adapter.send_magic_code(
        email=body.email,
        ip_address=get_auth_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/login/magic-code", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute", key_func=get_auth_rate_limit_key)
async def login_with_magic_code(
    request: Request,
    body: MagicCodeLoginRequest,
    db: Session,
) -> Response:
    """Authenticate an emailed one-time code in Accord's own login screen."""
    settings = get_settings()
    try:
        adapter = get_auth_adapter(settings)
    except AuthMisconfiguredError as exc:
        return _problem(
            request,
            status_code=exc.status_code,
            detail=exc.detail,
            error=exc.error,
        )
    identity = await adapter.authenticate_with_magic_code(
        email=body.email,
        code=body.code,
        ip_address=get_auth_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return await _complete_headless_login(request, db, identity)


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
    """Return identity, access_state, singular organization, and membership."""
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

    await handle_workos_event(db, event, raw_body=body)
    return Response(status_code=status.HTTP_200_OK)
