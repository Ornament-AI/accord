"""Typed calculation-engine inputs (ADR 0005/0007).

The engine consumes plain frozen dataclasses. A future DB-mapping lane will
map ORM rows into these types; this module has no DB imports.

UUID-like identifiers are ``str`` for now (e.g. ``str(uuid.UUID)`` from an
upstream lane). Do not import ``uuid`` here.

Effective-dated resolution is **upstream** of this engine (ADR 0005): all
``amount`` / ``rate`` / ``basis`` values on ``ComponentInput`` are already
resolved as-of the run's service date. The engine does not look up master
data.

Classification set
------------------
The six canonical payroll classifications plus ``informational`` (excluded
from all aggregates, kept for audit — e.g. FOREGONE_HRA):

- ``earning``
- ``employer_contribution``
- ``AG_deduction``
- ``treasury_deduction``
- ``gross_adjustment``
- ``external_recovery``
- ``informational``

``informational=True`` or ``excluded_from_totals=True`` also exclude a line
from aggregates even if its classification is one of the six.

Validation scope
----------------
``ComponentInput.__post_init__`` validates ``classification`` membership and a
non-empty ``component_code``. Unknown ``calc_kind`` values are rejected later
by the closed calculator registry (``UnknownCalculatorKindError``) so the
engine can propagate a typed error during calculation. Amount/rate shape
requirements (passthrough kinds need ``amount``, percentage/contribution kinds
need ``rate`` + non-empty ``basis``) are also enforced by the calculator layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.payroll.money import Money
from app.domain.payroll.rates import Rate
from app.domain.payroll.rounding import ROUND_NONE

ALLOWED_CLASSIFICATIONS: frozenset[str] = frozenset(
    {
        "earning",
        "employer_contribution",
        "AG_deduction",
        "treasury_deduction",
        "gross_adjustment",
        "external_recovery",
        "informational",
    }
)

# Documented ADR-0007 kind names (enforced by calculators.get, not construction).
KNOWN_CALC_KINDS: frozenset[str] = frozenset(
    {
        "fixed_recurring_amount",
        "direct_monthly_amount",
        "percentage_of_component_bases",
        "employer_employee_contribution",
        "loan_installment_recovery",
        "accommodation_charge",
        "one_time_adjustment",
    }
)


class InvalidComponentInputError(ValueError):
    """Raised when a ``ComponentInput`` fails structural validation."""


@dataclass(frozen=True, slots=True)
class ComponentInput:
    """One pay-component line ready for calculation.

    Default ``rounding_rule`` is ``ROUND_NONE``: passthrough kinds treat the
    supplied ``Money`` amount as already final. Percentage / contribution kinds
    must supply a non-``ROUND_NONE`` rule (or ``UnroundedAmount.quantize`` will
    reject it).

    ``calc_kind`` should be one of the seven ADR-0007 names in
    ``KNOWN_CALC_KINDS``; unrecognized kinds fail at calculation time via
    ``UnknownCalculatorKindError``.
    """

    component_code: str
    classification: str
    calc_kind: str
    amount: Money | None = None
    rate: Rate | None = None
    basis: tuple[str, ...] = ()
    rounding_rule: str = ROUND_NONE
    source_version_ids: tuple[str, ...] = ()
    informational: bool = False
    excluded_from_totals: bool = False
    gpf_jurisdiction: str | None = None
    accommodation_location: str | None = None
    employer_transfer: bool = False
    transfer_of: str | None = None
    service_period: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.classification not in ALLOWED_CLASSIFICATIONS:
            raise InvalidComponentInputError(
                f"unknown classification {self.classification!r}; "
                f"allowed={sorted(ALLOWED_CLASSIFICATIONS)}"
            )
        if not self.component_code:
            raise InvalidComponentInputError("component_code must be non-empty")

    def is_excluded_from_aggregates(self) -> bool:
        """True when this line must not contribute to any money aggregate."""
        return (
            self.informational
            or self.excluded_from_totals
            or self.classification == "informational"
        )


@dataclass(frozen=True, slots=True)
class EmployeeCalcInput:
    """Per-employee calculation input.

    ``retirement_regime`` and ``gpf_jurisdiction`` are informational passthrough
    for callers/tests; the engine does not enforce regime exclusivity.
    """

    employee_ref: str
    components: tuple[ComponentInput, ...]
    retirement_regime: str | None = None
    gpf_jurisdiction: str | None = None

    def __post_init__(self) -> None:
        if not self.employee_ref:
            raise InvalidComponentInputError("employee_ref must be non-empty")


@dataclass(frozen=True, slots=True)
class RunCalcInput:
    """Full payroll-run calculation input.

    The engine expects all rates/amounts already effective-resolved as-of the
    run's service date. Resolution of effective-dated master data is upstream
    (ADR 0005) and out of scope for this engine.
    """

    period: str
    org_ref: str
    employees: tuple[EmployeeCalcInput, ...] = ()

    def __post_init__(self) -> None:
        if not self.period:
            raise InvalidComponentInputError("period must be non-empty")
        if not self.org_ref:
            raise InvalidComponentInputError("org_ref must be non-empty")
