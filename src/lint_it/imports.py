from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import PurePath


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


def package_name(module: str, path: PurePath) -> str:
    """The package that relative imports inside ``module`` resolve against."""
    return module if path.name == "__init__.py" else module.rpartition(".")[0]


def absolute_module(node: ast.ImportFrom, package: str | None) -> str | None:
    """Absolute target of a ``from`` import, or None when it cannot be resolved."""
    if not node.level:
        return node.module
    if package is None:
        return None
    parts = package.split(".") if package else []
    if node.level > len(parts):
        return None
    prefix = parts[: len(parts) - node.level + 1]
    return ".".join((*prefix, *((node.module,) if node.module else ())))
