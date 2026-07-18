"""Auth routes — login, callback, logout, and current-user identity."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.responses import problem_response
from app.auth.adapters import DevAuthAdapter, get_auth_adapter
from app.auth.errors import AuthExchangeError, AuthMisconfiguredError
from app.auth.session import (
    get_session_store,
    session_payload_from_identity,
    sign_oauth_state,
    verify_oauth_state,
)
from app.config import get_settings

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


async def _establish_session_redirect(
    *,
    request: Request,
    workos_user_id: str,
    email: str,
    name: str | None,
    redirect_url: str,
) -> RedirectResponse:
    settings = get_settings()
    store = get_session_store(settings)
    cookie_value = await store.create_session(
        session_payload_from_identity(
            workos_user_id=workos_user_id,
            email=email,
            name=name,
        )
    )
    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    store.apply_session_cookie(response, cookie_value)
    return response


@router.get("/login")
async def login(request: Request) -> Response:
    """Start login: WorkOS redirect, or establish a dev session when bypass is on."""
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

    frontend_url = settings.effective_public_app_url.rstrip("/") or "/"

    # Dev bypass: mint a session immediately (no external redirect).
    if isinstance(adapter, DevAuthAdapter):
        identity = adapter.identity()
        return await _establish_session_redirect(
            request=request,
            workos_user_id=identity.subject_id,
            email=identity.email,
            name=identity.name,
            redirect_url=frontend_url,
        )

    state = sign_oauth_state(settings)
    authorization_url = adapter.get_authorization_url(
        state=state,
        redirect_uri=settings.workos_redirect_uri,
    )
    return RedirectResponse(url=authorization_url, status_code=status.HTTP_302_FOUND)


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
) -> Response:
    """Complete OAuth: verify state, exchange code, mint session, redirect to app."""
    settings = get_settings()

    if not verify_oauth_state(settings, state or ""):
        return _problem(
            request,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing OAuth state.",
            error="InvalidOAuthState",
        )

    if not code:
        return _problem(
            request,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization code.",
            error="MissingAuthorizationCode",
        )

    try:
        adapter = get_auth_adapter(settings)
    except AuthMisconfiguredError as exc:
        return _problem(
            request,
            status_code=exc.status_code,
            detail=exc.detail,
            error=exc.error,
        )

    try:
        identity = await adapter.exchange_code(code=code)
    except AuthExchangeError as exc:
        return _problem(
            request,
            status_code=exc.status_code,
            detail=exc.detail,
            error=exc.error,
        )

    frontend_url = settings.effective_public_app_url.rstrip("/") or "/"
    return await _establish_session_redirect(
        request=request,
        workos_user_id=identity.subject_id,
        email=identity.email,
        name=identity.name,
        redirect_url=frontend_url,
    )


@router.post("/logout")
async def logout(request: Request) -> Response:
    """Clear the session cookie. Idempotent when no session is present."""
    settings = get_settings()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    get_session_store(settings).clear_session_cookie(response)
    return response


@router.get("/me")
async def me(request: Request) -> Response:
    """Return the current identity from the signed session cookie."""
    settings = get_settings()

    # Fail closed in production when WorkOS is not configured (defense in depth;
    # Settings validation normally prevents this, but model_construct / forced
    # settings in tests can still hit this path).
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

    store = get_session_store(settings)
    payload = await store.read_session(cookie_value)
    if payload is None:
        return _problem(
            request,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    return JSONResponse(
        content={
            "id": payload.workos_user_id,
            "email": payload.email,
            "name": payload.name,
        }
    )
