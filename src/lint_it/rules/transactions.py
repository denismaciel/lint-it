from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.core import Finding, SourceFile, finding
from lint_it.policy import Layer


class TransactionBoundaryRule:
    """Code outside a transaction boundary calls `commit()` or `rollback()`.

    One place per request or job decides when work is durable. Any method named
    `commit` or `rollback` counts, on any receiver; only transaction and test
    modules may call them.
    """

    code = "LIT302"
    name = "transaction-boundary"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        if file.layer is None or file.has_layer(Layer.TRANSACTION, Layer.TEST):
            return []
        return [
            finding(
                self, file, node, f"{node.func.attr}() is only allowed at transaction boundaries"
            )
            for node in ast.walk(file.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"commit", "rollback"}
        ]
