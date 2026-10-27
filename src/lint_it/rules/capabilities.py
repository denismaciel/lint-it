from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
from copy import deepcopy

from lint_it.core import Finding, SourceFile, finding
from lint_it.policy import Layer
from lint_it.symbols import resolved_symbols

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


def _annotation_nodes(
    node: ast.AST, symbols: Mapping[ast.expr, frozenset[str]]
) -> Iterable[ast.expr]:
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
    """A core function takes a parameter that can perform effects.

    Database sessions and connections, HTTP clients, file objects and
    filesystems are capabilities: a function that receives one can do I/O even
    when it imports nothing. Types are matched by exact resolved name, through
    aliases, unions, `Optional`, `Annotated` and string annotations. Add your own
    with `workspace.effectful_types`. Ports are exempt because they describe
    effectful collaborators.
    """

    code = "LIT207"
    name = "effectful-capability"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        if not file.has_layer(Layer.CORE):
            return []
        # Normalize forward annotations on a private tree; snapshot ASTs stay untouched.
        tree = deepcopy(file.tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.arg) and node.annotation is not None:
                node.annotation = _AnnotationStrings().visit(node.annotation)
        symbols = resolved_symbols(tree, file.package)
        known = EFFECTFUL_TYPES | file.workspace.policy.effectful_types
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
                        file,
                        node,
                        f"core parameter '{node.arg}' receives effectful capability "
                        f"{', '.join(sorted(matches))}; "
                        "pass observed values and execute returned decisions in the shell",
                    )
                )
        return findings
