"""Shared API response helpers."""

from datetime import date
from http import HTTPStatus
from typing import Any

from fastapi.responses import JSONResponse

from app.timezone import current_ist_date


def export_content_disposition(slug: str, extension: str, *, as_of: date | None = None) -> str:
    stamp = (as_of or current_ist_date()).isoformat()
    return f'attachment; filename="accord-{slug}-{stamp}.{extension}"'


def problem_content(
    *,
    status_code: int,
    detail: str,
    instance: str,
    error: str | None = None,
    request_id: str | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    try:
        title = HTTPStatus(status_code).phrase
    except ValueError:
        title = "Error"
    return {
        "type": "about:blank",
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": instance,
        **({"error": error} if error else {}),
        **({"request_id": request_id} if request_id else {}),
        **({"errors": errors} if errors else {}),
    }


def problem_response(
    *,
    status_code: int,
    detail: str,
    instance: str,
    error: str | None = None,
    request_id: str | None = None,
    errors: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=problem_content(
            status_code=status_code,
            detail=detail,
            instance=instance,
            error=error,
            request_id=request_id,
            errors=errors,
        ),
        headers=headers,
    )
