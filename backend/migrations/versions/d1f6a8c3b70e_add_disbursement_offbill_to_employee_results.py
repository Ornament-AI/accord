"""Add off-bill employer remittance and disbursement to employee results.

Revision ID: d1f6a8c3b70e
Revises: e6a8c4d2f901
Create Date: 2026-07-19

Department sign-off 18 Jul 2026 confirmed that the NPS/DCPS employer share is
**off-bill**: it is never added to the gross bill, and the bank/RTGS total is a
**separate** figure from the treasury-face "Net Payable". See the "Resolved"
section of ``docs/payroll-domain.md``.

That makes two figures diverge, so both must be persisted on the immutable
result snapshot:

* ``net_payable`` (existing) — treasury-face net; has off-bill NPS employer
  subtracted.
* ``disbursement`` (new) — what the employee actually receives as bank credit
  ``= net_payable + offbill_employer_remittance``.

``offbill_employer_remittance`` is the sum of employer-transfer deduction lines
with no paired ``employer_contribution`` addition in gross (NPS employer only;
EPF employer is a true pass-through and is excluded).

Columns are added NOT NULL with a temporary ``server_default`` of 0 so the DDL
is safe on a populated table. Existing immutable snapshots are then migrated to
the only historically knowable compatibility value: zero off-bill remittance
and disbursement equal to the already-approved net payable. Matching run-version
totals receive the same values. The defaults are finally dropped so every future
insert must supply both values explicitly.
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1f6a8c3b70e"
down_revision: Union[str, None] = "e6a8c4d2f901"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None

_TABLE = "payroll_employee_results"
_COLUMNS = ("offbill_employer_remittance", "disbursement")


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column(
            _TABLE,
            sa.Column(name, sa.Numeric(14, 2), nullable=False, server_default="0"),
        )
    # Controlled migration-only escape hatch for the immutable snapshot guards.
    op.execute(sa.text("SET LOCAL accord.allow_immutable_ddl = 'on'"))

    # Old snapshots predate the off-bill distinction. Preserve the amount that
    # those runs historically treated as the employee bank credit rather than
    # turning every historical payslip/advice into a zero payment.
    op.execute(
        sa.text(
            "UPDATE payroll_employee_results "
            "SET offbill_employer_remittance = 0, disbursement = net_payable"
        )
    )
    op.execute(
        sa.text(
            "UPDATE payroll_run_versions "
            "SET totals = jsonb_set("
            "jsonb_set(COALESCE(totals, '{}'::jsonb), "
            "'{offbill_employer_remittance}', to_jsonb('0.00'::text), true), "
            "'{disbursement}', "
            "to_jsonb(COALESCE(totals->>'net_payable', '0.00')), true)"
        )
    )

    for name in _COLUMNS:
        # Drop the bootstrap default: writers must be explicit from here on.
        op.alter_column(_TABLE, name, server_default=None)


def downgrade() -> None:
    for name in reversed(_COLUMNS):
        op.drop_column(_TABLE, name)
