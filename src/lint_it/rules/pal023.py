from __future__ import annotations

import ast
from collections.abc import Iterable
from copy import deepcopy
from pathlib import Path

from lint_it.architecture import Architecture, Layer, has_layer
from lint_it.core import Finding, finding
from lint_it.rules.shared.functional_core import DECISION_MODULES, _is_domain_module
from lint_it.rules.shared.symbols import resolved_symbols

# Exact public type identities, never suffix or parameter-name heuristics.
EFFECTFUL_TYPES = frozenset(
    {
        "sqlalchemy.orm.Session",
        "sqlalchemy.orm.session.Session",
        "sqlalchemy.ext.asyncio.AsyncSession",
        "sqlalchemy.ext.asyncio.session.AsyncSession",
        "sqlalchemy.engine.Connection",
        "sqlalchemy.engine.Engine",
        "sqlite3.Connection",
        "sqlite3.Cursor",
        "psycopg.Connection",
        "psycopg.AsyncConnection",
        "httpx.Client",
        "httpx.AsyncClient",
        "requests.Session",
        "requests.sessions.Session",
        "aiohttp.ClientSession",
        "aiohttp.client.ClientSession",
        "io.IOBase",
        "io.RawIOBase",
        "io.BufferedIOBase",
        "io.TextIOBase",
        "io.TextIOWrapper",
        "typing.IO",
        "typing.TextIO",
        "typing.BinaryIO",
        "fsspec.AbstractFileSystem",
        "fsspec.spec.AbstractFileSystem",
    }
)


class _AnnotationStrings(ast.NodeTransformer):
    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if isinstance(node.value, str):
            try:
                parsed = ast.parse(node.value, mode="eval").body
            except SyntaxError:
                return node
            # Avoid recursion on quoted string literals.
            if not isinstance(parsed, ast.Constant):
                rewritten = self.visit(parsed)
                if isinstance(rewritten, ast.AST):
                    return ast.copy_location(rewritten, node)
        return node


def _annotation_nodes(node: ast.AST, symbols: dict[ast.expr, frozenset[str]]) -> Iterable[ast.expr]:
    if isinstance(node, ast.expr):
        yield node
    if isinstance(node, ast.Subscript):
        names = symbols.get(node.value, frozenset())
        if names & {"typing.Literal", "typing_extensions.Literal"}:
            return
        if names & {"typing.Annotated", "typing_extensions.Annotated"}:
            first = node.slice.elts[0] if isinstance(node.slice, ast.Tuple) else node.slice
            yield from _annotation_nodes(first, symbols)
            return
    for child in ast.iter_child_nodes(node):
        yield from _annotation_nodes(child, symbols)


class EffectfulCapabilityRule:
    code = "PAL023"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        if has_layer(filename, architecture, Layer.PORT) or filename.endswith("/ports.py"):
            return []
        if not _is_domain_module(filename, architecture, DECISION_MODULES | {"model.py"}):
            return []
        # Normalize forward annotations on a private tree; snapshot ASTs stay untouched.
        tree = deepcopy(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.arg) and node.annotation is not None:
                node.annotation = _AnnotationStrings().visit(node.annotation)
            if isinstance(node, ast.ImportFrom) and node.level and architecture is not None:
                path = Path(filename)
                package = architecture.package_for(path)
                if package is not None and path.is_relative_to(package.root / "src"):
                    parts = path.relative_to(package.root / "src").parent.parts
                    if node.level <= len(parts):
                        prefix = parts[: len(parts) - node.level + 1]
                        node.module = ".".join((*prefix, *((node.module,) if node.module else ())))
                        node.level = 0
        symbols = resolved_symbols(tree)
        known = EFFECTFUL_TYPES | (architecture.effectful_types if architecture else frozenset())
        findings: list[Finding] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.arg) or node.annotation is None:
                continue
            matches = {
                name
                for part in _annotation_nodes(node.annotation, symbols)
                if (names := symbols.get(part, frozenset())) and names <= known
                for name in names
            }
            if matches:
                findings.append(
                    finding(
                        self,
                        filename,
                        node,
                        f"core parameter '{node.arg}' receives effectful capability "
                        f"{', '.join(sorted(matches))}; "
                        "pass observed values and execute returned decisions in the shell",
                    )
                )
        return findings
