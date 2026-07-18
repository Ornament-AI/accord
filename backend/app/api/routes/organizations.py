"""Organization create route (Phase 2)."""

from __future__ import annotations

import hashlib
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUser, Session
from app.api.responses import problem_response
from app.auth.session import get_session_store
from app.config import get_settings
from app.models.identity import User
from app.schemas.organizations import CreateOrganizationRequest
from app.services.identity import build_me_payload
from app.services.organizations import create_organization
from app.tenancy import bind_tenant_context

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _user_agent_hash(request: Request) -> str | None:
    ua = request.headers.get("user-agent")
    if not ua:
        return None
    return hashlib.sha256(ua.encode("utf-8")).hexdigest()


@router.post("")
@router.post("/")
async def create_organization_route(
    request: Request,
    body: CreateOrganizationRequest,
    principal: CurrentUser,
    db: Session,
) -> Response:
    """Create an organization; creator becomes administrator; return /me shape."""
    settings = get_settings()
    if principal.session_id is None:
        return problem_response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            instance=str(request.url.path),
            request_id=getattr(request.state, "request_id", None),
        )

    user = await db.get(User, UUID(principal.user_id))
    if user is None:
        return problem_response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            instance=str(request.url.path),
            request_id=getattr(request.state, "request_id", None),
        )

    org, cookie_value = await create_organization(
        db,
        settings,
        user=user,
        name=body.name,
        slug=body.slug,
        current_session_id=UUID(principal.session_id),
        user_agent_hash=_user_agent_hash(request),
    )

    store = get_session_store(settings, db)
    session_row = await store.read_session(cookie_value)
    if session_row is None:
        return problem_response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            instance=str(request.url.path),
            request_id=getattr(request.state, "request_id", None),
        )

    # Re-load user after commit (create_organization commits). Commit clears
    # SET LOCAL — re-bind so /me membership reads work under forced RLS.
    user = await db.get(User, UUID(principal.user_id))
    assert user is not None
    if not db.in_transaction():
        await db.begin()
    await bind_tenant_context(db, organization_id=org.id, user_id=user.id)
    payload = await build_me_payload(db, user, session_row)
    response = JSONResponse(content=payload, status_code=status.HTTP_201_CREATED)
    store.apply_session_cookie(response, cookie_value)
    return response
