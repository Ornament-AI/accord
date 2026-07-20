"""Resolution of master data into typed engine inputs.

Resolution scope (as-of the run period's calendar month-end date)
-----------------------------------------------------------------
**In scope (resolved and fed into the engine):**

- Active employees: those with an active ``employee_profile_versions`` row on
  the as-of date (regime / jurisdiction from that profile).
- Employee pay version: ``basic_pay`` becomes a ``BASIC`` ``ComponentInput``
  (classification from the ``BASIC`` catalog row when present, else
  ``earning``; ``calc_kind=fixed_recurring_amount``).
- Recurring instructions with an active version: amount/rate from the
  instruction version, plus ``calc_kind`` / basis / rounding_rule (and
  fallback amount/rate) from the component's active rate version.
- Advances with an active installment version: one
  ``loan_installment_recovery`` line per account (component code from
  advance-type convention; classification from catalog).
- Accommodation with an active charge version: an ``accommodation_charge``
  license-fee line plus an informational / excluded ``FOREGONE_HRA`` line
  when ``informational_hra_foregone`` is set.
- Run draft inputs (``payroll_run_inputs``):
  - ``override`` — replaces the amount on an already-resolved component
    (or creates a ``direct_monthly_amount`` line if none exists).
  - ``exception`` — adds a ``direct_monthly_amount`` line.
  - ``one_time`` — adds a ``one_time_adjustment`` line.

**Out of scope for this lane:**

- Org-wide ``component_rate_versions`` that would apply automatically to every
  employee without a recurring instruction / run input / advance /
  accommodation source (e.g. statutory percentage tables applied en masse).
- Posting / workflow transitions beyond ``draft|calculated`` → ``calculating``
  → ``calculated``.
- Regime exclusivity enforcement and reversal semantics beyond
  feeding the typed engine inputs above.
"""

from __future__ import annotations

import calendar
import dataclasses
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.payroll.inputs import ComponentInput, EmployeeCalcInput, RunCalcInput
from app.domain.payroll.money import Money
from app.domain.payroll.rates import Rate
from app.domain.payroll.rounding import ROUND_HALF_UP_PAISE, ROUND_NONE, apply as apply_rounding
from app.exceptions import ConflictError, ValidationError
from app.models.accommodation import AccommodationAssignment, accommodation_charge_versions
from app.models.advances import AdvanceAccount, advance_installment_versions
from app.models.employees import (
    Employee,
    employee_pay_versions,
    employee_profile_versions,
)
from app.models.pay_components import PayComponent, component_rate_versions
from app.models.payroll_runs import (
    PayrollPeriod,
    PayrollRun,
    PayrollRunEmployee,
    PayrollRunInput,
)
from app.models.recurring_instructions import (
    RecurringInstruction,
    recurring_instruction_versions,
)
from app.services import versioning
from app.services.run_calculation._convert import (
    basis_tuple,
    money_or_none,
    month_end,
    period_label,
    rate_or_none,
    to_domain_classification,
)

_BASIC_CODE = "BASIC"
_ACCOMMODATION_LICENSE_FEE_CODE = "ACCOMMODATION_LICENSE_FEE"
_FOREGONE_HRA_CODE = "FOREGONE_HRA"

_ADVANCE_COMPONENT_CODES: dict[str, str] = {
    "hba": "HBA_INSTALLMENT",
    "gpf_advance": "GPF_ADVANCE_INSTALLMENT",
    "festival": "FESTIVAL_ADVANCE_INSTALLMENT",
    "motor_car": "MOTOR_CAR_ADVANCE_INSTALLMENT",
    "motorcycle": "MOTORCYCLE_ADVANCE_INSTALLMENT",
    "other": "OTHER_ADVANCE_INSTALLMENT",
}


async def load_component_catalog(
    db: AsyncSession,
    *,
    organization_id: UUID,
) -> dict[str, PayComponent]:
    stmt = sa.select(PayComponent).where(PayComponent.organization_id == organization_id)
    rows = (await db.execute(stmt)).scalars().all()
    return {row.code: row for row in rows}


@dataclasses.dataclass(frozen=True)
class _ResolvedMasterData:
    """Batched as-of master data for the selected employees.

    Loaded once per calculate (constant query count regardless of roster
    size) and consumed per employee via dict lookups.
    """

    pay_by_employee: Mapping[UUID, Any]
    instructions_by_employee: Mapping[UUID, list[RecurringInstruction]]
    ri_version_by_instruction: Mapping[UUID, Any]
    rate_version_by_component: Mapping[UUID, Any]
    component_by_id: Mapping[UUID, PayComponent]
    advances_by_employee: Mapping[UUID, list[AdvanceAccount]]
    installment_by_advance: Mapping[UUID, Any]
    assignments_by_employee: Mapping[UUID, list[AccommodationAssignment]]
    charge_by_assignment: Mapping[UUID, Any]


async def _load_master_data(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee_ids: list[UUID],
    on_date: date,
    catalog: dict[str, PayComponent],
) -> _ResolvedMasterData:
    pay_by_employee = await versioning.get_active_versions_map(
        db,
        employee_pay_versions,
        header_ids=employee_ids,
        organization_id=organization_id,
        on_date=on_date,
    )

    instructions_by_employee: dict[UUID, list[RecurringInstruction]] = {}
    instructions = (
        (
            await db.execute(
                sa.select(RecurringInstruction)
                .where(RecurringInstruction.organization_id == organization_id)
                .where(RecurringInstruction.employee_id.in_(employee_ids))
                .order_by(RecurringInstruction.created_at)
            )
        )
        .scalars()
        .all()
        if employee_ids
        else []
    )
    for instruction in instructions:
        instructions_by_employee.setdefault(instruction.employee_id, []).append(instruction)
    ri_version_by_instruction = await versioning.get_active_versions_map(
        db,
        recurring_instruction_versions,
        header_ids=[instruction.id for instruction in instructions],
        organization_id=organization_id,
        on_date=on_date,
    )
    rate_version_by_component = await versioning.get_active_versions_map(
        db,
        component_rate_versions,
        header_ids=list(
            {
                instruction.component_id
                for instruction in instructions
                if instruction.id in ri_version_by_instruction
            }
        ),
        organization_id=organization_id,
        on_date=on_date,
    )

    advances_by_employee: dict[UUID, list[AdvanceAccount]] = {}
    advances = (
        (
            await db.execute(
                sa.select(AdvanceAccount)
                .where(AdvanceAccount.organization_id == organization_id)
                .where(AdvanceAccount.employee_id.in_(employee_ids))
                .order_by(AdvanceAccount.created_at)
            )
        )
        .scalars()
        .all()
        if employee_ids
        else []
    )
    for advance in advances:
        advances_by_employee.setdefault(advance.employee_id, []).append(advance)
    installment_by_advance = await versioning.get_active_versions_map(
        db,
        advance_installment_versions,
        header_ids=[advance.id for advance in advances],
        organization_id=organization_id,
        on_date=on_date,
    )

    assignments_by_employee: dict[UUID, list[AccommodationAssignment]] = {}
    assignments = (
        (
            await db.execute(
                sa.select(AccommodationAssignment)
                .where(AccommodationAssignment.organization_id == organization_id)
                .where(AccommodationAssignment.employee_id.in_(employee_ids))
                .order_by(AccommodationAssignment.created_at)
            )
        )
        .scalars()
        .all()
        if employee_ids
        else []
    )
    for assignment in assignments:
        assignments_by_employee.setdefault(assignment.employee_id, []).append(assignment)
    charge_by_assignment = await versioning.get_active_versions_map(
        db,
        accommodation_charge_versions,
        header_ids=[assignment.id for assignment in assignments],
        organization_id=organization_id,
        on_date=on_date,
    )

    return _ResolvedMasterData(
        pay_by_employee=pay_by_employee,
        instructions_by_employee=instructions_by_employee,
        ri_version_by_instruction=ri_version_by_instruction,
        rate_version_by_component=rate_version_by_component,
        component_by_id={component.id: component for component in catalog.values()},
        advances_by_employee=advances_by_employee,
        installment_by_advance=installment_by_advance,
        assignments_by_employee=assignments_by_employee,
        charge_by_assignment=charge_by_assignment,
    )


def _put_component(
    by_code: dict[str, ComponentInput],
    comp: ComponentInput,
    *,
    replace: bool = False,
) -> None:
    if comp.component_code in by_code and not replace:
        raise ValidationError(
            f"Duplicate component_code {comp.component_code!r} while resolving "
            "employee calculation inputs."
        )
    by_code[comp.component_code] = comp


def _resolve_employee_components(
    *,
    employee: Employee,
    profile: Any,
    on_date: date,
    catalog: dict[str, PayComponent],
    master: _ResolvedMasterData,
    roster_row: PayrollRunEmployee | None,
    period_days: int,
    run_inputs: list[PayrollRunInput],
) -> EmployeeCalcInput:
    by_code: dict[str, ComponentInput] = {}

    pay = master.pay_by_employee.get(employee.id)
    if pay is not None:
        basic_comp = catalog.get(_BASIC_CODE)
        classification = (
            to_domain_classification(basic_comp.classification)
            if basic_comp is not None
            else "earning"
        )
        basic_amount = Decimal(pay["basic_pay"])
        if roster_row is not None:
            basic_amount = apply_rounding(
                ROUND_HALF_UP_PAISE,
                basic_amount * roster_row.payable_days / Decimal(period_days),
            )
        _put_component(
            by_code,
            ComponentInput(
                component_code=_BASIC_CODE,
                classification=classification,
                calc_kind="fixed_recurring_amount",
                amount=Money.from_decimal(basic_amount),
                rounding_rule=ROUND_NONE,
                source_version_ids=(str(pay["id"]),),
            ),
        )

    for instruction in master.instructions_by_employee.get(employee.id, []):
        ri_version = master.ri_version_by_instruction.get(instruction.id)
        if ri_version is None:
            continue
        component = master.component_by_id.get(instruction.component_id)
        if component is None:
            raise ValidationError(
                f"Recurring instruction {instruction.id} references a missing pay component."
            )
        rate_row = master.rate_version_by_component.get(component.id)
        if rate_row is None:
            raise ValidationError(
                f"No active component rate version for {component.code!r} on {on_date.isoformat()}."
            )
        amount = money_or_none(ri_version["amount"])
        rate = rate_or_none(ri_version["rate"])
        if amount is None:
            amount = money_or_none(rate_row["amount"])
        if rate is None:
            rate = rate_or_none(rate_row["rate"])
        source_ids = (str(ri_version["id"]), str(rate_row["id"]))
        _put_component(
            by_code,
            ComponentInput(
                component_code=component.code,
                classification=to_domain_classification(component.classification),
                calc_kind=rate_row["calc_kind"],
                amount=amount,
                rate=rate,
                basis=basis_tuple(rate_row["basis"]),
                rounding_rule=rate_row["rounding_rule"] or ROUND_NONE,
                source_version_ids=source_ids,
                reason=ri_version.get("reason"),
            ),
        )

    for advance in master.advances_by_employee.get(employee.id, []):
        inst = master.installment_by_advance.get(advance.id)
        if inst is None:
            continue
        code = _ADVANCE_COMPONENT_CODES.get(advance.advance_type)
        if code is None:
            raise ValidationError(f"Unsupported advance_type {advance.advance_type!r}.")
        catalog_row = catalog.get(code)
        if catalog_row is None:
            raise ValidationError(
                f"Pay component {code!r} required for advance_type {advance.advance_type!r} "
                "is missing from the catalog."
            )
        _put_component(
            by_code,
            ComponentInput(
                component_code=code,
                classification=to_domain_classification(catalog_row.classification),
                calc_kind="loan_installment_recovery",
                amount=Money.from_decimal(Decimal(inst["installment_amount"])),
                rounding_rule=ROUND_NONE,
                source_version_ids=(str(inst["id"]),),
            ),
        )

    for assignment in master.assignments_by_employee.get(employee.id, []):
        charge = master.charge_by_assignment.get(assignment.id)
        if charge is None:
            continue
        license_comp = catalog.get(_ACCOMMODATION_LICENSE_FEE_CODE)
        license_classification = (
            to_domain_classification(license_comp.classification)
            if license_comp is not None
            else "external_recovery"
        )
        _put_component(
            by_code,
            ComponentInput(
                component_code=_ACCOMMODATION_LICENSE_FEE_CODE,
                classification=license_classification,
                calc_kind="accommodation_charge",
                amount=Money.from_decimal(Decimal(charge["license_fee"])),
                rounding_rule=ROUND_NONE,
                source_version_ids=(str(charge["id"]),),
                accommodation_location=assignment.quarters_location,
            ),
        )
        foregone = charge.get("informational_hra_foregone")
        if foregone is not None:
            _put_component(
                by_code,
                ComponentInput(
                    component_code=_FOREGONE_HRA_CODE,
                    classification="informational",
                    calc_kind="direct_monthly_amount",
                    amount=Money.from_decimal(Decimal(foregone)),
                    rounding_rule=ROUND_NONE,
                    source_version_ids=(str(charge["id"]),),
                    informational=True,
                    excluded_from_totals=True,
                    accommodation_location=assignment.quarters_location,
                ),
            )

    if roster_row is not None:
        roster_source = (str(roster_row.id),)

        def apply_percent(code: str, percent: Decimal | None) -> None:
            if percent is None:
                return
            existing = by_code.get(code)
            catalog_row = catalog.get(code)
            _put_component(
                by_code,
                ComponentInput(
                    component_code=code,
                    classification=(
                        existing.classification
                        if existing is not None
                        else to_domain_classification(catalog_row.classification)
                        if catalog_row is not None
                        else "earning"
                    ),
                    calc_kind="percentage_of_component_bases",
                    rate=Rate.from_percent(format(percent, "f")),
                    basis=("BASIC",),
                    rounding_rule=ROUND_HALF_UP_PAISE,
                    source_version_ids=tuple(
                        dict.fromkeys(
                            [*(existing.source_version_ids if existing else ()), *roster_source]
                        )
                    ),
                    reason="Payroll run grid override",
                ),
                replace=existing is not None,
            )

        apply_percent("DA", roster_row.da_percent)
        apply_percent("HRA", roster_row.hra_percent)

        if roster_row.da_difference is not None:
            code = "DA_DIFFERENCE"
            catalog_row = catalog.get(code)
            _put_component(
                by_code,
                ComponentInput(
                    component_code=code,
                    classification=(
                        to_domain_classification(catalog_row.classification)
                        if catalog_row is not None
                        else "gross_adjustment"
                    ),
                    calc_kind="one_time_adjustment",
                    amount=Money.from_decimal(roster_row.da_difference),
                    source_version_ids=roster_source,
                    reason="DA difference entered in payroll run grid",
                ),
                replace=code in by_code,
            )

        if roster_row.transport_amount is not None:
            code = "TRANSPORT"
            existing = by_code.get(code)
            catalog_row = catalog.get(code)
            _put_component(
                by_code,
                ComponentInput(
                    component_code=code,
                    classification=(
                        existing.classification
                        if existing is not None
                        else to_domain_classification(catalog_row.classification)
                        if catalog_row is not None
                        else "earning"
                    ),
                    calc_kind="direct_monthly_amount",
                    amount=Money.from_decimal(roster_row.transport_amount),
                    source_version_ids=tuple(
                        dict.fromkeys(
                            [*(existing.source_version_ids if existing else ()), *roster_source]
                        )
                    ),
                    reason="Transport amount entered in payroll run grid",
                ),
                replace=existing is not None,
            )

    for row in sorted(run_inputs, key=lambda r: (r.component_code, r.input_kind, str(r.id))):
        catalog_row = catalog.get(row.component_code)
        classification = (
            to_domain_classification(catalog_row.classification)
            if catalog_row is not None
            else "gross_adjustment"
        )
        source_ids_extra = (str(row.id),)
        if row.input_kind == "override":
            existing = by_code.get(row.component_code)
            if existing is not None:
                merged_sources = tuple(
                    dict.fromkeys([*existing.source_version_ids, *source_ids_extra])
                )
                _put_component(
                    by_code,
                    ComponentInput(
                        component_code=existing.component_code,
                        classification=existing.classification,
                        calc_kind=existing.calc_kind,
                        amount=money_or_none(row.amount)
                        if row.amount is not None
                        else existing.amount,
                        rate=rate_or_none(row.rate) if row.rate is not None else existing.rate,
                        basis=existing.basis,
                        rounding_rule=existing.rounding_rule,
                        source_version_ids=merged_sources,
                        informational=existing.informational,
                        excluded_from_totals=existing.excluded_from_totals,
                        gpf_jurisdiction=existing.gpf_jurisdiction,
                        accommodation_location=existing.accommodation_location,
                        employer_transfer=existing.employer_transfer,
                        transfer_of=existing.transfer_of,
                        service_period=existing.service_period,
                        reason=row.reason,
                    ),
                    replace=True,
                )
            else:
                _put_component(
                    by_code,
                    ComponentInput(
                        component_code=row.component_code,
                        classification=classification,
                        calc_kind="direct_monthly_amount",
                        amount=money_or_none(row.amount),
                        rate=rate_or_none(row.rate),
                        rounding_rule=ROUND_NONE,
                        source_version_ids=source_ids_extra,
                        reason=row.reason,
                    ),
                )
        elif row.input_kind == "exception":
            _put_component(
                by_code,
                ComponentInput(
                    component_code=row.component_code,
                    classification=classification,
                    calc_kind="direct_monthly_amount",
                    amount=money_or_none(row.amount),
                    rate=rate_or_none(row.rate),
                    rounding_rule=ROUND_NONE,
                    source_version_ids=source_ids_extra,
                    reason=row.reason,
                ),
            )
        elif row.input_kind == "one_time":
            _put_component(
                by_code,
                ComponentInput(
                    component_code=row.component_code,
                    classification=classification,
                    calc_kind="one_time_adjustment",
                    amount=money_or_none(row.amount),
                    rate=rate_or_none(row.rate),
                    rounding_rule=ROUND_NONE,
                    source_version_ids=source_ids_extra,
                    reason=row.reason,
                ),
            )
        else:
            raise ValidationError(f"Unsupported run input_kind {row.input_kind!r}.")

    by_code = _stamp_employer_transfer_metadata(by_code, catalog)

    # Stable audit order: BASIC first, then remaining codes sorted.
    ordered_codes = []
    if _BASIC_CODE in by_code:
        ordered_codes.append(_BASIC_CODE)
    ordered_codes.extend(sorted(code for code in by_code if code != _BASIC_CODE))
    components = tuple(by_code[code] for code in ordered_codes)
    return EmployeeCalcInput(
        employee_ref=str(employee.id),
        components=components,
        retirement_regime=profile["retirement_regime"],
        gpf_jurisdiction=profile.get("gpf_jurisdiction"),
    )


def _stamp_employer_transfer_metadata(
    by_code: dict[str, ComponentInput],
    catalog: Mapping[str, Any],
) -> dict[str, ComponentInput]:
    """Return component inputs carrying the catalog's transfer semantics."""
    stamped = dict(by_code)
    for code, comp in by_code.items():
        catalog_row = catalog.get(code)
        if catalog_row is None or not catalog_row.employer_transfer:
            continue
        stamped[code] = dataclasses.replace(
            comp,
            employer_transfer=True,
            transfer_of=catalog_row.transfer_of,
        )
    return stamped


async def resolve_run_calc_input(
    db: AsyncSession,
    *,
    organization_id: UUID,
    period: PayrollPeriod,
    run_id: UUID,
) -> tuple[RunCalcInput, dict[str, Employee]]:
    on_date = month_end(period.period_year, period.period_month)
    catalog = await load_component_catalog(db, organization_id=organization_id)

    emp_stmt = (
        sa.select(Employee)
        .where(Employee.organization_id == organization_id)
        .order_by(Employee.employee_number)
    )
    org_employees = list((await db.execute(emp_stmt)).scalars().all())

    inputs_stmt = (
        sa.select(PayrollRunInput)
        .where(PayrollRunInput.organization_id == organization_id)
        .where(PayrollRunInput.run_id == run_id)
    )
    all_inputs = list((await db.execute(inputs_stmt)).scalars().all())
    inputs_by_employee: dict[UUID, list[PayrollRunInput]] = {}
    for row in all_inputs:
        inputs_by_employee.setdefault(row.employee_id, []).append(row)

    roster_rows = list(
        (
            await db.execute(
                sa.select(PayrollRunEmployee)
                .join(PayrollRun, PayrollRun.id == PayrollRunEmployee.run_id)
                .where(PayrollRunEmployee.organization_id == organization_id)
                .where(PayrollRunEmployee.run_id == run_id)
            )
        )
        .scalars()
        .all()
    )
    roster_by_employee = {row.employee_id: row for row in roster_rows}
    run = await db.get(PayrollRun, run_id)
    roster_initialized = bool(run and run.roster_initialized)

    selected = [
        employee
        for employee in org_employees
        if not (roster_initialized and employee.id not in roster_by_employee)
    ]
    profiles = await versioning.get_active_versions_map(
        db,
        employee_profile_versions,
        header_ids=[employee.id for employee in selected],
        organization_id=organization_id,
        on_date=on_date,
    )
    selected = [employee for employee in selected if employee.id in profiles]
    master = await _load_master_data(
        db,
        organization_id=organization_id,
        employee_ids=[employee.id for employee in selected],
        on_date=on_date,
        catalog=catalog,
    )

    period_days = calendar.monthrange(period.period_year, period.period_month)[1]
    employees: list[EmployeeCalcInput] = []
    employee_by_ref: dict[str, Employee] = {}
    for employee in selected:
        emp_input = _resolve_employee_components(
            employee=employee,
            profile=profiles[employee.id],
            on_date=on_date,
            catalog=catalog,
            master=master,
            roster_row=roster_by_employee.get(employee.id),
            period_days=period_days,
            run_inputs=inputs_by_employee.get(employee.id, []),
        )
        employees.append(emp_input)
        employee_by_ref[str(employee.id)] = employee

    run_input = RunCalcInput(
        period=period_label(period.period_year, period.period_month),
        org_ref=str(organization_id),
        employees=tuple(employees),
    )
    return run_input, employee_by_ref


async def assert_roster_calculable(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
    period: PayrollPeriod,
) -> None:
    """Fail fast unless every saved roster member is calculable at month-end.

    Enforces: non-empty roster, and resolved-profile count == saved roster
    count (no silent partial calculations).
    """
    roster_ids = list(
        (
            await db.execute(
                sa.select(PayrollRunEmployee.employee_id)
                .where(PayrollRunEmployee.organization_id == organization_id)
                .where(PayrollRunEmployee.run_id == run_id)
            )
        )
        .scalars()
        .all()
    )
    if not roster_ids:
        raise ConflictError(
            "The saved roster is empty. Add at least one employee before calculating."
        )
    period_days = calendar.monthrange(period.period_year, period.period_month)[1]
    on_date = date(period.period_year, period.period_month, period_days)
    profiles = await versioning.get_active_versions_map(
        db,
        employee_profile_versions,
        header_ids=roster_ids,
        organization_id=organization_id,
        on_date=on_date,
    )
    missing = [eid for eid in roster_ids if eid not in profiles]
    if missing:
        numbers = (
            (
                await db.execute(
                    sa.select(Employee.employee_number)
                    .where(Employee.id.in_(missing))
                    .order_by(Employee.employee_number)
                )
            )
            .scalars()
            .all()
        )
        raise ConflictError(
            "These roster employees have no active profile on "
            f"{on_date.isoformat()} and cannot be calculated: "
            f"{', '.join(numbers)}. Remove them from the roster and save again."
        )
