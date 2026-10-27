from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.core import Finding, SourceFile, finding
from lint_it.policy import Layer

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
MOCK_FIXTURES = frozenset({"mocker", "class_mocker", "module_mocker", "package_mocker"})


class MockingRule:
    """A test patches code instead of passing fakes in.

    Reports `unittest.mock`, pytest-mock fixtures (`mocker` and friends) and
    `monkeypatch` methods in test modules. If a test needs to replace a
    collaborator, the code under test should accept it as a port; pass a
    hand-written fake that implements it.
    """

    code = "LIT304"
    name = "mocking"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        if not file.has_layer(Layer.TEST):
            return []
        visitor = _Visitor(self, file)
        visitor.visit(file.tree)
        return visitor.findings


class _Visitor(ast.NodeVisitor):
    def __init__(self, rule: MockingRule, file: SourceFile) -> None:
        self.rule = rule
        self.file = file
        self.findings: list[Finding] = []

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
        self._check_fixtures(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_fixtures(node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "monkeypatch"
            and node.func.attr in MONKEYPATCH_METHODS
        ):
            self._add(node, "do not use pytest monkeypatch in tests")
        self.generic_visit(node)

    def _check_fixtures(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            if argument.arg in MOCK_FIXTURES:
                self._add(argument, "do not use pytest-mock fixtures in tests")

    def _add(self, node: ast.AST, message: str) -> None:
        self.findings.append(finding(self.rule, self.file, node, message))
