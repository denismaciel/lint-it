from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.architecture import Architecture, Layer, has_layer
from lint_it.core import Finding, finding, is_test_file, normalized_filename


def _is_boundary(filename: str, architecture: Architecture | None) -> bool:
    classified = has_layer(
        filename,
        architecture,
        Layer.MIGRATION,
        Layer.TEST_SHELL,
        Layer.TRANSACTION_BOUNDARY,
    )
    if classified is not None:
        return classified
    normalized = normalized_filename(filename)
    return (
        is_test_file(normalized)
        or normalized.endswith("/app/dependencies.py")
        or "/unit_of_work/" in f"/{normalized}"
        or normalized.endswith("/unit_of_work.py")
        or "/migrations/" in f"/{normalized}"
        or "/scripts/" in f"/{normalized}"
    )


class TransactionBoundaryRule:
    code = "PAL005"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        if _is_boundary(filename, architecture):
            return []
        return [
            finding(
                self,
                filename,
                node,
                f"{node.func.attr}() is only allowed at transaction boundaries",
            )
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"commit", "rollback"}
        ]
