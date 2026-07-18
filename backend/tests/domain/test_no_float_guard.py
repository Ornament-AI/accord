"""CI float-ban guard for ``backend/app/domain`` (ADR 0006).

Limitation (documented in ``_float_guard``): the scanner does not flag
fully-qualified typing constructs such as ``typing.Optional[float]`` or
``list[float]``. A stretch goal for ``X | float`` unions is implemented when
both sides are simple Names.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.domain._float_guard import (
    format_violations,
    scan,
    scan_directory,
    scan_source,
)

_DOMAIN_ROOT = Path(__file__).resolve().parents[2] / "app" / "domain"


def test_domain_package_has_no_float_violations() -> None:
    """Walk every ``.py`` under ``backend/app/domain`` at test-run time."""
    assert _DOMAIN_ROOT.is_dir(), f"missing domain package: {_DOMAIN_ROOT}"
    violations = scan_directory(_DOMAIN_ROOT)
    if violations:
        joined = "\n".join(format_violations(violations))
        pytest.fail(f"float ban violations in domain package:\n{joined}")


def test_float_literal_is_flagged() -> None:
    violations = scan_source("x = 1.5\n")
    assert len(violations) == 1
    assert "float literal" in violations[0].message
    assert violations[0].lineno == 1


def test_float_call_is_flagged() -> None:
    violations = scan_source('y = float("1.5")\n')
    assert len(violations) == 1
    assert "call to float" in violations[0].message


def test_float_param_and_return_annotations_are_flagged() -> None:
    source = "def f(x: float) -> float:\n    return x\n"
    violations = scan_source(source)
    messages = "\n".join(format_violations(violations))
    assert any("parameter 'x'" in v.message for v in violations), messages
    assert any("return annotation" in v.message for v in violations), messages


def test_annassign_float_is_flagged() -> None:
    violations = scan_source("x: float = 0\n")
    assert len(violations) == 1
    assert "annotation 'float'" in violations[0].message


def test_bit_or_union_with_float_is_flagged() -> None:
    violations = scan_source("def f(x: int | float) -> None:\n    return None\n")
    assert any("float" in v.message for v in violations)


def test_clean_snippet_has_zero_violations() -> None:
    source = (
        "from decimal import Decimal\n"
        "\n"
        "def add(a: Decimal, b: Decimal) -> Decimal:\n"
        "    if isinstance(a, float):\n"
        "        raise TypeError('banned')\n"
        "    return a + b\n"
    )
    assert scan_source(source) == []


def test_scan_accepts_path_and_tempfile(tmp_path: Path) -> None:
    dirty = tmp_path / "dirty.py"
    dirty.write_text("x = 1.5\ny = float('1')\n", encoding="utf-8")
    violations = scan(dirty)
    assert len(violations) == 2
    assert all(str(dirty) in v.path for v in violations)


def test_optional_float_limitation_is_documented() -> None:
    """Known gap: typing.Optional[float] is not flagged in this first pass."""
    violations = scan_source("from typing import Optional\nx: Optional[float] = None\n")
    assert violations == []
