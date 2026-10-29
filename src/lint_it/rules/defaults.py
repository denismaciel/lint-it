from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping

from lint_it.core import Finding, SourceFile, finding
from lint_it.policy import EDGE_LAYERS


def _defaults(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[ast.expr, ...]:
    keyword = tuple(value for value in node.args.kw_defaults if value is not None)
    return (*node.args.defaults, *keyword)


def _bases(node: ast.ClassDef) -> tuple[str, ...]:
    return tuple(ast.unparse(base) for base in node.bases)


CONSTANT_NAME = re.compile(r"^_?[A-Z][A-Z0-9_]*$")
IMMUTABLE_CONSTRUCTORS = frozenset(
    {
        "Decimal",
        "Fraction",
        "datetime.timedelta",
        "decimal.Decimal",
        "fractions.Fraction",
        "frozenset",
        "timedelta",
        "tuple",
    }
)


def _module_constants(tree: ast.Module) -> dict[str, ast.expr]:
    constants: dict[str, ast.expr] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            if isinstance(target, ast.Name):
                constants[target.id] = statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            if isinstance(statement.target, ast.Name):
                constants[statement.target.id] = statement.value
    return constants


def _immutable_default(node: ast.expr, constants: Mapping[str, ast.expr]) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Tuple):
        return all(_immutable_default(item, constants) for item in node.elts)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return isinstance(node.operand, ast.Constant) and isinstance(
            node.operand.value, (int, float, complex)
        )
    if isinstance(node, ast.Name):
        if not CONSTANT_NAME.match(node.id):
            return False
        bound = constants.get(node.id)
        remaining = {name: value for name, value in constants.items() if name != node.id}
        return bound is None or _immutable_default(bound, remaining)
    if isinstance(node, ast.Attribute):
        return bool(CONSTANT_NAME.match(node.attr))
    if isinstance(node, ast.Call) and ast.unparse(node.func) in IMMUTABLE_CONSTRUCTORS:
        arguments = (*node.args, *(keyword.value for keyword in node.keywords))
        return all(_immutable_collection(argument, constants) for argument in arguments)
    return False


def _immutable_collection(node: ast.expr, constants: Mapping[str, ast.expr]) -> bool:
    if isinstance(node, (ast.List, ast.Set)):
        return all(_immutable_default(item, constants) for item in node.elts)
    return _immutable_default(node, constants)


class ImmutableDefaultRule:
    """A parameter default is not an immutable value.

    Outside the edge layers (boundary, router, transaction, test), defaults may
    only be literals, signed numbers, tuples, `UPPER_CASE` constants and enum
    members, and immutable constructors such as `frozenset()` or `Decimal("0")`
    over those. A same-module constant bound to a mutable value still counts as
    mutable. A default such as
    `[]`, `Settings()` or `datetime.now()` is evaluated once at import time and
    hides a dependency; make the caller pass it. Protocol methods and exception
    `__init__` methods are exempt.
    """

    code = "LIT305"
    name = "immutable-defaults"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        if file.layer is None or file.has_layer(*EDGE_LAYERS):
            return []
        visitor = _Visitor(self, file)
        visitor.visit(file.tree)
        return visitor.findings


class _Visitor(ast.NodeVisitor):
    def __init__(self, rule: ImmutableDefaultRule, file: SourceFile) -> None:
        self.rule = rule
        self.file = file
        self.findings: list[Finding] = []
        self.constants = _module_constants(file.tree)
        self.protocol_depth = 0
        self.exception_depth = 0

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = _bases(node)
        is_protocol = any(base == "Protocol" or base.endswith(".Protocol") for base in bases)
        is_exception = node.name.endswith(("Error", "Exception")) or any(
            base in {"Exception", "BaseException"}
            or base.endswith((".Exception", ".BaseException"))
            for base in bases
        )
        self.protocol_depth += is_protocol
        self.exception_depth += is_exception
        self.generic_visit(node)
        self.protocol_depth -= is_protocol
        self.exception_depth -= is_exception

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_function(node)

    def _check_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        exempt = self.protocol_depth > 0 or (self.exception_depth > 0 and node.name == "__init__")
        if not exempt and any(
            not _immutable_default(default, self.constants) for default in _defaults(node)
        ):
            self.findings.append(
                finding(
                    self.rule,
                    self.file,
                    node,
                    "parameter defaults must be immutable literals; "
                    "have the caller pass constructed values",
                )
            )
        self.generic_visit(node)
