"""Pydantic schemas for pay-setup master data (Phase 3).

``percentage_of_component_bases`` requires ``rate`` (the percentage applied to
basis component amounts) in addition to a non-empty ``basis`` code list.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from app.schemas.money import MoneyAmount, RateValue

# TODO: reconcile with a shared money schema type if one lands in app/domain or app/schemas/common


REPORT_CONFIG_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class Classification(StrEnum):
    EARNING = "earning"
    EMPLOYER_CONTRIBUTION = "employer_contribution"
    AG_DEDUCTION = "ag_deduction"
    TREASURY_DEDUCTION = "treasury_deduction"
    GROSS_ADJUSTMENT = "gross_adjustment"
    EXTERNAL_RECOVERY = "external_recovery"
    INFORMATIONAL = "informational"


class CalcKind(StrEnum):
    FIXED_RECURRING_AMOUNT = "fixed_recurring_amount"
    DIRECT_MONTHLY_AMOUNT = "direct_monthly_amount"
    PERCENTAGE_OF_COMPONENT_BASES = "percentage_of_component_bases"
    EMPLOYER_EMPLOYEE_CONTRIBUTION = "employer_employee_contribution"
    LOAN_INSTALLMENT_RECOVERY = "loan_installment_recovery"
    ACCOMMODATION_CHARGE = "accommodation_charge"
    ONE_TIME_ADJUSTMENT = "one_time_adjustment"


class RoundingRule(StrEnum):
    ROUND_HALF_UP_RUPEE = "ROUND_HALF_UP_RUPEE"
    ROUND_HALF_UP_PAISE = "ROUND_HALF_UP_PAISE"
    ROUND_DOWN_RUPEE = "ROUND_DOWN_RUPEE"


class AdvanceType(StrEnum):
    HBA = "hba"
    GPF_ADVANCE = "gpf_advance"
    FESTIVAL = "festival"
    MOTOR_CAR = "motor_car"
    MOTORCYCLE = "motorcycle"
    OTHER = "other"


class QuartersLocation(StrEnum):
    MUMBAI = "mumbai"
    WORLI = "worli"
    OTHER = "other"


class ScheduleKind(StrEnum):
    SIMPLE_COMPONENT = "simple_component"
    LOAN_INSTALLMENT = "loan_installment"


class PayComponentCreate(BaseModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    classification: Classification
    display_order: int = 0
    # Employer-transfer pairing drives off-bill remittance and disbursement
    # (docs/payroll-domain.md "Resolved"). ``transfer_of`` names the
    # employer_contribution code this line reverses; leave it null on an
    # employer-transfer line to mark the transfer as off-bill (NPS employer).
    employer_transfer: bool = False
    transfer_of: str | None = None
    schedule_kind: ScheduleKind | None = None
    schedule_title: str | None = Field(default=None, min_length=1)
    schedule_account_head: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _transfer_of_requires_employer_transfer(self) -> "PayComponentCreate":
        if self.transfer_of is not None and not self.employer_transfer:
            raise ValueError("transfer_of requires employer_transfer=true")
        if self.employer_transfer and self.classification not in {
            Classification.AG_DEDUCTION,
            Classification.TREASURY_DEDUCTION,
            Classification.EXTERNAL_RECOVERY,
        }:
            raise ValueError("employer_transfer requires a deduction classification")
        return self

    @field_validator("transfer_of")
    @classmethod
    def _strip_optional_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("transfer_of must not be empty")
        return stripped

    @field_validator("code", "name")
    @classmethod
    def _strip_nonempty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty or whitespace-only")
        return stripped


class PayComponentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    display_order: int | None = None
    is_active: bool | None = None
    employer_transfer: bool | None = None
    transfer_of: str | None = None
    schedule_kind: ScheduleKind | None = None
    schedule_title: str | None = Field(default=None, min_length=1)
    schedule_account_head: str | None = Field(default=None, min_length=1)

    @field_validator("name", "display_order", "is_active", "employer_transfer")
    @classmethod
    def _reject_null_non_nullable_updates(cls, value: Any) -> Any:
        # Omitted fields keep their defaults without running this validator.
        # Only transfer_of may be explicitly null, because null clears a pairing.
        if value is None:
            raise ValueError("must not be null")
        return value

    @field_validator("transfer_of")
    @classmethod
    def _strip_optional_transfer_of(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("transfer_of must not be empty")
        return stripped

    @model_validator(mode="after")
    def _at_least_one_field(self) -> PayComponentUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one updatable field is required.")
        return self


class PayComponentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    classification: str
    is_active: bool
    display_order: int
    employer_transfer: bool
    transfer_of: str | None
    is_standard: bool
    schedule_kind: str | None
    schedule_title: str | None
    schedule_account_head: str | None
    created_at: datetime
    updated_at: datetime


class ComponentRateVersionCreate(BaseModel):
    effective_from: date
    calc_kind: CalcKind
    rate: RateValue | None = None
    amount: MoneyAmount | None = None
    basis: list[str] | None = None
    rounding_rule: RoundingRule
    change_reason: str | None = None

    @model_validator(mode="after")
    def _validate_calc_kind_matrix(self) -> ComponentRateVersionCreate:
        kind = self.calc_kind
        if kind == CalcKind.PERCENTAGE_OF_COMPONENT_BASES:
            if self.rate is None:
                raise ValueError("rate is required for percentage_of_component_bases")
            if not self.basis:
                raise ValueError("basis is required for percentage_of_component_bases")
            if self.amount is not None:
                raise ValueError("amount must be absent for percentage_of_component_bases")
        elif kind in {CalcKind.FIXED_RECURRING_AMOUNT, CalcKind.DIRECT_MONTHLY_AMOUNT}:
            if self.amount is None:
                raise ValueError(f"amount is required for {kind.value}")
            if self.rate is not None:
                raise ValueError(f"rate must be absent for {kind.value}")
            if self.basis is not None:
                raise ValueError(f"basis must be absent for {kind.value}")
        elif kind == CalcKind.EMPLOYER_EMPLOYEE_CONTRIBUTION:
            if self.rate is None:
                raise ValueError("rate is required for employer_employee_contribution")
            if self.amount is not None:
                raise ValueError("amount must be absent for employer_employee_contribution")
        return self


class VersionResponse(BaseModel):
    id: UUID
    effective_from: date
    effective_to: date | None
    created_at: datetime
    created_by: UUID
    change_reason: str | None = None


class ComponentRateVersionResponse(VersionResponse):
    rate: str | None = None
    amount: str | None = None
    calc_kind: str
    basis: list[str] | None = None
    rounding_rule: str


class RecurringInstructionCreate(BaseModel):
    component_id: UUID
    effective_from: date
    amount: MoneyAmount | None = None
    rate: RateValue | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _require_amount_or_rate(self) -> RecurringInstructionCreate:
        if self.amount is None and self.rate is None:
            raise ValueError("At least one of amount or rate is required.")
        return self


class RecurringInstructionVersionCreate(BaseModel):
    effective_from: date | None = None
    amount: MoneyAmount | None = None
    rate: RateValue | None = None
    reason: str | None = None
    end_on: date | None = None
    change_reason: str | None = None

    @model_validator(mode="after")
    def _validate_mode(self) -> RecurringInstructionVersionCreate:
        terminate = self.end_on is not None
        new_version = self.effective_from is not None
        if terminate and new_version:
            raise ValueError("end_on cannot be combined with effective_from.")
        if terminate:
            if self.amount is not None or self.rate is not None:
                raise ValueError("amount and rate must be absent when end_on is provided.")
            return self
        if not new_version:
            raise ValueError("Either effective_from or end_on is required.")
        if self.amount is None and self.rate is None:
            raise ValueError("At least one of amount or rate is required for a new version.")
        return self


class RecurringInstructionVersionResponse(VersionResponse):
    amount: str | None = None
    rate: str | None = None
    reason: str | None = None


class RecurringInstructionResponse(BaseModel):
    id: UUID
    employee_id: UUID
    component_id: UUID
    created_at: datetime
    updated_at: datetime
    amount: str | None = None
    rate: str | None = None
    reason: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    version_id: UUID | None = None


class AdvanceInstallmentInput(BaseModel):
    installment_amount: MoneyAmount
    installments_total: int = Field(gt=0)
    installments_recovered_opening: int = Field(ge=0)
    effective_from: date


class AdvanceCreate(BaseModel):
    advance_type: AdvanceType
    principal: MoneyAmount
    sanctioned_on: date
    reference: str | None = None
    installment: AdvanceInstallmentInput

    @model_validator(mode="after")
    def _validate_installment(self) -> AdvanceCreate:
        if self.principal <= Decimal("0"):
            raise ValueError("principal must be greater than zero.")
        inst = self.installment
        if inst.installment_amount > self.principal:
            raise ValueError("installment_amount must not exceed principal.")
        if inst.installments_recovered_opening > inst.installments_total:
            raise ValueError("installments_recovered_opening must not exceed installments_total.")
        return self


class AdvanceInstallmentVersionCreate(BaseModel):
    effective_from: date
    installment_amount: MoneyAmount
    installments_total: int = Field(gt=0)
    installments_recovered_opening: int = Field(ge=0)
    change_reason: str | None = None


class AdvanceInstallmentVersionResponse(VersionResponse):
    installment_amount: str
    installments_total: int
    installments_recovered_opening: int


class AdvanceResponse(BaseModel):
    id: UUID
    employee_id: UUID
    advance_type: str
    principal: str
    sanctioned_on: date
    reference: str | None
    created_at: datetime
    updated_at: datetime
    installment_amount: str | None = None
    installments_total: int | None = None
    installments_recovered_opening: int | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    version_id: UUID | None = None


class AccommodationChargeInput(BaseModel):
    license_fee: MoneyAmount
    informational_hra_foregone: MoneyAmount | None = None
    effective_from: date


class AccommodationCreate(BaseModel):
    quarters_location: QuartersLocation
    quarters_identifier: str = Field(min_length=1)
    charge: AccommodationChargeInput


class AccommodationChargeVersionCreate(BaseModel):
    effective_from: date
    license_fee: MoneyAmount
    informational_hra_foregone: MoneyAmount | None = None
    change_reason: str | None = None


class AccommodationChargeVersionResponse(VersionResponse):
    license_fee: str
    informational_hra_foregone: str | None = None


class AccommodationResponse(BaseModel):
    id: UUID
    employee_id: UUID
    quarters_location: str
    quarters_identifier: str
    created_at: datetime
    updated_at: datetime
    license_fee: str | None = None
    informational_hra_foregone: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    version_id: UUID | None = None


class ReportConfigurationResponse(BaseModel):
    key: str
    value: Any
    updated_at: datetime


class ReportConfigurationUpsert(BaseModel):
    value: Any


class HeadOfAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    demand_number: str | None = None
    major_head: str | None = None
    sub_head: str | None = None
    detailed_head: str | None = None


class BankAdviceRecipient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bank_name: str | None = None
    branch: str | None = None
    address_lines: list[str] = Field(default_factory=list)


class ReportSignatory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    name: str
    designation: str


class PayrollExportProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_name: str | None = None
    office_name: str | None = None
    address_lines: list[str] = Field(default_factory=list)
    cin: str | None = None
    phone: str | None = None
    website: str | None = None
    ddo_name: str | None = None
    ddo_code: str | None = None
    department_code: str | None = None
    treasury_code: str | None = None
    head_of_account: HeadOfAccount = Field(default_factory=HeadOfAccount)
    bank_advice_recipient: BankAdviceRecipient = Field(default_factory=BankAdviceRecipient)
    salary_reference_prefix: str | None = None
    signatories: list[ReportSignatory] = Field(default_factory=list)


class PayrollExportProfileResponse(BaseModel):
    value: PayrollExportProfile
    updated_at: datetime | None = None
