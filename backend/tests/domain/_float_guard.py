"""AST float-ban scanner for ``backend/app/domain`` (ADR 0006).

Detects:
- ``ast.Constant`` whose value is a Python ``float``
- bare ``float(...)`` calls (Name ``float``)
- annotations that are exactly the name ``float`` on ``AnnAssign``,
  parameters, and return annotations

Limitation: does not catch typing constructs such as ``typing.Optional[float]``,
``list[float]``, or ``Annotated[float, ...]``. A stretch goal for ``X | float``
unions is implemented when both sides are simple ``ast.Name`` nodes.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FloatViolation:
    path: str
    lineno: int
    message: str

    def format(self) -> str:
        return f"{self.path}:{self.lineno}: {self.message}"


def _is_float_name(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "float"


def _annotation_is_bare_float(node: ast.AST) -> bool:
    if _is_float_name(node):
        return True
    # Stretch: X | float / float | X with simple Name operands.
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _is_float_name(node.left) or _is_float_name(node.right)
    return False


class _FloatVisitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.violations: list[FloatViolation] = []

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, float):
            self.violations.append(
                FloatViolation(
                    self.path,
                    node.lineno,
                    f"float literal {node.value!r} is banned in domain code",
                )
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if _is_float_name(node.func):
            self.violations.append(
                FloatViolation(
                    self.path,
                    node.lineno,
                    "call to float(...) is banned in domain code",
                )
            )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if _annotation_is_bare_float(node.annotation):
            self.violations.append(
                FloatViolation(
                    self.path,
                    node.lineno,
                    "annotation 'float' is banned in domain code",
                )
            )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_function_annotations(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_function_annotations(node)
        self.generic_visit(node)

    def _check_function_annotations(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for arg in (*node.args.args, *node.args.posonlyargs, *node.args.kwonlyargs):
            if arg.annotation is not None and _annotation_is_bare_float(arg.annotation):
                self.violations.append(
                    FloatViolation(
                        self.path,
                        arg.lineno,
                        f"parameter {arg.arg!r} annotated as float is banned",
                    )
                )
        if node.args.vararg is not None and node.args.vararg.annotation is not None:
            if _annotation_is_bare_float(node.args.vararg.annotation):
                self.violations.append(
                    FloatViolation(
                        self.path,
                        node.args.vararg.lineno,
                        f"parameter {node.args.vararg.arg!r} annotated as float is banned",
                    )
                )
        if node.args.kwarg is not None and node.args.kwarg.annotation is not None:
            if _annotation_is_bare_float(node.args.kwarg.annotation):
                self.violations.append(
                    FloatViolation(
                        self.path,
                        node.args.kwarg.lineno,
                        f"parameter {node.args.kwarg.arg!r} annotated as float is banned",
                    )
                )
        if node.returns is not None and _annotation_is_bare_float(node.returns):
            self.violations.append(
                FloatViolation(
                    self.path,
                    node.lineno,
                    "return annotation 'float' is banned in domain code",
                )
            )


def scan_source(source: str, *, path: str = "<memory>") -> list[FloatViolation]:
    """Scan a Python source string; return all float-ban violations."""
    tree = ast.parse(source, filename=path)
    visitor = _FloatVisitor(path)
    visitor.visit(tree)
    return visitor.violations


def scan_file(path: Path) -> list[FloatViolation]:
    """Scan a single ``.py`` file."""
    source = path.read_text(encoding="utf-8")
    return scan_source(source, path=str(path))


def scan(source_or_path: str | Path, *, path: str = "<memory>") -> list[FloatViolation]:
    """Scan a source string or a ``Path`` to a ``.py`` file."""
    if isinstance(source_or_path, Path):
        return scan_file(source_or_path)
    return scan_source(source_or_path, path=path)


def scan_directory(root: Path) -> list[FloatViolation]:
    """Recursively scan every ``.py`` file under ``root``."""
    violations: list[FloatViolation] = []
    for py_path in sorted(root.rglob("*.py")):
        violations.extend(scan_file(py_path))
    return violations


# Alias kept for readability at call sites that scan the domain package.
scan_domain_tree = scan_directory


def format_violations(violations: list[FloatViolation]) -> list[str]:
    """Return human-readable ``path:lineno: message`` strings."""
    return [v.format() for v in violations]
