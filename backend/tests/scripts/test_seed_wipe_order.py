"""Guard the FK-safe wipe ordering in scripts/seed_paybill_xlsx.py.

The wipe issues plain DELETEs (no CASCADE), so every child table must appear
before its parent. Regression: payroll_run_employees was missing entirely,
making DELETE FROM payroll_runs fail once any roster row existed.
"""

from __future__ import annotations

import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "seed_paybill_xlsx.py"

# child table -> parent table it references with a plain (non-cascading) FK
FK_CHILD_BEFORE_PARENT = [
    ("payroll_run_employees", "payroll_runs"),
    ("payroll_run_employees", "employees"),
    ("payroll_run_versions", "payroll_runs"),
    ("payroll_run_inputs", "payroll_runs"),
    ("payroll_runs", "payroll_periods"),
    ("employee_profile_versions", "employees"),
]


def _wipe_tables() -> list[str]:
    source = SCRIPT.read_text()
    match = re.search(r"tables\s*=\s*\[(.*?)\]", source, flags=re.DOTALL)
    assert match, "could not locate the wipe tables list in seed_paybill_xlsx.py"
    return re.findall(r'"([a-z_]+)"', match.group(1))


def test_wipe_list_contains_roster_table():
    assert "payroll_run_employees" in _wipe_tables()


def test_wipe_list_deletes_children_before_parents():
    tables = _wipe_tables()
    for child, parent in FK_CHILD_BEFORE_PARENT:
        assert child in tables, f"{child} missing from wipe list"
        assert parent in tables, f"{parent} missing from wipe list"
        assert tables.index(child) < tables.index(parent), (
            f"{child} must be wiped before {parent} (plain DELETE, no CASCADE)"
        )
