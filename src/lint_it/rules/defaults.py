from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.core import Finding, SourceFile, finding
from lint_it.policy import EDGE_LAYERS


def _defaults(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[ast.expr, ...]:
    keyword = tuple(value for value in node.args.kw_defaults if value is not None)
    return (*node.args.defaults, *keyword)


def _bases(node: ast.ClassDef) -> tuple[str, ...]:
    return tuple(ast.unparse(base) for base in node.bases)


def _immutable_default(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Tuple):
        return all(_immutable_default(item) for item in node.elts)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return isinstance(node.operand, ast.Constant) and isinstance(
            node.operand.value, (int, float, complex)
        )
    return False


class ImmutableDefaultRule:
    """A parameter default is not an immutable literal.

    Outside the edge layers (boundary, router, transaction, test), defaults may
    only be constants, signed numbers, and tuples of those. A default such as
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
        if not exempt and any(not _immutable_default(default) for default in _defaults(node)):
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
