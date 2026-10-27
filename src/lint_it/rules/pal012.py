from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.architecture import Architecture
from lint_it.core import Finding, finding
from lint_it.imports import imported_modules
from lint_it.rules.shared.functional_core import (
    CORE_MODULES,
    _is_domain_module,
    _root_module,
)

VALIDATION_FRAMEWORKS = frozenset({"pydantic", "pydantic_settings"})


class BoundaryValidationRule:
    code = "PAL012"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        if not _is_domain_module(filename, architecture, CORE_MODULES):
            return []
        return [
            finding(
                self,
                filename,
                node,
                f"{_root_module(module)} belongs at a system boundary; "
                "map its validated data to domain types",
            )
            for node, module in imported_modules(tree)
            if _root_module(module) in VALIDATION_FRAMEWORKS
        ]
