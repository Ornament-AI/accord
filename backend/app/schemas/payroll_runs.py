"""Pydantic schemas for payroll periods, runs, and draft inputs."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
)


def _require_decimal_string(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str):
        raise ValueError("Must be a decimal string")
    try:
        parsed = Decimal(value)
    except Exception as exc:
        raise ValueError("Invalid decimal string") from exc
    if not parsed.is_finite():
        raise ValueError("Decimal must be finite")
    return parsed


def _serialize_money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


def _serialize_rate(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.0001'))}"


MoneyAmount = Annotated[
    Decimal,
    BeforeValidator(_require_decimal_string),
    PlainSerializer(_serialize_money, return_type=str),
]
RateValue = Annotated[
    Decimal,
    BeforeValidator(_require_decimal_string),
    PlainSerializer(_serialize_rate, return_type=str),
]


class RunType(StrEnum):
    REGULAR = "regular"
    SUPPLEMENTAL = "supplemental"
    REVERSAL = "reversal"


class InputKind(StrEnum):
    EXCEPTION = "exception"
    OVERRIDE = "override"
    ONE_TIME = "one_time"


class PayrollPeriodCreate(BaseModel):
    period_year: int = Field(ge=1900, le=9999)
    period_month: int = Field(ge=1, le=12)


class PayrollPeriodResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    period_year: int
    period_month: int
    status: str
    created_at: datetime
    updated_at: datetime


class PayrollRunCreate(BaseModel):
    period_id: UUID
    run_type: RunType = RunType.REGULAR


class PayrollRunListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    period_id: UUID
    period_year: int
    period_month: int
    run_type: str
    status: str
    lock_version: int
    created_at: datetime
    updated_at: datetime


class PayrollRunDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    period_id: UUID
    period_year: int
    period_month: int
    period_status: str
    run_type: str
    status: str
    current_version: dict[str, Any] | None = None
    lock_version: int
    created_at: datetime
    updated_at: datetime


class PayrollRunInputUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_kind: InputKind
    amount: MoneyAmount | None = None
    rate: RateValue | None = None
    reason: str = Field(min_length=1)
    service_period_start: date | None = None
    service_period_end: date | None = None
    expected_version: int | None = None

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty or whitespace-only")
        return stripped


class PayrollRunInputResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    employee_id: UUID
    component_code: str
    input_kind: str
    amount: MoneyAmount | None
    rate: RateValue | None
    reason: str
    service_period_start: date | None
    service_period_end: date | None
    version: int
    created_by: UUID
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime
