"""Payroll run calculate command: resolve master data → engine → immutable version.

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
import uuid
from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.payroll.engine import calculate_run
from app.domain.payroll.inputs import ComponentInput, EmployeeCalcInput, RunCalcInput
from app.domain.payroll.money import Money
from app.domain.payroll.rates import Rate
from app.domain.payroll.results import CalculationTrace, RunResult
from app.domain.payroll.rounding import ROUND_HALF_UP_PAISE, ROUND_NONE, apply as apply_rounding
from app.exceptions import ConflictError, NotFoundError, ValidationError
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
    payroll_employee_results,
    payroll_result_lines,
    payroll_run_versions,
)
from app.models.recurring_instructions import (
    RecurringInstruction,
    recurring_instruction_versions,
)
from app.services import versioning

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

_ALLOWED_CALCULATE_STATUSES = frozenset({"draft", "calculated"})


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _to_domain_classification(db_classification: str) -> str:
    if db_classification == "ag_deduction":
        return "AG_deduction"
    return db_classification


def _to_db_classification(domain_classification: str) -> str:
    if domain_classification == "AG_deduction":
        return "ag_deduction"
    # Result-line CHECK omits ``informational``; persist column as earning and
    # keep the true classification inside the ADR-0007 trace JSON.
    if domain_classification == "informational":
        return "earning"
    return domain_classification


def _money_or_none(value: Decimal | None) -> Money | None:
    if value is None:
        return None
    return Money.from_decimal(Decimal(value))


def _rate_or_none(value: Decimal | None) -> Rate | None:
    if value is None:
        return None
    return Rate(amount=Decimal(value))


def _basis_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()


def _period_label(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _serialize_component_input(comp: ComponentInput) -> dict[str, Any]:
    return {
        "component_code": comp.component_code,
        "classification": comp.classification,
        "calc_kind": comp.calc_kind,
        "amount": None if comp.amount is None else comp.amount.to_canonical_str(),
        "rate": None if comp.rate is None else comp.rate.to_canonical_str(),
        "basis": list(comp.basis),
        "rounding_rule": comp.rounding_rule,
        "source_version_ids": list(comp.source_version_ids),
        "informational": comp.informational,
        "excluded_from_totals": comp.excluded_from_totals,
        "gpf_jurisdiction": comp.gpf_jurisdiction,
        "accommodation_location": comp.accommodation_location,
        "employer_transfer": comp.employer_transfer,
        "transfer_of": comp.transfer_of,
        "service_period": comp.service_period,
        "reason": comp.reason,
    }


def _serialize_run_calc_input(run_input: RunCalcInput) -> dict[str, Any]:
    employees: list[dict[str, Any]] = []
    for emp in sorted(run_input.employees, key=lambda e: e.employee_ref):
        employees.append(
            {
                "employee_ref": emp.employee_ref,
                "retirement_regime": emp.retirement_regime,
                "gpf_jurisdiction": emp.gpf_jurisdiction,
                "components": [_serialize_component_input(c) for c in emp.components],
            }
        )
    return {
        "period": run_input.period,
        "org_ref": run_input.org_ref,
        "employees": employees,
    }


def _totals_payload(result: RunResult) -> dict[str, str]:
    return {
        "earnings_total": result.earnings_total.to_canonical_str(),
        "employer_contribution_total": result.employer_contribution_total.to_canonical_str(),
        "gross_adjustment_total": result.gross_adjustment_total.to_canonical_str(),
        "gross_total": result.gross_total.to_canonical_str(),
        "ag_deduction_total": result.ag_deduction_total.to_canonical_str(),
        "treasury_deduction_total": result.treasury_deduction_total.to_canonical_str(),
        "external_recovery_total": result.external_recovery_total.to_canonical_str(),
        "deductions_total": result.deductions_total.to_canonical_str(),
        "net_payable": result.net_payable.to_canonical_str(),
        # Employee disbursement is reconciled separately from treasury-face
        # net payable (docs/payroll-domain.md "Resolved").
        "offbill_employer_remittance": result.offbill_employer_remittance.to_canonical_str(),
        "disbursement": result.disbursement.to_canonical_str(),
    }


def _trace_payload(trace: CalculationTrace) -> dict[str, Any]:
    return {
        "component": trace.component,
        "classification": trace.classification,
        "basis": list(trace.basis),
        "basis_total": (
            None if trace.basis_total is None else trace.basis_total.to_canonical_str()
        ),
        "rate": None if trace.rate is None else trace.rate.to_canonical_str(),
        "unrounded_value": trace.unrounded_value,
        "rounding_rule": trace.rounding_rule,
        "rounded_value": trace.rounded_value.to_canonical_str(),
        "source_version_ids": list(trace.source_version_ids),
        "calculator_kind": trace.calculator_kind,
        "engine_version": trace.engine_version,
        "employer_transfer": trace.employer_transfer,
        "transfer_of": trace.transfer_of,
    }


async def _load_component_catalog(
    db: AsyncSession,
    *,
    organization_id: UUID,
) -> dict[str, PayComponent]:
    stmt = sa.select(PayComponent).where(PayComponent.organization_id == organization_id)
    rows = (await db.execute(stmt)).scalars().all()
    return {row.code: row for row in rows}


async def _active_rate_version(
    db: AsyncSession,
    *,
    organization_id: UUID,
    component_id: UUID,
    on_date: date,
) -> Any | None:
    return await versioning.get_active_version(
        db,
        component_rate_versions,
        header_id=component_id,
        organization_id=organization_id,
        on_date=on_date,
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


async def _resolve_employee_components(
    db: AsyncSession,
    *,
    organization_id: UUID,
    employee: Employee,
    profile: Any,
    on_date: date,
    catalog: dict[str, PayComponent],
    roster_row: PayrollRunEmployee | None,
    period_days: int,
    run_inputs: list[PayrollRunInput],
) -> EmployeeCalcInput:
    by_code: dict[str, ComponentInput] = {}

    pay = await versioning.get_active_version(
        db,
        employee_pay_versions,
        header_id=employee.id,
        organization_id=organization_id,
        on_date=on_date,
    )
    if pay is not None:
        basic_comp = catalog.get(_BASIC_CODE)
        classification = (
            _to_domain_classification(basic_comp.classification)
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

    ri_stmt = (
        sa.select(RecurringInstruction)
        .where(RecurringInstruction.organization_id == organization_id)
        .where(RecurringInstruction.employee_id == employee.id)
        .order_by(RecurringInstruction.created_at)
    )
    instructions = (await db.execute(ri_stmt)).scalars().all()
    for instruction in instructions:
        ri_version = await versioning.get_active_version(
            db,
            recurring_instruction_versions,
            header_id=instruction.id,
            organization_id=organization_id,
            on_date=on_date,
        )
        if ri_version is None:
            continue
        component = await db.get(PayComponent, instruction.component_id)
        if component is None or component.organization_id != organization_id:
            raise ValidationError(
                f"Recurring instruction {instruction.id} references a missing pay component."
            )
        rate_row = await _active_rate_version(
            db,
            organization_id=organization_id,
            component_id=component.id,
            on_date=on_date,
        )
        if rate_row is None:
            raise ValidationError(
                f"No active component rate version for {component.code!r} on {on_date.isoformat()}."
            )
        amount = _money_or_none(ri_version["amount"])
        rate = _rate_or_none(ri_version["rate"])
        if amount is None:
            amount = _money_or_none(rate_row["amount"])
        if rate is None:
            rate = _rate_or_none(rate_row["rate"])
        source_ids = (str(ri_version["id"]), str(rate_row["id"]))
        _put_component(
            by_code,
            ComponentInput(
                component_code=component.code,
                classification=_to_domain_classification(component.classification),
                calc_kind=rate_row["calc_kind"],
                amount=amount,
                rate=rate,
                basis=_basis_tuple(rate_row["basis"]),
                rounding_rule=rate_row["rounding_rule"] or ROUND_NONE,
                source_version_ids=source_ids,
                reason=ri_version.get("reason"),
            ),
        )

    adv_stmt = (
        sa.select(AdvanceAccount)
        .where(AdvanceAccount.organization_id == organization_id)
        .where(AdvanceAccount.employee_id == employee.id)
        .order_by(AdvanceAccount.created_at)
    )
    for advance in (await db.execute(adv_stmt)).scalars().all():
        inst = await versioning.get_active_version(
            db,
            advance_installment_versions,
            header_id=advance.id,
            organization_id=organization_id,
            on_date=on_date,
        )
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
                classification=_to_domain_classification(catalog_row.classification),
                calc_kind="loan_installment_recovery",
                amount=Money.from_decimal(Decimal(inst["installment_amount"])),
                rounding_rule=ROUND_NONE,
                source_version_ids=(str(inst["id"]),),
            ),
        )

    acc_stmt = (
        sa.select(AccommodationAssignment)
        .where(AccommodationAssignment.organization_id == organization_id)
        .where(AccommodationAssignment.employee_id == employee.id)
        .order_by(AccommodationAssignment.created_at)
    )
    for assignment in (await db.execute(acc_stmt)).scalars().all():
        charge = await versioning.get_active_version(
            db,
            accommodation_charge_versions,
            header_id=assignment.id,
            organization_id=organization_id,
            on_date=on_date,
        )
        if charge is None:
            continue
        license_comp = catalog.get(_ACCOMMODATION_LICENSE_FEE_CODE)
        license_classification = (
            _to_domain_classification(license_comp.classification)
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
                        else _to_domain_classification(catalog_row.classification)
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
                        _to_domain_classification(catalog_row.classification)
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
                        else _to_domain_classification(catalog_row.classification)
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
            _to_domain_classification(catalog_row.classification)
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
                        amount=_money_or_none(row.amount)
                        if row.amount is not None
                        else existing.amount,
                        rate=_rate_or_none(row.rate) if row.rate is not None else existing.rate,
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
                        amount=_money_or_none(row.amount),
                        rate=_rate_or_none(row.rate),
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
                    amount=_money_or_none(row.amount),
                    rate=_rate_or_none(row.rate),
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
                    amount=_money_or_none(row.amount),
                    rate=_rate_or_none(row.rate),
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


async def _resolve_run_calc_input(
    db: AsyncSession,
    *,
    organization_id: UUID,
    period: PayrollPeriod,
    run_id: UUID,
) -> tuple[RunCalcInput, dict[str, Employee]]:
    on_date = _month_end(period.period_year, period.period_month)
    catalog = await _load_component_catalog(db, organization_id=organization_id)

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

    employees: list[EmployeeCalcInput] = []
    employee_by_ref: dict[str, Employee] = {}
    for employee in org_employees:
        roster_row = roster_by_employee.get(employee.id)
        if roster_initialized and roster_row is None:
            continue
        profile = await versioning.get_active_version(
            db,
            employee_profile_versions,
            header_id=employee.id,
            organization_id=organization_id,
            on_date=on_date,
        )
        if profile is None:
            continue
        emp_input = await _resolve_employee_components(
            db,
            organization_id=organization_id,
            employee=employee,
            profile=profile,
            on_date=on_date,
            catalog=catalog,
            roster_row=roster_row,
            period_days=calendar.monthrange(period.period_year, period.period_month)[1],
            run_inputs=inputs_by_employee.get(employee.id, []),
        )
        employees.append(emp_input)
        employee_by_ref[str(employee.id)] = employee

    run_input = RunCalcInput(
        period=_period_label(period.period_year, period.period_month),
        org_ref=str(organization_id),
        employees=tuple(employees),
    )
    return run_input, employee_by_ref


async def calculate_run_command(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
    user_id: UUID,
) -> dict[str, Any]:
    """Resolve inputs, run the engine, and append an immutable run version."""
    stmt = (
        sa.select(PayrollRun)
        .where(PayrollRun.id == run_id)
        .where(PayrollRun.organization_id == organization_id)
        .with_for_update()
    )
    run = (await db.execute(stmt)).scalar_one_or_none()
    if run is None:
        raise NotFoundError("Payroll run not found.")
    if run.status not in _ALLOWED_CALCULATE_STATUSES:
        raise ConflictError(
            f"Payroll run cannot be calculated from status {run.status!r}; "
            "allowed statuses are draft and calculated."
        )
    # Draft runs require an explicit saved roster. Legacy non-draft runs may still
    # recalculate with roster_initialized=false (pre-roster migration), which
    # falls back to all organization employees in _resolve_run_calc_input.
    if run.status == "draft" and not run.roster_initialized:
        raise ConflictError("Payroll run roster must be saved before calculation.")

    period = await db.get(PayrollPeriod, run.period_id)
    if period is None or period.organization_id != organization_id:
        raise NotFoundError("Payroll period not found.")

    run.status = "calculating"
    await db.flush()

    run_input, employee_by_ref = await _resolve_run_calc_input(
        db,
        organization_id=organization_id,
        period=period,
        run_id=run.id,
    )
    result = calculate_run(run_input)

    max_version_stmt = sa.select(
        sa.func.coalesce(sa.func.max(payroll_run_versions.c.version_number), 0)
    ).where(
        payroll_run_versions.c.organization_id == organization_id,
        payroll_run_versions.c.run_id == run.id,
    )
    next_version = int((await db.execute(max_version_stmt)).scalar_one()) + 1
    version_id = uuid.uuid4()
    calculated_at = datetime.now(timezone.utc)
    inputs_snapshot = _serialize_run_calc_input(run_input)
    totals = _totals_payload(result)

    await db.execute(
        sa.insert(payroll_run_versions).values(
            id=version_id,
            organization_id=organization_id,
            run_id=run.id,
            version_number=next_version,
            engine_version=result.engine_version,
            content_hash=result.content_hash,
            calculated_at=calculated_at,
            calculated_by=user_id,
            inputs_snapshot=inputs_snapshot,
            totals=totals,
        )
    )

    for emp_result in result.employees:
        employee = employee_by_ref.get(emp_result.employee_ref)
        if employee is None:
            raise ValidationError(
                f"Engine returned unknown employee_ref {emp_result.employee_ref!r}."
            )
        employee_result_id = uuid.uuid4()
        await db.execute(
            sa.insert(payroll_employee_results).values(
                id=employee_result_id,
                organization_id=organization_id,
                run_version_id=version_id,
                employee_id=employee.id,
                employee_number=employee.employee_number,
                earnings_total=emp_result.earnings_total.amount,
                employer_contribution_total=emp_result.employer_contribution_total.amount,
                gross_total=emp_result.gross_total.amount,
                deductions_total=emp_result.deductions_total.amount,
                net_payable=emp_result.net_payable.amount,
                offbill_employer_remittance=emp_result.offbill_employer_remittance.amount,
                disbursement=emp_result.disbursement.amount,
            )
        )
        line_rows: list[dict[str, Any]] = []
        for sequence, trace in enumerate(emp_result.lines, start=1):
            line_rows.append(
                {
                    "id": uuid.uuid4(),
                    "organization_id": organization_id,
                    "employee_result_id": employee_result_id,
                    "component_code": trace.component,
                    "classification": _to_db_classification(trace.classification),
                    "calc_kind": trace.calculator_kind,
                    "amount": trace.rounded_value.amount,
                    "sequence": sequence,
                    "trace": _trace_payload(trace),
                }
            )
        if line_rows:
            await db.execute(sa.insert(payroll_result_lines).values(line_rows))

    run.current_version_id = version_id
    run.status = "calculated"
    run.lock_version = run.lock_version + 1
    run.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.commit()

    return {
        "run_id": run.id,
        "version_id": version_id,
        "version_number": next_version,
        "content_hash": result.content_hash,
        "engine_version": result.engine_version,
        "totals": totals,
    }
