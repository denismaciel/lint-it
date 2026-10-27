from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.architecture import Architecture, Layer, has_layer
from lint_it.core import Finding, finding, is_test_file, normalized_filename
from lint_it.imports import imported_modules
from lint_it.rules.shared.persistence_boundaries import (
    _domain_module_parts,
    _is_persistence_module,
)


class DomainPersistenceImportRule:
    """Prevent business modules and HTTP routers from importing adapters."""

    code = "PAL010"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        if has_layer(filename, architecture, Layer.TEST_SHELL) or is_test_file(filename):
            return []
        normalized = normalized_filename(filename)
        is_domain_business_module = _domain_module_parts(
            filename
        ) is not None and not _is_persistence_module(filename)
        is_app_router = any(part in f"/{normalized}" for part in ("/app/router/", "/app/routers/"))
        if not is_domain_business_module and not is_app_router:
            return []

        return [
            finding(
                self,
                filename,
                node,
                "business modules and routers cannot import persistence adapters",
            )
            for node, module in imported_modules(tree)
            if _imports_persistence(node, module)
        ]


def _imports_persistence(node: ast.Import | ast.ImportFrom, module: str) -> bool:
    if isinstance(node, ast.ImportFrom) and node.level > 0:
        return module == "persistence" or module.startswith("persistence.")
    return ".persistence." in f".{module}." or module.endswith(".persistence")
