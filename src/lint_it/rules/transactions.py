from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.core import Finding, SourceFile, finding
from lint_it.policy import TRANSACTION_PACKAGES, Layer
from lint_it.symbols import UNKNOWN


class TransactionBoundaryRule:
    """Code outside a transaction boundary calls `commit()` or `rollback()`.

    One place per request or job decides when work is durable. Any method named
    `commit` or `rollback` counts, unless its receiver resolves only to a
    third-party package outside the database drivers and ORMs (`sqlalchemy`,
    `asyncpg`, `psycopg`, `sqlite3`, ...), such as a search index writer. Only
    transaction and test modules may call them.
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
            and not _non_transactional(file, node.func.value)
        ]


def _non_transactional(file: SourceFile, receiver: ast.expr) -> bool:
    names = file.symbols.get(receiver, UNKNOWN)
    if not names or "?" in names:
        return False
    modules = file.workspace.index.modules
    for name in names:
        root = name.split(".", 1)[0]
        if root in TRANSACTION_PACKAGES or any(
            module == root or module.startswith(f"{root}.") for module in modules
        ):
            return False
    return True
