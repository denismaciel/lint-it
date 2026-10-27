from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.architecture import Architecture, Layer, has_layer
from lint_it.core import Finding, finding, normalized_filename

BOUNDARY_FILE_NAMES = (
    "__main__.py",
    "admin_router.py",
    "cli.py",
    "config.py",
    "dependency.py",
    "dependencies.py",
    "main.py",
    "main_cli.py",
    "migrations.py",
    "router.py",
)
BOUNDARY_PATH_PARTS = (
    "/cli/",
    "/migrations/",
    "/scripts/",
    "/sources/",
    "/tests/",
)
FASTAPI_DEFAULT_CALL_NAMES = frozenset(
    {
        "Body",
        "Cookie",
        "Depends",
        "File",
        "Form",
        "Header",
        "Path",
        "Query",
        "Security",
    }
)
FASTAPI_ROUTE_DECORATOR_NAMES = frozenset(
    {
        "api_route",
        "delete",
        "get",
        "head",
        "options",
        "patch",
        "post",
        "put",
        "route",
        "websocket",
    }
)


def _is_boundary_file(filename: str, architecture: Architecture | None) -> bool:
    classified = has_layer(
        filename,
        architecture,
        Layer.BOUNDARY,
        Layer.MIGRATION,
        Layer.TEST_SHELL,
        Layer.TRANSACTION_BOUNDARY,
    )
    if classified is not None:
        return classified
    normalized = normalized_filename(filename)
    if normalized.endswith(BOUNDARY_FILE_NAMES) or normalized.endswith(
        ("_test.py", "/api.py", "/imports.py")
    ):
        return True
    return any(part in f"/{normalized}" for part in BOUNDARY_PATH_PARTS)


def _defaults(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[ast.expr, ...]:
    keyword = tuple(value for value in node.args.kw_defaults if value is not None)
    return (*node.args.defaults, *keyword)


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Call):
        return _name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


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


class NoArgumentDefaultsRule:
    code = "PAL001"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        if _is_boundary_file(filename, architecture):
            return []
        visitor = _Visitor(self, filename)
        visitor.visit(tree)
        return visitor.findings


class _Visitor(ast.NodeVisitor):
    def __init__(self, rule: NoArgumentDefaultsRule, filename: str) -> None:
        self.rule = rule
        self.filename = filename
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
        defaults = _defaults(node)
        route = any(
            _name(decorator) in FASTAPI_ROUTE_DECORATOR_NAMES for decorator in node.decorator_list
        )
        fastapi_defaults = bool(defaults) and all(
            isinstance(value, ast.Call) and _name(value) in FASTAPI_DEFAULT_CALL_NAMES
            for value in defaults
        )
        exempt = (
            self.protocol_depth > 0
            or (self.exception_depth > 0 and node.name == "__init__")
            or route
            or fastapi_defaults
        )
        if any(not _immutable_default(default) for default in defaults) and not exempt:
            self.findings.append(
                finding(
                    self.rule,
                    self.filename,
                    node,
                    (
                        "core defaults must be immutable literals; construct mut"
                        "able values and observe effects in the shell"
                    ),
                )
            )
        self.generic_visit(node)
