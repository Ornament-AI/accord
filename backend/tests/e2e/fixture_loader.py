"""Parse the sanitized June 2026 golden fixture into seedable structures."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "sanitized" / "june-2026"

# Fixture classification → pay-component catalog API classification.
# ``informational`` is not accepted by PayComponentCreate (product gap).
_CLASSIFICATION_TO_API: dict[str, str] = {
    "earning": "earning",
    "employer_contribution": "employer_contribution",
    "AG_deduction": "ag_deduction",
    "treasury_deduction": "treasury_deduction",
    "gross_adjustment": "gross_adjustment",
    "external_recovery": "external_recovery",
}

# Components resolved by recurring instructions (need catalog rate versions).
RECURRING_COMPONENT_CODES = frozenset(
    {
        "DA",
        "HRA",
        "TRANSPORT",
        "OTHER_ALLOWANCE",
        "GPF_SUBSCRIPTION",
        "NPS_EMPLOYEE",
        "NPS_EMPLOYER_TRANSFER",
        "EPF_EMPLOYEE",
        "EPF_EMPLOYER",
        "EPF_EMPLOYER_TRANSFER",
        "INCOME_TAX",
        "PROFESSIONAL_TAX",
        "GIS",
    }
)

ADVANCE_COMPONENT_CODES = frozenset({"HBA_INSTALLMENT"})
ACCOMMODATION_COMPONENT_CODES = frozenset({"ACCOMMODATION_LICENSE_FEE", "FOREGONE_HRA"})
BASIC_CODE = "BASIC"


@dataclass(frozen=True)
class OfficeSeed:
    fixture_id: str
    name: str
    code: str
    jurisdiction: str
    city: str


@dataclass(frozen=True)
class ComponentSeed:
    code: str
    name: str
    fixture_classification: str
    api_classification: str | None
    informational: bool = False
    excluded_from_totals: bool = False
    # Employer-transfer pairing drives off-bill remittance / disbursement.
    # ``transfer_of`` is None for off-bill transfers (NPS employer).
    employer_transfer: bool = False
    transfer_of: str | None = None


@dataclass(frozen=True)
class PayLineSeed:
    component_code: str
    classification: str
    amount: Decimal
    informational: bool = False
    excluded_from_totals: bool = False
    gpf_jurisdiction: str | None = None
    accommodation_location: str | None = None


@dataclass(frozen=True)
class AccommodationSeed:
    location: str
    office_id: str


@dataclass
class EmployeeSeed:
    fixture_id: str
    name: str
    sevarth_id: str
    pan: str
    bank_account: str
    ifsc: str
    regime: str
    office_id: str
    jurisdiction: str
    professional_tax_liable: bool
    gpf_account: str | None = None
    pran: str | None = None
    epf_number: str | None = None
    accommodation: AccommodationSeed | None = None
    lines: list[PayLineSeed] = field(default_factory=list)


@dataclass(frozen=True)
class OrganizationSeed:
    name: str
    period: str
    offices: list[OfficeSeed]
    pay_unit_name: str
    pay_unit_code: str


@dataclass(frozen=True)
class ExpectedTotals:
    aggregates: dict[str, str]
    raw: dict[str, Any]


@dataclass(frozen=True)
class JuneFixture:
    organization: OrganizationSeed
    components: list[ComponentSeed]
    employees: list[EmployeeSeed]
    expected: ExpectedTotals


def _load_json(name: str) -> dict[str, Any]:
    with (_FIXTURE_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def money(value: str | Decimal) -> Decimal:
    """Whole-rupee fixture amounts as Decimal (canonical two-place later)."""
    return Decimal(str(value))


def money_str(value: str | Decimal) -> str:
    """Canonical money string for API bodies (``82000`` → ``82000.00``)."""
    return f"{money(value).quantize(Decimal('0.01'))}"


def map_regime(fixture_regime: str) -> tuple[str, str | None]:
    """Map fixture regime tag → (retirement_regime, gpf_jurisdiction)."""
    if fixture_regime == "gpf_mumbai":
        return "gpf", "mumbai"
    if fixture_regime == "gpf_nagpur":
        return "gpf", "nagpur"
    if fixture_regime == "nps":
        return "nps", None
    if fixture_regime == "epf":
        return "epf", None
    raise ValueError(f"Unknown fixture regime {fixture_regime!r}")


def map_quarters_location(location: str) -> str:
    return location.strip().lower()


def load_june_fixture() -> JuneFixture:
    org_doc = _load_json("organization.json")
    components_doc = _load_json("components.json")
    employees_doc = _load_json("employees.json")
    pay_doc = _load_json("pay.json")
    expected_doc = _load_json("expected_totals.json")

    offices = [
        OfficeSeed(
            fixture_id=office["office_id"],
            name=office["name"],
            code=office["office_id"],
            jurisdiction=office["city"].strip().lower(),
            city=office["city"],
        )
        for office in org_doc["offices"]
    ]
    pay_unit = org_doc["pay_units"][0]
    organization = OrganizationSeed(
        name=org_doc["name"],
        period=org_doc["period"],
        offices=offices,
        pay_unit_name=pay_unit["name"],
        pay_unit_code=pay_unit["pay_unit_id"],
    )

    components: list[ComponentSeed] = []
    for row in components_doc["components"]:
        fixture_cls = row["classification"]
        components.append(
            ComponentSeed(
                code=row["code"],
                name=row["name"],
                fixture_classification=fixture_cls,
                api_classification=_CLASSIFICATION_TO_API.get(fixture_cls),
                informational=bool(row.get("informational", False)),
                excluded_from_totals=bool(row.get("excluded_from_totals", False)),
                employer_transfer=bool(row.get("employer_transfer", False)),
                transfer_of=row.get("pairs_with"),
            )
        )

    pay_by_employee = {emp["employee_id"]: emp for emp in pay_doc["employees"]}
    employees: list[EmployeeSeed] = []
    for row in employees_doc["employees"]:
        acc_raw = row.get("accommodation")
        accommodation = None
        if acc_raw is not None:
            accommodation = AccommodationSeed(
                location=acc_raw["location"],
                office_id=acc_raw["office_id"],
            )
        pay_emp = pay_by_employee[row["employee_id"]]
        lines = [
            PayLineSeed(
                component_code=line["component_code"],
                classification=line["classification"],
                amount=money(line["amount"]),
                informational=bool(line.get("informational", False)),
                excluded_from_totals=bool(line.get("excluded_from_totals", False)),
                gpf_jurisdiction=(
                    line["gpf_jurisdiction"].strip().lower()
                    if line.get("gpf_jurisdiction")
                    else None
                ),
                accommodation_location=(
                    line["accommodation_location"].strip().lower()
                    if line.get("accommodation_location")
                    else None
                ),
            )
            for line in pay_emp["lines"]
        ]
        employees.append(
            EmployeeSeed(
                fixture_id=row["employee_id"],
                name=row["name"],
                sevarth_id=row["sevarth_id"],
                pan=row["pan"],
                bank_account=row["bank_account"],
                ifsc=row["ifsc"],
                regime=row["regime"],
                office_id=row["office_id"],
                jurisdiction=row["jurisdiction"],
                professional_tax_liable=bool(row["professional_tax_liable"]),
                gpf_account=row.get("gpf_account"),
                pran=row.get("pran"),
                epf_number=row.get("epf_number"),
                accommodation=accommodation,
                lines=lines,
            )
        )

    return JuneFixture(
        organization=organization,
        components=components,
        employees=employees,
        expected=ExpectedTotals(
            aggregates=dict(expected_doc["aggregates"]),
            raw=expected_doc,
        ),
    )


def line_amount(employee: EmployeeSeed, component_code: str) -> Decimal | None:
    for line in employee.lines:
        if line.component_code == component_code:
            return line.amount
    return None
