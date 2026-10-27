from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.architecture import Architecture
from lint_it.core import Finding, finding, normalized_filename
from lint_it.rules.shared.symbols import UNKNOWN, resolved_symbols

FORBIDDEN_SUFFIXES = ("Repository", "Client", "Engine")
FORBIDDEN_FACTORIES = frozenset(
    {
        "create_async_engine",
        "create_engine",
        "load_settings",
    }
)


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


class RouterConstructionRule:
    code = "PAL006"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        normalized = normalized_filename(filename)
        if not (
            normalized.endswith(("/router.py", "_router.py"))
            or any(part in f"/{normalized}" for part in ("/app/router/", "/app/routers/"))
        ):
            return []

        findings: list[Finding] = []
        symbols = resolved_symbols(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            resolved = symbols.get(node.func, frozenset())
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
                        filename,
                        node,
                        f"routers cannot construct {', '.join(sorted(names))}",
                    )
                )
        return findings
