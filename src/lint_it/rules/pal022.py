from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.architecture import Architecture, Layer, has_layer
from lint_it.core import Finding, finding
from lint_it.rules.shared.effects import is_async_effect
from lint_it.rules.shared.functional_core import DECISION_MODULES, _is_domain_module
from lint_it.rules.shared.symbols import resolved_symbols


class SynchronousCoreRule:
    code = "PAL022"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        if has_layer(filename, architecture, Layer.PORT) or filename.endswith("/ports.py"):
            return []
        if not _is_domain_module(filename, architecture, DECISION_MODULES):
            return []
        findings = [
            finding(
                self,
                filename,
                node,
                "async execution belongs in the shell; the core computes decisions from values",
            )
            for node in ast.walk(tree)
            if isinstance(node, (ast.Await, ast.AsyncFor, ast.AsyncWith))
        ]
        findings.extend(
            finding(self, filename, node, "task and thread scheduling belongs in the shell")
            for node, names in resolved_symbols(tree).items()
            if isinstance(node, (ast.Name, ast.Attribute))
            and isinstance(node.ctx, ast.Load)
            and names
            and all(is_async_effect(name) for name in names)
        )
        return findings
