"""Pydantic schemas for auth identity endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, SecretStr

AccessState = Literal["unbootstrapped", "unprovisioned", "active"]


class MeOrganization(BaseModel):
    id: str
    name: str
    slug: str


class MeMembership(BaseModel):
    role: str
    capabilities: list[str] = Field(default_factory=list)


class MeResponse(BaseModel):
    id: str
    email: str
    name: str
    is_platform_admin: bool
    access_state: AccessState
    organization: MeOrganization | None
    membership: MeMembership | None


class PasswordLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=1024)


class MagicCodeRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class MagicCodeLoginRequest(MagicCodeRequest):
    code: str = Field(min_length=6, max_length=16)
