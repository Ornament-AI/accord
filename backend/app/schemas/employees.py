"""Pydantic schemas for employee master data (Phase 3).

Sensitive fields (PAN, PRAN, GPF/EPF/pension account numbers, bank account
numbers) are masked by default via ``mask_value``. Money fields use canonical
decimal strings in JSON (ADR-0006).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    model_validator,
)

from app.schemas.pagination import PaginatedResponse

VersionKind = Literal["profile", "posting", "pay", "bank"]
SENSITIVE_PROFILE_FIELDS = (
    "pan",
    "pran",
    "gpf_account_number",
    "epf_number",
    "pension_account",
)


def mask_value(value: str | None) -> str | None:
    """Last-4 mask: ``••••1234`` when len > 4, else ``••••``; ``None`` stays ``None``."""
    if value is None:
        return None
    if len(value) > 4:
        return f"••••{value[-4:]}"
    if len(value) >= 1:
        return "••••"
    return "••••"


def _require_decimal_string(value: Any) -> Decimal:
    """Accept JSON decimal strings and in-process ``Decimal``; reject int/float."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or isinstance(value, (int, float)) or not isinstance(value, str):
        raise ValueError("Must be a decimal string")
    try:
        parsed = Decimal(value)
    except Exception as exc:
        raise ValueError("Invalid decimal string") from exc
    return parsed


def _serialize_money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


MoneyAmount = Annotated[
    Decimal,
    BeforeValidator(_require_decimal_string),
    PlainSerializer(_serialize_money, return_type=str),
]


class RetirementRegime(StrEnum):
    GPF = "gpf"
    NPS = "nps"
    EPF = "epf"


class GpfJurisdiction(StrEnum):
    MUMBAI = "mumbai"
    NAGPUR = "nagpur"


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    sevarth_id: str = Field(min_length=1)
    pan: str | None = None
    date_of_birth: date
    date_of_joining: date
    retirement_regime: RetirementRegime
    gpf_jurisdiction: GpfJurisdiction | None = None
    pran: str | None = None
    gpf_account_number: str | None = None
    epf_number: str | None = None
    pension_account: str | None = None

    @model_validator(mode="after")
    def _regime_jurisdiction_coupling(self) -> Self:
        if self.retirement_regime == RetirementRegime.GPF:
            if self.gpf_jurisdiction is None:
                raise ValueError("gpf_jurisdiction is required when retirement_regime is 'gpf'")
        elif self.gpf_jurisdiction is not None:
            raise ValueError(
                "gpf_jurisdiction must be absent when retirement_regime is "
                f"'{self.retirement_regime.value}'"
            )
        return self


class PostingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    office_id: UUID
    payroll_unit_id: UUID
    post_id: UUID
    employee_group_id: UUID | None = None


class PayInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pay_matrix_level: str = Field(min_length=1)
    basic_pay: MoneyAmount


class BankInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_number: str = Field(min_length=1)
    ifsc: str = Field(min_length=1)
    bank_name: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    is_primary_salary: bool = True


class CreateEmployeeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_number: str = Field(min_length=1)
    effective_from: date
    profile: ProfileInput
    posting: PostingInput | None = None
    pay: PayInput | None = None
    bank: BankInput | None = None
    change_reason: str | None = None


class CreateProfileVersionRequest(ProfileInput):
    effective_from: date
    change_reason: str | None = None


class CreatePostingVersionRequest(PostingInput):
    effective_from: date
    change_reason: str | None = None


class CreatePayVersionRequest(PayInput):
    effective_from: date
    change_reason: str | None = None


class CreateBankVersionRequest(BankInput):
    effective_from: date
    change_reason: str | None = None


class ProfileVersionResponse(BaseModel):
    id: UUID
    effective_from: date
    effective_to: date | None
    name: str
    sevarth_id: str
    pan: str | None
    date_of_birth: date
    date_of_joining: date
    retirement_regime: str
    gpf_jurisdiction: str | None
    pran: str | None
    gpf_account_number: str | None
    epf_number: str | None
    pension_account: str | None
    created_at: datetime
    created_by: UUID
    change_reason: str | None


