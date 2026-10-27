from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import PurePosixPath
from types import MappingProxyType

from lint_it.architecture import Architecture
from lint_it.core import Finding, finding, normalized_filename
from lint_it.imports import imported_modules

FORBIDDEN_BY_LAYER = MappingProxyType(
    {
        "router": frozenset({"model", "persistence"}),
        "service": frozenset({"router"}),
        "model": frozenset({"router", "service", "persistence"}),
        "ports": frozenset({"router", "service", "persistence"}),
        "core": frozenset({"router", "service", "persistence"}),
        "policy": frozenset({"router", "service", "persistence"}),
    }
)


class DomainImportRule:
    code = "PAL003"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        normalized = normalized_filename(filename)
        path = PurePosixPath(normalized)
        layer = path.stem
        is_domain = "/domains/" in f"/{normalized}"
        is_persistence = is_domain and "/persistence/" in f"/{normalized}"
        is_app_router = any(part in f"/{normalized}" for part in ("/app/router/", "/app/routers/"))
        if not is_domain and not is_app_router:
            return []

        forbidden: frozenset[str] | set[str] = FORBIDDEN_BY_LAYER.get(layer, frozenset())
        if is_persistence:
            layer = "persistence"
            forbidden = {"router", "service"}
        if is_app_router:
            forbidden = {"model", "persistence"}

        findings: list[Finding] = []
        for node, module in imported_modules(tree):
            relative = isinstance(node, ast.ImportFrom) and node.level > 0
            if not relative and ".domains." not in f".{module}.":
                continue
            imported_layer = module.rsplit(".", maxsplit=1)[-1]
            if imported_layer in forbidden:
                findings.append(
                    finding(
                        self,
                        filename,
                        node,
                        f"{layer} cannot import {module}",
                    )
                )
        return findings
