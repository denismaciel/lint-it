from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.architecture import Architecture
from lint_it.core import Finding, finding, is_test_file

MONKEYPATCH_METHODS = frozenset(
    {
        "chdir",
        "context",
        "delattr",
        "delenv",
        "delitem",
        "setattr",
        "setenv",
        "setitem",
        "syspath_prepend",
    }
)


class NoTestMocksRule:
    code = "PAL002"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        if not is_test_file(filename):
            return []
        visitor = _Visitor(self, filename)
        visitor.visit(tree)
        return visitor.findings


class _Visitor(ast.NodeVisitor):
    def __init__(self, rule: NoTestMocksRule, filename: str) -> None:
        self.rule = rule
        self.filename = filename
        self.findings: list[Finding] = []
        self.monkeypatch_names: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        if any(
            alias.name == "unittest.mock" or alias.name.startswith("unittest.mock.")
            for alias in node.names
        ):
            self._add(node, "do not import unittest.mock in tests")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "unittest.mock" or (
            node.module == "unittest" and any(alias.name == "mock" for alias in node.names)
        ):
            self._add(node, "do not import unittest.mock in tests")
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._capture(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._capture(node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in self.monkeypatch_names
            and node.func.attr in MONKEYPATCH_METHODS
        ):
            self._add(node, "do not use pytest monkeypatch in tests")
        self.generic_visit(node)

    def _capture(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ):
            if argument.arg == "monkeypatch":
                self.monkeypatch_names.add(argument.arg)

    def _add(self, node: ast.AST, message: str) -> None:
        self.findings.append(finding(self.rule, self.filename, node, message))