class PostingVersionResponse(BaseModel):
    id: UUID
    effective_from: date
    effective_to: date | None
    office_id: UUID
    payroll_unit_id: UUID
    post_id: UUID
    employee_group_id: UUID | None
    created_at: datetime
    created_by: UUID
    change_reason: str | None


class PayVersionResponse(BaseModel):
    id: UUID
    effective_from: date
    effective_to: date | None
    pay_matrix_level: str
    basic_pay: MoneyAmount
    created_at: datetime
    created_by: UUID
    change_reason: str | None


class BankVersionResponse(BaseModel):
    id: UUID
    effective_from: date
    effective_to: date | None
    account_number: str
    ifsc: str
    bank_name: str
    branch: str
    is_primary_salary: bool
    created_at: datetime
    created_by: UUID
    change_reason: str | None


class EmployeeSummary(BaseModel):
    id: UUID
    employee_number: str
    name: str | None = None
    sevarth_id: str | None = None
    retirement_regime: str | None = None


class EmployeeDetail(BaseModel):
    id: UUID
    employee_number: str
    organization_id: UUID
    created_at: datetime
    updated_at: datetime
    as_of: date
    profile: ProfileVersionResponse | None = None
    posting: PostingVersionResponse | None = None
    pay: PayVersionResponse | None = None
    bank: BankVersionResponse | None = None


EmployeeListPage = PaginatedResponse[EmployeeSummary]


def _validity_bounds(validity: Any) -> tuple[date, date | None]:
    lower = validity.lower
    upper = validity.upper
    if upper is not None and hasattr(upper, "year"):
        return lower, upper
    return lower, None


def profile_from_row(row: Any, *, reveal: bool) -> ProfileVersionResponse:
    effective_from, effective_to = _validity_bounds(row["validity"])
    data = {
        "id": row["id"],
        "effective_from": effective_from,
        "effective_to": effective_to,
        "name": row["name"],
        "sevarth_id": row["sevarth_id"],
        "pan": row["pan"],
        "date_of_birth": row["date_of_birth"],
        "date_of_joining": row["date_of_joining"],
        "retirement_regime": row["retirement_regime"],
        "gpf_jurisdiction": row["gpf_jurisdiction"],
        "pran": row["pran"],
        "gpf_account_number": row["gpf_account_number"],
        "epf_number": row["epf_number"],
        "pension_account": row["pension_account"],
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "change_reason": row["change_reason"],
    }
    if not reveal:
        for field in SENSITIVE_PROFILE_FIELDS:
            data[field] = mask_value(data[field])
    return ProfileVersionResponse.model_validate(data)


def posting_from_row(row: Any) -> PostingVersionResponse:
    effective_from, effective_to = _validity_bounds(row["validity"])
    return PostingVersionResponse(
        id=row["id"],
        effective_from=effective_from,
        effective_to=effective_to,
        office_id=row["office_id"],
        payroll_unit_id=row["payroll_unit_id"],
        post_id=row["post_id"],
        employee_group_id=row["employee_group_id"],
        created_at=row["created_at"],
        created_by=row["created_by"],
        change_reason=row["change_reason"],
    )


def pay_from_row(row: Any) -> PayVersionResponse:
    effective_from, effective_to = _validity_bounds(row["validity"])
    basic_pay = row["basic_pay"]
    if not isinstance(basic_pay, Decimal):
        basic_pay = Decimal(str(basic_pay))
    return PayVersionResponse(
        id=row["id"],
        effective_from=effective_from,
        effective_to=effective_to,
        pay_matrix_level=row["pay_matrix_level"],
        basic_pay=basic_pay,
        created_at=row["created_at"],
        created_by=row["created_by"],
        change_reason=row["change_reason"],
    )


def bank_from_row(row: Any, *, reveal: bool) -> BankVersionResponse:
    effective_from, effective_to = _validity_bounds(row["validity"])
    account_number = row["account_number"]
    if not reveal:
        account_number = mask_value(account_number)
    return BankVersionResponse(
        id=row["id"],
        effective_from=effective_from,
        effective_to=effective_to,
        account_number=account_number if account_number is not None else "",
        ifsc=row["ifsc"],
        bank_name=row["bank_name"],
        branch=row["branch"],
        is_primary_salary=bool(row["is_primary_salary"]),
        created_at=row["created_at"],
        created_by=row["created_by"],
        change_reason=row["change_reason"],
    )
