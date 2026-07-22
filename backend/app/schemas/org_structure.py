"""Pydantic schemas for organization-structure master data."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    model_config = ConfigDict(extra="forbid")

    designation: str = Field(min_length=1)
    pay_bill_heading: str | None = Field(default=None, min_length=1)
    class_name: str = Field(min_length=1)
    sanctioned_strength: int | None = Field(default=None, ge=0)
    vacant_count: int | None = Field(default=None, ge=0)
    pay_scale: str | None = Field(default=None, min_length=1)
    display_order: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_strength(self) -> "PostCreate":
        if self.vacant_count is not None and self.sanctioned_strength is None:
            raise ValueError("sanctioned_strength is required when vacant_count is provided")
        if (
            self.vacant_count is not None
            and self.sanctioned_strength is not None
            and self.vacant_count > self.sanctioned_strength
        ):
            raise ValueError("vacant_count must not exceed sanctioned_strength")
        return self


class PostUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    designation: str | None = None
    pay_bill_heading: str | None = Field(default=None, min_length=1)
    class_name: str | None = None
    sanctioned_strength: int | None = Field(default=None, ge=0)
    vacant_count: int | None = Field(default=None, ge=0)
    pay_scale: str | None = Field(default=None, min_length=1)
    display_order: int | None = Field(default=None, ge=0)


class PostResponse(BaseModel):
    id: UUID
    designation: str
    pay_bill_heading: str | None
    class_name: str
    sanctioned_strength: int | None
    vacant_count: int | None
    pay_scale: str | None
    display_order: int | None
    created_at: datetime
    updated_at: datetime
