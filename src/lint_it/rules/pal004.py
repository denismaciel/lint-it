from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.architecture import Architecture, Layer, has_layer
from lint_it.core import Finding, finding, normalized_filename
from lint_it.rules.shared.symbols import resolved_symbols


def _is_allowed(filename: str, architecture: Architecture | None) -> bool:
    classified = has_layer(
        filename, architecture, Layer.BOUNDARY, Layer.MIGRATION, Layer.TEST_SHELL
    )
    if classified is not None:
        return classified
    normalized = normalized_filename(filename)
    return normalized.endswith("/config.py") or "/scripts/" in f"/{normalized}"


class EnvironmentAccessRule:
    code = "PAL004"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        if _is_allowed(filename, architecture):
            return []
        return [
            finding(
                self,
                filename,
                node,
                "environment access is only allowed at configured system boundaries",
            )
            for node, names in resolved_symbols(tree).items()
            if isinstance(node, (ast.Name, ast.Attribute))
            and isinstance(node.ctx, ast.Load)
            and names
            and names <= {"os.environ", "os.environb", "os.getenv", "os.getenvb"}
        ]
