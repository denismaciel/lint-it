from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.architecture import Architecture
from lint_it.core import Finding, finding
from lint_it.imports import imported_modules
from lint_it.rules.shared.effects import IO_MODULES, is_io
from lint_it.rules.shared.functional_core import CORE_MODULES, _is_domain_module, _root_module
from lint_it.rules.shared.symbols import resolved_symbols


class ImperativeShellRule:
    code = "PAL014"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        if not _is_domain_module(filename, architecture, CORE_MODULES):
            return []
        findings = [
            finding(
                self,
                filename,
                node,
                f"{_root_module(module)} is infrastructure; "
                "perform I/O in the shell and pass values into the core",
            )
            for node, module in imported_modules(tree)
            if _root_module(module) in IO_MODULES
        ]
        findings.extend(
            finding(
                self,
                filename,
                node,
                f"{', '.join(sorted(names))} performs I/O; pass its result into the core",
            )
            for node, names in resolved_symbols(tree).items()
            if isinstance(node, (ast.Name, ast.Attribute))
            and isinstance(node.ctx, ast.Load)
            and names
            and all(is_io(name) for name in names)
        )
        return findings
