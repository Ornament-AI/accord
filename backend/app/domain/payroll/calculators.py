"""Closed typed calculator registry (ADR 0007).

Calculator contract
-------------------
Every calculator is a pure function::

    (CalculatorContext) -> CalculatorResult

``CalculatorContext`` carries:

- ``component``: the ``ComponentInput`` being calculated
- ``computed``: mapping of already-calculated ``component_code -> Money`` for
  basis lookup (the engine topologically orders so bases are present)

``CalculatorResult`` carries:

- ``rounded_value``: final ``Money`` (already rounded per the line's rule)
- ``unrounded_value``: pre-round ``Decimal`` (full precision; for passthrough
  kinds this equals the input amount's ``Decimal``)
- ``basis_total``: sum of basis ``Money`` values when applicable, else ``None``
- ``rate``: the rate used when applicable, else ``None``

Passthrough kinds (``fixed_recurring_amount``, ``direct_monthly_amount``,
``loan_installment_recovery``, ``accommodation_charge``, ``one_time_adjustment``)
require ``ComponentInput.amount``. ``one_time_adjustment`` **may be negative**;
callers must not assume non-negative Money.

Percentage-shaped kinds (``percentage_of_component_bases``,
``employer_employee_contribution``) require ``rate`` and a non-empty ``basis``.
They compute ``Money.sum(basis values) * rate -> UnroundedAmount``, then
``quantize(rounding_rule)``. Employer/employee pairing semantics live in the
component catalog, not in these calculators.

Unknown kinds raise ``UnknownCalculatorKindError`` (never a bare ``KeyError``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from app.domain.payroll.inputs import ComponentInput
from app.domain.payroll.money import Money
from app.domain.payroll.rates import Rate

# --- errors -----------------------------------------------------------------


class UnknownCalculatorKindError(ValueError):
    """Raised when ``calc_kind`` is not in the closed calculator registry."""


class MissingAmountError(ValueError):
    """Raised when a passthrough calculator kind is missing ``amount``."""


class MissingRateError(ValueError):
    """Raised when a percentage/contribution kind is missing ``rate``."""


class MissingBasisError(ValueError):
    """Raised when a percentage/contribution kind has an empty ``basis``."""


class MissingBasisComponentError(ValueError):
    """Raised when a named basis component has not been computed yet."""

    def __init__(self, *, missing_code: str, requesting_code: str) -> None:
        self.missing_code = missing_code
        self.requesting_code = requesting_code
        super().__init__(
            f"basis component {missing_code!r} not computed for "
            f"requesting component {requesting_code!r}"
        )


# --- context / result -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CalculatorContext:
    """Inputs available to a single calculator invocation."""

    component: ComponentInput
    computed: Mapping[str, Money]


@dataclass(frozen=True, slots=True)
class CalculatorResult:
    """Output of a single calculator invocation."""

    rounded_value: Money
    unrounded_value: Decimal
    basis_total: Money | None = None
    rate: Rate | None = None


CalculatorFn = Callable[[CalculatorContext], CalculatorResult]


# --- helpers ----------------------------------------------------------------


def _require_amount(component: ComponentInput) -> Money:
    if component.amount is None:
        raise MissingAmountError(
            f"calc_kind {component.calc_kind!r} requires amount on "
            f"component {component.component_code!r}"
        )
    return component.amount


def _passthrough(ctx: CalculatorContext) -> CalculatorResult:
    amount = _require_amount(ctx.component)
    return CalculatorResult(
        rounded_value=amount,
        unrounded_value=Decimal(amount.amount),
        basis_total=None,
        rate=None,
    )


def _sum_basis(ctx: CalculatorContext) -> Money:
    component = ctx.component
    if not component.basis:
        raise MissingBasisError(
            f"calc_kind {component.calc_kind!r} requires non-empty basis on "
            f"component {component.component_code!r}"
        )
    values: list[Money] = []
    for code in component.basis:
        try:
            values.append(ctx.computed[code])
        except KeyError as exc:
            raise MissingBasisComponentError(
                missing_code=code,
                requesting_code=component.component_code,
            ) from exc
    return Money.sum(values)


def _percentage_shaped(ctx: CalculatorContext) -> CalculatorResult:
    component = ctx.component
    if component.rate is None:
        raise MissingRateError(
            f"calc_kind {component.calc_kind!r} requires rate on "
            f"component {component.component_code!r}"
        )
    basis_total = _sum_basis(ctx)
    unrounded = basis_total * component.rate
    rounded = unrounded.quantize(component.rounding_rule)
    return CalculatorResult(
        rounded_value=rounded,
        unrounded_value=unrounded.to_decimal(),
        basis_total=basis_total,
        rate=component.rate,
    )


# --- kind implementations ---------------------------------------------------


def calculate_fixed_recurring_amount(ctx: CalculatorContext) -> CalculatorResult:
    """Passthrough of effective-dated fixed recurring amount."""
    return _passthrough(ctx)


def calculate_direct_monthly_amount(ctx: CalculatorContext) -> CalculatorResult:
    """Passthrough of direct monthly / draft override amount."""
    return _passthrough(ctx)


def calculate_loan_installment_recovery(ctx: CalculatorContext) -> CalculatorResult:
    """Passthrough of scheduled loan / advance installment amount."""
    return _passthrough(ctx)


def calculate_accommodation_charge(ctx: CalculatorContext) -> CalculatorResult:
    """Passthrough of accommodation license-fee recovery amount."""
    return _passthrough(ctx)


def calculate_one_time_adjustment(ctx: CalculatorContext) -> CalculatorResult:
    """Passthrough of one-time adjustment; amount may be negative."""
    return _passthrough(ctx)


def calculate_percentage_of_component_bases(ctx: CalculatorContext) -> CalculatorResult:
    """Rate × sum of already-computed basis component Money values."""
    return _percentage_shaped(ctx)


def calculate_employer_employee_contribution(ctx: CalculatorContext) -> CalculatorResult:
    """Same shape as percentage; pairing is a catalog concern, not here."""
    return _percentage_shaped(ctx)


# --- closed registry --------------------------------------------------------


_REGISTRY: MappingProxyType[str, CalculatorFn] = MappingProxyType(
    {
        "fixed_recurring_amount": calculate_fixed_recurring_amount,
        "direct_monthly_amount": calculate_direct_monthly_amount,
        "percentage_of_component_bases": calculate_percentage_of_component_bases,
        "employer_employee_contribution": calculate_employer_employee_contribution,
        "loan_installment_recovery": calculate_loan_installment_recovery,
        "accommodation_charge": calculate_accommodation_charge,
        "one_time_adjustment": calculate_one_time_adjustment,
    }
)


def get(calc_kind: str) -> CalculatorFn:
    """Return the calculator for ``calc_kind``.

    Raises ``UnknownCalculatorKindError`` for unrecognized kinds.
    """
    try:
        return _REGISTRY[calc_kind]
    except KeyError as exc:
        raise UnknownCalculatorKindError(f"unknown calculator kind: {calc_kind!r}") from exc
