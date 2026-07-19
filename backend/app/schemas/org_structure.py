"""Pydantic schemas for organization-structure master data."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Jurisdiction = Literal["mumbai", "nagpur", "worli", "other"]


class OfficeCreate(BaseModel):
    name: str = Field(min_length=1)
    code: str = Field(min_length=1)
    jurisdiction: Jurisdiction


class OfficeUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    jurisdiction: Jurisdiction | None = None


class OfficeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str
    jurisdiction: str
    created_at: datetime
    updated_at: datetime


class PayrollUnitCreate(BaseModel):
    name: str = Field(min_length=1)
    code: str = Field(min_length=1)


class PayrollUnitUpdate(BaseModel):
    name: str | None = None
    code: str | None = None


class PayrollUnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str
    created_at: datetime
    updated_at: datetime


class EmployeeGroupCreate(BaseModel):
    name: str = Field(min_length=1)
    code: str = Field(min_length=1)


class EmployeeGroupUpdate(BaseModel):
    name: str | None = None
    code: str | None = None


class EmployeeGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str
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
