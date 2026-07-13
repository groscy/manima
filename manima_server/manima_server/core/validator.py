"""AST allowlist validation (task 2.6, specs/sandbox).

A fast-fail run *before* execution that rejects source which obviously has no business
in a Manim scene — imports outside an allowlist, dynamic execution, filesystem/network/
process reach. Rejections are structured so the repair loop can act on them.

**This is not a security boundary (invariant 5).** The sandbox is. Validation exists to
turn a class of failures into cheap, immediate, repairable rejections instead of paying
for a container round-trip — and to give the repair loop a crisp message. Source that
slips past it is still fully contained by the sandbox; that is the intended division of
responsibility, not a defect.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

# Import roots a legitimate Manim CE scene may need. Everything else is rejected here
# (and would also be useless offline in the sandbox).
ALLOWED_IMPORT_ROOTS = frozenset(
    {"manim", "numpy", "np", "math", "cmath", "random", "itertools", "functools",
     "operator", "fractions", "decimal", "typing", "dataclasses", "collections"}
)

# Names whose mere use signals dynamic execution or host reach.
DENIED_NAMES = frozenset(
    {"exec", "eval", "compile", "__import__", "open", "globals", "locals",
     "vars", "getattr", "setattr", "delattr", "input", "breakpoint"}
)

# Dunder attributes that are the usual sandbox-escape stepping stones.
DENIED_ATTRS = frozenset(
    {"__globals__", "__builtins__", "__subclasses__", "__bases__", "__mro__",
     "__class__", "__dict__", "__code__", "__closure__", "__import__"}
)


@dataclass
class Violation:
    line: int
    message: str


@dataclass
class ValidationResult:
    ok: bool
    violations: list[Violation] = field(default_factory=list)

    def as_repair_message(self) -> str:
        """A crisp rejection the repair loop can feed back to the generator."""

        if self.ok:
            return ""
        lines = "; ".join(f"line {v.line}: {v.message}" for v in self.violations)
        return f"static validation rejected the source ({lines})"


def validate(source: str) -> ValidationResult:
    """Parse and check ``source`` against the allowlist. Never executes anything."""

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return ValidationResult(
            ok=False,
            violations=[Violation(exc.lineno or 0, f"syntax error: {exc.msg}")],
        )

    violations: list[Violation] = []
    for node in ast.walk(tree):
        _check_node(node, violations)

    return ValidationResult(ok=not violations, violations=violations)


def _check_node(node: ast.AST, out: list[Violation]) -> None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            if root not in ALLOWED_IMPORT_ROOTS:
                out.append(Violation(node.lineno, f"import of '{alias.name}' not allowed"))
    elif isinstance(node, ast.ImportFrom):
        root = (node.module or "").split(".", 1)[0]
        if root and root not in ALLOWED_IMPORT_ROOTS:
            out.append(Violation(node.lineno, f"import from '{node.module}' not allowed"))
    elif isinstance(node, ast.Name):
        if node.id in DENIED_NAMES:
            out.append(Violation(node.lineno, f"use of '{node.id}' not allowed"))
    elif isinstance(node, ast.Attribute):
        if node.attr in DENIED_ATTRS:
            out.append(Violation(node.lineno, f"access to '{node.attr}' not allowed"))


def scene_names(source: str) -> list[str]:
    """Class names that subclass a ``*Scene`` — used to resolve ambiguous scenes.

    A syntactic heuristic (bases named ``Scene``/``ThreeDScene``/...); the definitive
    scene discovery is Manim's own at render time. Returns [] on a syntax error.
    """

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                if name.endswith("Scene"):
                    found.append(node.name)
                    break
    return found
