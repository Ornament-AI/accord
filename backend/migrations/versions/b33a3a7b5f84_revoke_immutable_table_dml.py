"""Revoke UPDATE/DELETE/TRUNCATE on immutable financial tables.

Revision ID: b33a3a7b5f84
Revises: a9f3c2e81b04
Create Date: 2026-07-18

Defense-in-depth for High finding: posted/immutable financial tables
(``payroll_run_versions``, ``payroll_employee_results``, ``payroll_result_lines``,
``payroll_approvals``, ``audit_events``) must not retain UPDATE/DELETE/TRUNCATE
grants for runtime roles ``accord_app`` / ``accord_worker``.

Protection previously relied only on the ``accord_forbid_update_delete`` trigger
whose escape hatch (``SET LOCAL accord.allow_immutable_ddl = 'on'``) is settable
via plain SET LOCAL. This migration adds the ADR-0009 grant/revoke backstop so
UPDATE/DELETE/TRUNCATE are impossible for these roles even if the trigger is
bypassed. INSERT + SELECT remain (insert-then-immutable).

``create_roles.sql`` ALTER DEFAULT PRIVILEGES grants SELECT/INSERT/UPDATE/DELETE
on migrator-created tables; REVOKE of a privilege not held is a no-op, so this
is idempotent-safe. Mutable tables (``payroll_runs``, ``payroll_run_inputs``,
``outbox_events``) are intentionally untouched.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b33a3a7b5f84"
down_revision: Union[str, None] = "a9f3c2e81b04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IMMUTABLE_TABLES = (
    "payroll_run_versions",
    "payroll_employee_results",
    "payroll_result_lines",
    "payroll_approvals",
    "audit_events",
)

# Downgrade re-grants only phase4 snapshot + approvals tables. audit_events is
# omitted because migration a9f3c2e81b04 owns its REVOKE; downgrading to that
# revision must leave audit_events revoked.
DOWNGRADE_REGRANT_TABLES = (
    "payroll_run_versions",
    "payroll_employee_results",
    "payroll_result_lines",
    "payroll_approvals",
)


def upgrade() -> None:
    for table_name in IMMUTABLE_TABLES:
        op.execute(
            f"REVOKE UPDATE, DELETE, TRUNCATE ON TABLE {table_name} FROM accord_app, accord_worker"
        )


def downgrade() -> None:
    # Do not re-grant TRUNCATE — create_roles.sql default privileges only ever
    # granted SELECT/INSERT/UPDATE/DELETE.
    for table_name in DOWNGRADE_REGRANT_TABLES:
        op.execute(f"GRANT UPDATE, DELETE ON TABLE {table_name} TO accord_app, accord_worker")
