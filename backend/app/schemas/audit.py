"""Pydantic schemas for the compact audit timeline and structured detail API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pagination import PaginatedResponse

COMMAND_NAME_PATTERN = r"^[a-z][a-z0-9_.]*$"


class AuditActor(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str


class AuditEventListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    command: str
    event_kind: Literal["mutation", "access"] | None = None
    entity_type: str
    entity_id: UUID
    entity_label: str
    actor: AuditActor | None = None
    changed_count: int = 0
    created_at: datetime


class AuditEventDetailResponse(AuditEventListItem):
    request_id: str | None = None
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    resource_state: dict[str, Any] | None = None
    access_details: dict[str, Any] = Field(default_factory=dict)


class AuditFilterOptionsResponse(BaseModel):
    entity_types: list[str]
    commands: list[str]
    actors: list[AuditActor]


AuditEventListPage = PaginatedResponse[AuditEventListItem]
