"""Pydantic schemas for auth identity endpoints."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class SwitchOrganizationRequest(BaseModel):
    organization_id: UUID


class MeOrganization(BaseModel):
    id: str
    name: str
    slug: str
    role: str


class MeActiveOrganization(MeOrganization):
    capabilities: list[str] = Field(default_factory=list)


class MeResponse(BaseModel):
    id: str
    email: str
    name: str
    is_platform_admin: bool
    active_organization: MeActiveOrganization | None
    organizations: list[MeOrganization]
