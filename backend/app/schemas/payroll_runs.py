"""Pydantic schemas for payroll periods, runs, and draft inputs."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
)

from app.schemas.run_results import CurrentVersion


def _require_decimal_string(value: object) -> Decimal:
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
    model_config = ConfigDict(extra="forbid")

    period_id: UUID


class PayrollRunListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    period_id: UUID
    period_year: int
    period_month: int
    status: str
    lock_version: int
    created_at: datetime
    updated_at: datetime


class PayrollRunReportMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bill_number: str | None = None
    bill_date: date | None = None
    payment_date: date | None = None
    demand_number: str | None = None
    major_head: str | None = None
    sub_head: str | None = None
    detailed_head: str | None = None
    bank_advice_number: str | None = None
    bank_advice_date: date | None = None
    approval_note_number: str | None = None
    approval_note_date: date | None = None


class PayrollRunDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    period_id: UUID
    period_year: int
    period_month: int
    period_status: str
    status: str
    current_version: CurrentVersion | None = None
    lock_version: int
    roster_initialized: bool = False
    report_metadata: PayrollRunReportMetadata = Field(default_factory=PayrollRunReportMetadata)
    created_at: datetime
    updated_at: datetime


class ReportReadinessIssue(BaseModel):
    report_type: str
    code: str
    message: str


class ReportReadinessResponse(BaseModel):
    ready: bool
    issues: list[ReportReadinessIssue]


class PayrollRunEmployeeUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    payable_days: MoneyAmount = Field(ge=0, le=31)
    da_percent: RateValue | None = Field(default=None, ge=0, le=1000)
    # Signed by design: a gross adjustment that may recover a prior-period
    # overpayment. Bounded to the Numeric(12, 2) storage contract.
    da_difference: MoneyAmount | None = Field(
        default=None, ge=Decimal("-99999999.99"), le=Decimal("99999999.99")
    )
    hra_percent: RateValue | None = Field(default=None, ge=0, le=1000)
    transport_amount: MoneyAmount | None = Field(default=None, ge=0, le=Decimal("99999999.99"))


class PayrollRunRosterUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employees: list[PayrollRunEmployeeUpsert] = Field(min_length=1)


class PayrollRunEmployeeResponse(BaseModel):
    employee_id: UUID
    employee_number: str
    employee_name: str | None = None
    sevarth_id: str | None = None
    retirement_regime: str | None = None
    basic_pay: MoneyAmount | None = None
    selected: bool
    eligible: bool = True
    ineligible_reason: str | None = None
    payable_days: MoneyAmount
    da_percent: RateValue | None = None
    da_difference: MoneyAmount | None = None
    hra_percent: RateValue | None = None
    transport_amount: MoneyAmount | None = None


class PayrollRunRosterHistoryResponse(BaseModel):
    id: UUID
    action: str
    changed_employees: int
    selected_employees: int
    changed_fields: list[str]
    actor_name: str
    created_at: datetime


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
