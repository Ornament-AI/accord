"""Health, readiness, request-id, and Problem Detail handler tests."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request

from app.config import get_settings
from app.exceptions import NotFoundError
from app.main import (
    app,
    handle_accord_error,
    handle_http_exception,
    handle_unhandled,
    handle_validation_error,
)


def _request_with_id(request_id: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/test",
            "raw_path": b"/api/test",
            "root_path": "",
            "scheme": "http",
            "query_string": b"",
            "headers": [(b"x-request-id", request_id.encode())],
            "client": ("testclient", 50000),
            "server": ("test", 80),
        }
    )


def _request_with_state_and_header(*, state_id: str, header_id: str) -> Request:
    request = _request_with_id(header_id)
    request.state.request_id = state_id
    return request


@pytest.mark.asyncio
async def test_healthz(client):
    resp = await client.get("/api/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_generated_request_id_is_returned(client):
    resp = await client.get("/api/healthz")

    request_id = resp.headers["X-Request-ID"]
    assert len(request_id) == 32
    int(request_id, 16)


@pytest.mark.asyncio
async def test_invalid_request_id_header_is_replaced(client):
    resp = await client.get("/api/healthz", headers={"X-Request-ID": "bad request id!"})

    request_id = resp.headers["X-Request-ID"]
    assert request_id != "bad request id!"
    assert len(request_id) == 32
    int(request_id, 16)


@pytest.mark.asyncio
async def test_invalid_content_length_rejection_includes_request_id(client):
    resp = await client.get(
        "/api/healthz",
        headers={"Content-Length": "not-an-int", "X-Request-ID": "bad-length"},
    )

    assert resp.status_code == 400
    assert resp.headers["X-Request-ID"] == "bad-length"
    assert resp.json()["detail"] == "Invalid Content-Length header"


@pytest.mark.asyncio
async def test_oversized_content_length_rejection_includes_request_id(client):
    settings = get_settings()
    resp = await client.get(
        "/api/healthz",
        headers={
            "Content-Length": str(settings.max_request_body_bytes + 1),
            "X-Request-ID": "too-large",
        },
    )

    assert resp.status_code == 413
    assert resp.headers["X-Request-ID"] == "too-large"
    assert resp.json()["detail"] == "Request body too large"


@pytest.mark.asyncio
async def test_http_exception_handler_preserves_headers_with_header_fallback():
    response = await handle_http_exception(
        _request_with_id("handler-request-id"),
        HTTPException(
            status_code=418,
            detail="Teapot",
            headers={"X-Original-Header": "preserved"},
        ),
    )

    assert response.headers["X-Request-ID"] == "handler-request-id"
    assert response.headers["X-Original-Header"] == "preserved"


@pytest.mark.asyncio
async def test_http_exception_handler_prefers_state_request_id():
    response = await handle_http_exception(
        _request_with_state_and_header(state_id="state-request-id", header_id="header-request-id"),
        HTTPException(
            status_code=418,
            detail="Teapot",
            headers={"X-Original-Header": "preserved"},
        ),
    )

    assert response.headers["X-Request-ID"] == "state-request-id"
    assert response.headers["X-Original-Header"] == "preserved"


@pytest.mark.asyncio
async def test_accord_error_handler_adds_request_id():
    response = await handle_accord_error(
        _request_with_state_and_header(state_id="accord-request-id", header_id="header-request-id"),
        NotFoundError("Missing resource."),
    )

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "accord-request-id"
    body = response.body
    assert b"Missing resource." in body


@pytest.mark.asyncio
async def test_unhandled_exception_handler_adds_request_id():
    response = await handle_unhandled(
        _request_with_state_and_header(
            state_id="unhandled-request-id", header_id="header-request-id"
        ),
        RuntimeError("boom"),
    )

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "unhandled-request-id"
    assert b"An unexpected error occurred." in response.body
    assert b"boom" not in response.body


@pytest.mark.asyncio
async def test_validation_error_handler_includes_request_id():
    request = _request_with_state_and_header(
        state_id="validation-id", header_id="header-request-id"
    )
    exc = RequestValidationError(
        [
            {
                "loc": ("query", "page"),
                "msg": "Input should be greater than 0",
                "type": "greater_than",
            }
        ]
    )
    response = await handle_validation_error(request, exc)

    assert response.status_code == 422
    assert response.headers["X-Request-ID"] == "validation-id"
    assert b"Request validation failed." in response.body


@pytest.mark.asyncio
async def test_readyz(client):
    resp = await client.get("/api/readyz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"
    assert data["auth"] == "ok"
    assert data["jobs"] == "ok"
    assert data["storage"] == "unconfigured"
    assert data["reports"] == "ok"


@pytest.mark.asyncio
async def test_readyz_reports_auth_unavailable_when_not_ready(client):
    original = getattr(app.state, "auth_ready", True)
    app.state.auth_ready = False
    try:
        resp = await client.get("/api/readyz")
    finally:
        app.state.auth_ready = original

    assert resp.status_code == 503
    assert resp.json()["detail"] == "Auth provider is not ready."


@pytest.mark.asyncio
async def test_readyz_reports_database_unavailable(client):
    with patch(
        "app.api.routes.health.session_context",
        side_effect=RuntimeError("db down"),
    ):
        resp = await client.get("/api/readyz")

    assert resp.status_code == 503
    assert resp.json()["detail"] == "Database connection is not ready."


@pytest.mark.asyncio
async def test_security_headers_present_on_healthz(client):
    resp = await client.get("/api/healthz")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in resp.headers["content-security-policy"]
