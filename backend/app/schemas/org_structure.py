"""Pydantic schemas for organization-structure master data."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Jurisdiction = Literal["mumbai", "nagpur", "worli", "other"]


class OfficeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    jurisdiction: Jurisdiction


class OfficeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    jurisdiction: Jurisdiction | None = None


class OfficeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    jurisdiction: str
    created_at: datetime
    updated_at: datetime


class PostCreate(BaseModel):
    designation: str = Field(min_length=1)
    class_name: str = Field(min_length=1)


class PostUpdate(BaseModel):
    designation: str | None = None
    class_name: str | None = None


class PostResponse(BaseModel):
    id: UUID
    designation: str
    class_name: str
    created_at: datetime
    updated_at: datetime
