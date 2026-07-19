"""Gate F golden test: reproduce the Proven June 2026 invariants exactly.

Loads the read-only sanitized June 2026 fixture (``fixtures/sanitized/
june-2026/``) directly from disk, builds ``RunCalcInput`` using
``calc_kind="direct_monthly_amount"`` for every pay line (the fixture already
supplies fully resolved whole-rupee amounts — no percentage/contribution
calculators are needed for this golden path; those get dedicated unit
coverage in ``test_calculators.py`` / ``test_engine.py``), runs
``calculate_run`` once, and asserts every aggregate in ``expected_totals.json``
matches exactly, plus per-employee gross-to-net identity for every employee
and content-hash determinism.

Money amounts in the fixture are whole-rupee integer strings (e.g. ``"82000"``)
with no paise; ``Money.from_str`` accepts fewer than 2 decimal places and
treats the value as unchanged (padded only on serialize), so
``Money.from_str("82000")`` and ``Money.from_str("82000.00")`` are equal.

Jurisdiction / location / scheme subtotals (GPF Mumbai vs Nagpur, NPS vs EPF,
accommodation Mumbai vs Worli, etc.) are not carried on ``CalculationTrace``
(that dataclass only has the ADR-0007 audit fields, not fixture-specific
metadata). This test correlates each ``CalculationTrace`` in a computed
``EmployeeResult.lines`` with the original pay.json line at the same index
(the engine documents that lines are emitted in the same order as the input
``ComponentInput`` tuple, which this test builds directly from pay.json's
line order) to recover that metadata, while still reading the *computed*
``rounded_value`` off the trace so the assertions genuinely exercise engine
output, not just a re-derivation of the fixture.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.domain.payroll.engine import calculate_run
from app.domain.payroll.inputs import ComponentInput, EmployeeCalcInput, RunCalcInput
from app.domain.payroll.money import Money
from app.domain.payroll.results import RunResult

_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "sanitized" / "june-2026"


def _load_json(name: str) -> dict[str, Any]:
    with (_FIXTURE_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def _pay_doc() -> dict[str, Any]:
    return _load_json("pay.json")


def _expected_aggregates() -> dict[str, str]:
    return _load_json("expected_totals.json")["aggregates"]


def _build_run_input(pay_doc: dict[str, Any]) -> RunCalcInput:
    employees: list[EmployeeCalcInput] = []
    for emp in pay_doc["employees"]:
        components: list[ComponentInput] = []
        for line in emp["lines"]:
            components.append(
                ComponentInput(
                    component_code=line["component_code"],
                    classification=line["classification"],
                    calc_kind="direct_monthly_amount",
                    amount=Money.from_str(line["amount"]),
                    informational=bool(line.get("informational", False)),
                    excluded_from_totals=bool(line.get("excluded_from_totals", False)),
                    gpf_jurisdiction=line.get("gpf_jurisdiction"),
                    accommodation_location=line.get("accommodation_location"),
                    employer_transfer=bool(line.get("employer_transfer", False)),
                    transfer_of=line.get("transfer_of"),
                )
            )
        employees.append(
            EmployeeCalcInput(
                employee_ref=emp["employee_id"],
                components=tuple(components),
            )
        )
    return RunCalcInput(
        period=pay_doc["period"],
        org_ref="june-2026-fixture",
        employees=tuple(employees),
    )


@pytest.fixture(scope="module")
def pay_doc() -> dict[str, Any]:
    return _pay_doc()


@pytest.fixture(scope="module")
def expected_aggregates() -> dict[str, str]:
    return _expected_aggregates()


@pytest.fixture(scope="module")
def run_input(pay_doc: dict[str, Any]) -> RunCalcInput:
    return _build_run_input(pay_doc)


@pytest.fixture(scope="module")
def run_result(run_input: RunCalcInput) -> RunResult:
    return calculate_run(run_input)


def _money(value: str) -> Money:
    return Money.from_str(value)


def test_fixture_has_32_employees(pay_doc: dict[str, Any]) -> None:
    assert len(pay_doc["employees"]) == 32


def test_top_level_aggregates_match_expected_totals(
    run_result: RunResult, expected_aggregates: dict[str, str]
) -> None:
    assert run_result.earnings_total == _money(expected_aggregates["salary_earnings"])
    assert run_result.employer_contribution_total == _money(expected_aggregates["employer_share"])
    assert run_result.gross_total == _money(expected_aggregates["gross_bill"])
    assert run_result.deductions_total == _money(expected_aggregates["total_deductions"])
    assert run_result.net_payable == _money(expected_aggregates["net_payable"])

    # Sanity: these are the headline Proven June 2026 invariants verbatim.
    assert run_result.earnings_total == _money("5073200")
    assert run_result.employer_contribution_total == _money("29785")
    assert run_result.gross_total == _money("5102985")
    assert run_result.deductions_total == _money("1264890")
    assert run_result.net_payable == _money("3838095")


def _line_metadata_by_employee(
    pay_doc: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    return {emp["employee_id"]: emp["lines"] for emp in pay_doc["employees"]}


def _iter_trace_with_metadata(
    run_result: RunResult, pay_doc: dict[str, Any]
) -> list[tuple[str, Any, dict[str, Any]]]:
    """Yield ``(employee_ref, CalculationTrace, source_line_dict)`` triples.

    Correlates each computed trace line with its originating pay.json line by
    positional index within the employee (engine preserves input line order).
    """
    metadata_by_employee = _line_metadata_by_employee(pay_doc)
    out: list[tuple[str, Any, dict[str, Any]]] = []
    for emp_result in run_result.employees:
        source_lines = metadata_by_employee[emp_result.employee_ref]
        assert len(source_lines) == len(emp_result.lines)
        for trace, source_line in zip(emp_result.lines, source_lines, strict=True):
            assert trace.component == source_line["component_code"]
            out.append((emp_result.employee_ref, trace, source_line))
    return out


def test_gpf_jurisdiction_subtotals(
    run_result: RunResult, pay_doc: dict[str, Any], expected_aggregates: dict[str, str]
) -> None:
    mumbai = Money.zero()
    nagpur = Money.zero()
    for _, trace, source_line in _iter_trace_with_metadata(run_result, pay_doc):
        if trace.component != "GPF_SUBSCRIPTION":
            continue
        jurisdiction = source_line.get("gpf_jurisdiction")
        if jurisdiction == "Mumbai":
            mumbai = mumbai + trace.rounded_value
        elif jurisdiction == "Nagpur":
            nagpur = nagpur + trace.rounded_value
        else:
            pytest.fail(f"GPF_SUBSCRIPTION line missing Mumbai/Nagpur tag: {source_line}")
    assert mumbai == _money(expected_aggregates["gpf_mumbai"]) == _money("165000")
    assert nagpur == _money(expected_aggregates["gpf_nagpur"]) == _money("115000")
    assert (mumbai + nagpur) == _money(expected_aggregates["gpf_total"]) == _money("280000")


def test_nps_and_epf_scheme_subtotals(
    run_result: RunResult, pay_doc: dict[str, Any], expected_aggregates: dict[str, str]
) -> None:
    nps_employee = Money.zero()
    nps_employer_transfer = Money.zero()
    nps_employer_contribution_in_gross_bill = Money.zero()
    epf_employee = Money.zero()
    epf_employer_contribution = Money.zero()
    epf_employer_transfer = Money.zero()

    for _, trace, _source_line in _iter_trace_with_metadata(run_result, pay_doc):
        code = trace.component
        if code == "NPS_EMPLOYEE":
            nps_employee = nps_employee + trace.rounded_value
        elif code == "NPS_EMPLOYER_TRANSFER":
            nps_employer_transfer = nps_employer_transfer + trace.rounded_value
            if trace.classification == "employer_contribution":
                nps_employer_contribution_in_gross_bill = (
                    nps_employer_contribution_in_gross_bill + trace.rounded_value
                )
        elif code == "EPF_EMPLOYEE":
            epf_employee = epf_employee + trace.rounded_value
        elif code == "EPF_EMPLOYER":
            epf_employer_contribution = epf_employer_contribution + trace.rounded_value
        elif code == "EPF_EMPLOYER_TRANSFER":
            epf_employer_transfer = epf_employer_transfer + trace.rounded_value

    assert nps_employee == _money(expected_aggregates["nps_employee"]) == _money("109245")
    assert nps_employer_transfer == _money(expected_aggregates["nps_employer"]) == _money("152943")
    assert epf_employee == _money(expected_aggregates["epf_employee"]) == _money("29785")
    assert (
        epf_employer_contribution == _money(expected_aggregates["epf_employer"]) == _money("29785")
    )
    assert epf_employer_transfer == _money("29785")

    # Critical asymmetry (must NOT be "fixed"): NPS employer never enters
    # gross bill as an employer_contribution addition; only EPF employer does.
    assert nps_employer_contribution_in_gross_bill == Money.zero()
    assert epf_employer_contribution == epf_employer_transfer

    employer_transfer = nps_employer_transfer + epf_employer_transfer
    employee_contribution = nps_employee + epf_employee
    assert employer_transfer == _money(expected_aggregates["employer_transfer"]) == _money("182728")
    assert (
        employee_contribution
        == _money(expected_aggregates["employee_contribution"])
        == _money("139030")
    )


def test_treasury_and_recovery_subtotals(
    run_result: RunResult, pay_doc: dict[str, Any], expected_aggregates: dict[str, str]
) -> None:
    income_tax = Money.zero()
    gis = Money.zero()
    hba = Money.zero()
    professional_tax = Money.zero()
    pt_line_count = 0
    accommodation_mumbai = Money.zero()
    accommodation_worli = Money.zero()

    for _, trace, source_line in _iter_trace_with_metadata(run_result, pay_doc):
        code = trace.component
        if code == "INCOME_TAX":
            income_tax = income_tax + trace.rounded_value
        elif code == "GIS":
            gis = gis + trace.rounded_value
        elif code == "HBA_INSTALLMENT":
            hba = hba + trace.rounded_value
        elif code == "PROFESSIONAL_TAX":
            professional_tax = professional_tax + trace.rounded_value
            pt_line_count += 1
        elif code == "ACCOMMODATION_LICENSE_FEE":
            location = source_line.get("accommodation_location")
            if location == "Mumbai":
                accommodation_mumbai = accommodation_mumbai + trace.rounded_value
            elif location == "Worli":
                accommodation_worli = accommodation_worli + trace.rounded_value
            else:
                pytest.fail(f"accommodation line missing Mumbai/Worli tag: {source_line}")

    assert income_tax == _money(expected_aggregates["income_tax"]) == _money("550700")
    assert gis == _money(expected_aggregates["gis"]) == _money("22440")
    assert hba == _money(expected_aggregates["hba"]) == _money("72723")
    assert professional_tax == _money(expected_aggregates["professional_tax"]) == _money("5600")
    assert pt_line_count == 28
    assert (
        accommodation_mumbai
        == _money(expected_aggregates["accommodation_mumbai"])
        == _money("10419")
    )
    assert (
        accommodation_worli == _money(expected_aggregates["accommodation_worli"]) == _money("1250")
    )
    accommodation_total = accommodation_mumbai + accommodation_worli
    assert (
        accommodation_total == _money(expected_aggregates["accommodation_total"]) == _money("11669")
    )


def test_foregone_hra_is_traced_but_excluded_from_all_aggregates(
    run_result: RunResult, pay_doc: dict[str, Any]
) -> None:
    foregone_traces = [
        trace
        for _, trace, _source in _iter_trace_with_metadata(run_result, pay_doc)
        if trace.component == "FOREGONE_HRA"
    ]
    assert len(foregone_traces) > 0, "expected at least one informational FOREGONE_HRA line"
    for trace in foregone_traces:
        assert trace.classification == "informational"

    # Recompute earnings from the traces of every employee, explicitly
    # excluding any line whose classification is "informational" (or which is
    # otherwise flagged excluded), and confirm it equals the engine's own
    # earnings_total — i.e. FOREGONE_HRA contributed nothing either way.
    recomputed_earnings = Money.zero()
    for emp_result in run_result.employees:
        for trace in emp_result.lines:
            if trace.classification == "earning":
                recomputed_earnings = recomputed_earnings + trace.rounded_value
    assert recomputed_earnings == run_result.earnings_total
    assert recomputed_earnings == _money("5073200")


def test_per_employee_gross_to_net_identity_holds_for_every_employee(
    run_result: RunResult,
) -> None:
    assert len(run_result.employees) == 32
    for emp_result in run_result.employees:
        assert emp_result.gross_total - emp_result.deductions_total == emp_result.net_payable
        assert (
            emp_result.earnings_total
            + emp_result.employer_contribution_total
            + emp_result.gross_adjustment_total
            == emp_result.gross_total
        )
        assert (
            emp_result.ag_deduction_total
            + emp_result.treasury_deduction_total
            + emp_result.external_recovery_total
            == emp_result.deductions_total
        )


def test_per_employee_totals_match_pay_json_declared_totals(
    run_result: RunResult, pay_doc: dict[str, Any]
) -> None:
    declared_by_id = {emp["employee_id"]: emp["totals"] for emp in pay_doc["employees"]}
    for emp_result in run_result.employees:
        declared = declared_by_id[emp_result.employee_ref]
        assert emp_result.earnings_total == _money(declared["earnings"])
        assert emp_result.employer_contribution_total == _money(declared["employer_contribution"])
        assert emp_result.gross_total == _money(declared["gross"])
        assert emp_result.deductions_total == _money(declared["deductions"])
        assert emp_result.net_payable == _money(declared["net_payable"])


def test_sum_of_employee_net_payable_equals_run_net_payable(run_result: RunResult) -> None:
    # Treasury-face net (has off-bill NPS employer subtracted). Unchanged figure.
    total = Money.zero()
    for emp_result in run_result.employees:
        total = total + emp_result.net_payable
    assert total == run_result.net_payable == _money("3838095")


def test_sum_of_payslip_disbursements_equals_run_disbursement(run_result: RunResult) -> None:
    # Payslip take-home / bank-RTGS credit = disbursement, reconciled SEPARATELY
    # from Net Payable. Disbursement = net_payable + off-bill NPS employer.
    # Department sign-off 18 Jul 2026; see docs/payroll-domain.md Resolved section.
    total = Money.zero()
    for emp_result in run_result.employees:
        total = total + emp_result.disbursement
    assert total == run_result.disbursement == _money("3991038")


def test_disbursement_identity_and_offbill_remittance(run_result: RunResult) -> None:
    # Off-bill remittance is NPS employer only (EPF employer is a true gross
    # pass-through and is excluded); disbursement exceeds Net Payable by exactly
    # that amount, and the two are intentionally not equal.
    assert run_result.offbill_employer_remittance == _money("152943")
    assert (
        run_result.disbursement == run_result.net_payable + run_result.offbill_employer_remittance
    )
    assert run_result.disbursement - run_result.net_payable == _money("152943")
    for emp_result in run_result.employees:
        assert (
            emp_result.disbursement
            == emp_result.net_payable + emp_result.offbill_employer_remittance
        )


def test_content_hash_is_deterministic_across_two_runs(run_input: RunCalcInput) -> None:
    first = calculate_run(run_input)
    second = calculate_run(run_input)
    assert isinstance(first.content_hash, str)
    assert len(first.content_hash) == 64  # sha256 hex digest
    assert first.content_hash == second.content_hash


def test_content_hash_is_deterministic_rebuilding_input_from_fixture(
    pay_doc: dict[str, Any],
) -> None:
    first = calculate_run(_build_run_input(pay_doc))
    second = calculate_run(_build_run_input(pay_doc))
    assert first.content_hash == second.content_hash


def test_unrounded_value_is_a_clean_decimal_string_for_passthrough_lines(
    run_result: RunResult,
) -> None:
    emp = run_result.employees[0]
    trace = emp.lines[0]
    # direct_monthly_amount passthrough: unrounded_value must parse cleanly
    # back to the same Decimal as rounded_value's underlying amount.
    assert Decimal(trace.unrounded_value) == trace.rounded_value.amount
