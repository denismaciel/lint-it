from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.core import Finding, SourceFile, finding
from lint_it.policy import Layer
from lint_it.symbols import UNKNOWN

FORBIDDEN_SUFFIXES = ("Repository", "Client", "Engine")
FORBIDDEN_FACTORIES = frozenset({"create_async_engine", "create_engine", "load_settings"})


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


class RouterConstructionRule:
    """A router constructs its own infrastructure.

    Routers receive repositories, clients, engines and settings through
    dependency injection; they never build them. Calls to anything named
    `*Repository`, `*Client` or `*Engine`, `create_engine`,
    `create_async_engine` or `load_settings` are reported, matched by resolved
    name when the import is known.
    """

    code = "LIT303"
    name = "router-construction"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        if not file.has_layer(Layer.ROUTER):
            return []
        findings: list[Finding] = []
        for node in ast.walk(file.tree):
            if not isinstance(node, ast.Call):
                continue
            resolved = file.symbols.get(node.func, frozenset())
            names = {name.rsplit(".", maxsplit=1)[-1] for name in resolved}
            if not names or resolved == UNKNOWN:
                call_name = _call_name(node)
                names = {call_name} if call_name is not None else set()
            if names and all(
                name.endswith(FORBIDDEN_SUFFIXES) or name in FORBIDDEN_FACTORIES for name in names
            ):
                findings.append(
                    finding(
                        self,
                        file,
                        node,
                        f"routers cannot construct {', '.join(sorted(names))}",
                        target=", ".join(sorted(names)),
                    )
                )
        return findings
