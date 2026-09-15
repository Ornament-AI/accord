"""Non-negative money/rate CHECK bounds on mutable input + master-data tables.

Revision ID: c3d9e5f2a714
Revises: b4d8e2a1c306
Create Date: 2026-09-24

T1.4 (docs/review-2026-09.md): negative money previously flowed to posted
payroll. Bounds mirror the Pydantic schemas and the storage contracts
(money ``Numeric(12, 2)`` -> ±99999999.99, rates ``Numeric(9, 4)`` ->
0..99999.9999).

Deliberate carve-outs preserved:

* ``payroll_run_inputs.amount`` may be negative only when
  ``input_kind = 'one_time'`` (one_time_adjustment recovers prior-period
  overpayments).
* ``component_rate_versions.amount`` may be negative only when
  ``calc_kind = 'one_time_adjustment'``.
* ``recurring_instruction_versions.amount`` stays signed: the calc kind is
  resolved from the linked component's rate version, so the carve-out cannot
  be decided on this row; ``validate_run_inputs`` enforces the kind rule at
  calculate time.
* Roster ``da_difference`` keeps its existing signed CHECK.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c3d9e5f2a714"
down_revision: str | None = "b4d8e2a1c306"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MONEY_MAX = "99999999.99"
_RATE_MAX = "99999.9999"

# (table, constraint_name, condition)
_CHECKS: tuple[tuple[str, str, str], ...] = (
    (
        "payroll_run_inputs",
        "ck_payroll_run_inputs_amount",
        "amount IS NULL OR ("
        f"amount >= -{_MONEY_MAX} AND amount <= {_MONEY_MAX} AND ("
        "input_kind = 'one_time' OR amount >= 0))",
    ),
    (
        "payroll_run_inputs",
        "ck_payroll_run_inputs_rate",
        f"rate IS NULL OR (rate >= 0 AND rate <= {_RATE_MAX})",
    ),
    (
        "recurring_instruction_versions",
        "ck_recurring_instruction_versions_amount",
        "amount IS NULL OR ("
        f"amount >= -{_MONEY_MAX} AND amount <= {_MONEY_MAX})",
    ),
    (
        "recurring_instruction_versions",
        "ck_recurring_instruction_versions_rate",
        f"rate IS NULL OR (rate >= 0 AND rate <= {_RATE_MAX})",
    ),
    (
        "advance_accounts",
        "ck_advance_accounts_principal_positive",
        f"principal > 0 AND principal <= {_MONEY_MAX}",
    ),
    (
        "advance_installment_versions",
        "ck_advance_installment_versions_installment_amount",
        f"installment_amount > 0 AND installment_amount <= {_MONEY_MAX}",
    ),
    (
        "advance_installment_versions",
        "ck_advance_installment_versions_installments",
        "installments_total > 0 AND installments_recovered_opening >= 0 "
        "AND installments_recovered_opening <= installments_total",
    ),
    (
        "component_rate_versions",
        "ck_component_rate_versions_amount",
        "calc_kind = 'one_time_adjustment' OR amount IS NULL OR amount >= 0",
    ),
    (
        "component_rate_versions",
        "ck_component_rate_versions_rate",
        f"rate IS NULL OR (rate >= 0 AND rate <= {_RATE_MAX})",
    ),
    (
        "accommodation_charge_versions",
        "ck_accommodation_charge_versions_license_fee",
        f"license_fee >= 0 AND license_fee <= {_MONEY_MAX}",
    ),
    (
        "accommodation_charge_versions",
        "ck_accommodation_charge_versions_house_rent",
        "house_rent IS NULL OR ("
        f"house_rent >= 0 AND house_rent <= {_MONEY_MAX})",
    ),
    (
        "accommodation_charge_versions",
        "ck_accommodation_charge_versions_service_charge",
        "service_charge IS NULL OR ("
        f"service_charge >= 0 AND service_charge <= {_MONEY_MAX})",
    ),
    (
        "accommodation_charge_versions",
        "ck_accommodation_charge_versions_parking_charge",
        "parking_charge IS NULL OR ("
        f"parking_charge >= 0 AND parking_charge <= {_MONEY_MAX})",
    ),
    (
        "accommodation_charge_versions",
        "ck_accommodation_charge_versions_additional_parking",
        "additional_parking_charge IS NULL OR ("
        f"additional_parking_charge >= 0 AND additional_parking_charge <= {_MONEY_MAX})",
    ),
    (
        "accommodation_charge_versions",
        "ck_accommodation_charge_versions_hra_foregone",
        "informational_hra_foregone IS NULL OR ("
        f"informational_hra_foregone >= 0 AND informational_hra_foregone <= {_MONEY_MAX})",
    ),
    (
        "employee_pay_versions",
        "ck_employee_pay_versions_basic_pay_nonneg",
        f"basic_pay >= 0 AND basic_pay <= {_MONEY_MAX}",
    ),
)


def upgrade() -> None:
    for table, name, condition in _CHECKS:
        op.create_check_constraint(name, table, condition)


def downgrade() -> None:
    for table, name, _condition in reversed(_CHECKS):
        op.drop_constraint(name, table, type_="check")
