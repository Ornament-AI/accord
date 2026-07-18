"""Model smoke tests reuse migration scratch-DB fixtures.

Import (not pytest_plugins) so collecting migrations + models together does not
re-register ``tests.migrations.conftest`` as a plugin.
"""

from tests.migrations.conftest import (  # noqa: F401
    as_psycopg_url,
    diag,
    ensure_accord_roles,
    run_alembic,
    scratch_db,
)
