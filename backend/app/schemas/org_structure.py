"""Pydantic schemas for org-structure master data and organization settings."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, Field, field_validator

Jurisdiction = Literal["mumbai", "nagpur", "worli", "other"]

_LOCALE_RE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")
_VALID_TIMEZONES = available_timezones()


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


class OrganizationSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    locale: str
    timezone: str
    currency: str
    financial_year_start_month: int
    created_at: datetime
    updated_at: datetime


class OrganizationSettingsUpdate(BaseModel):
    locale: str | None = None
    timezone: str | None = None
    currency: str | None = None
    financial_year_start_month: int | None = None

    @field_validator("locale")
    @classmethod
    def _validate_locale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _LOCALE_RE.fullmatch(value):
            raise ValueError("Locale must match the pattern xx-YY (e.g. en-IN).")
        return value

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in _VALID_TIMEZONES:
            raise ValueError("Timezone must be a valid IANA timezone identifier.")
        return value

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) != 3 or not value.isalpha():
            raise ValueError("Currency must be a 3-letter ISO 4217 code.")
        return value.upper()

    @field_validator("financial_year_start_month")
    @classmethod
    def _validate_financial_year_start_month(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if not 1 <= value <= 12:
            raise ValueError("Financial year start month must be between 1 and 12.")
        return value
