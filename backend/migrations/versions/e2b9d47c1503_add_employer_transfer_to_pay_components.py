"""Add employer-transfer metadata to the pay component catalog.

Revision ID: e2b9d47c1503
Revises: d1f6a8c3b70e
Create Date: 2026-07-19

``disbursement`` (added in d1f6a8c3b70e) is derived from employer-transfer
deduction lines that have no paired ``employer_contribution`` addition in gross
(off-bill NPS employer). The engine reads that pairing from
``ComponentInput.employer_transfer`` / ``transfer_of``, but the pay-component
catalog had no column to carry it — so any run calculated from real master data
produced ``offbill_employer_remittance = 0`` and silently collapsed
``disbursement`` back onto ``net_payable``.

These two columns are the catalog's record of that pairing:

* ``employer_transfer`` — line reverses an employer contribution out of net.
* ``transfer_of`` — code of the ``employer_contribution`` component it reverses.
  NULL means the transfer has **no** gross-bill addition, i.e. it is off-bill
  (NPS employer). ``EPF_EMPLOYER_TRANSFER`` points at ``EPF_EMPLOYER`` and is
  therefore a true pass-through, not off-bill.

See the "Resolved" section of ``docs/payroll-domain.md``.
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2b9d47c1503"
down_revision: Union[str, None] = "d1f6a8c3b70e"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None

_TABLE = "pay_components"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            "employer_transfer",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Nullable by design: NULL transfer_of on an employer_transfer line means
    # "off-bill" (no paired gross addition).
    op.add_column(_TABLE, sa.Column("transfer_of", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_pay_components_transfer_of_requires_employer_transfer",
        _TABLE,
        "transfer_of IS NULL OR employer_transfer",
    )
    # These codes are stable catalog business keys used by every existing
    # Accord fixture/seed. Backfill upgraded tenants so their next calculation
    # does not silently collapse disbursement onto net payable.
    op.execute(
        sa.text(
            "UPDATE pay_components "
            "SET employer_transfer = true, transfer_of = NULL "
            "WHERE code = 'NPS_EMPLOYER_TRANSFER'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE pay_components "
            "SET employer_transfer = true, transfer_of = 'EPF_EMPLOYER' "
            "WHERE code = 'EPF_EMPLOYER_TRANSFER'"
        )
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_pay_components_transfer_of_requires_employer_transfer",
        _TABLE,
        type_="check",
    )
    op.drop_column(_TABLE, "transfer_of")
    op.drop_column(_TABLE, "employer_transfer")
