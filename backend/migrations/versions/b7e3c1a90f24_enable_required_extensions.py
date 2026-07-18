"""Enable required extensions.

Revision ID: b7e3c1a90f24
Revises:
Create Date: 2026-07-17

Phase 1 initial migration — extensions only; no tenant tables.

Empirical check against local PostgreSQL 18.4 (Homebrew):
``SELECT gen_random_uuid();`` succeeds with **no** extensions installed.
``gen_random_uuid()`` has been built into PostgreSQL core since PG 13, so
``pgcrypto`` is not required for UUID defaults and is intentionally not
created here.

``btree_gist`` **is** created: ADR-0005 effective-dated master data will need
GiST exclusion constraints (``EXCLUDE USING gist``) on version tables in
later phases.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e3c1a90f24"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
