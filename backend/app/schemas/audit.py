"""Pydantic schemas for audit-event read API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pagination import PaginatedResponse

# Command names align with ADR 0008 / 0009 (e.g. ``post``, ``artifact.download``).
COMMAND_NAME_PATTERN = r"^[a-z][a-z0-9_.]*$"


class AuditActor(BaseModel):
    """User attribution for an audit event; omitted for system-originated rows."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    command: str
    entity_type: str
    entity_id: UUID
    actor: AuditActor | None = None
    request_id: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


AuditEventListPage = PaginatedResponse[AuditEventResponse]
