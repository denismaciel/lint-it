from __future__ import annotations

import ast
from collections.abc import Iterator


def imported_modules(
    tree: ast.Module,
) -> Iterator[tuple[ast.Import | ast.ImportFrom, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                yield node, node.module
            else:
                for alias in node.names:
                    yield node, alias.name
