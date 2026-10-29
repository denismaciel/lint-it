from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
from functools import cache
from pathlib import Path

from lint_it.imports import absolute_module, package_name
from lint_it.workspace import Source

Edge = tuple[ast.Import | ast.ImportFrom, str, str | None]


def module_imports(tree: ast.Module, package: str | None) -> Iterable[Edge]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node, alias.name, None
        elif isinstance(node, ast.ImportFrom):
            base = absolute_module(node, package)
            if base is None:
                continue
            for alias in node.names:
                yield node, base, alias.name


@cache
def top_level_imports(tree: ast.Module, package: str | None) -> tuple[Edge, ...]:
    """Imports directly in the module body: the names the module re-exports."""
    body: list[ast.stmt] = [
        node for node in tree.body if isinstance(node, ast.Import | ast.ImportFrom)
    ]
    return tuple(module_imports(ast.Module(body=body, type_ignores=[]), package))


def _targets(
    module: str,
    name: str | None,
    modules: Mapping[str, Source],
    seen: frozenset[tuple[str, str | None]],
) -> tuple[Source, ...]:
    key = (module, name)
    if key in seen:
        return ()
    if name is not None and f"{module}.{name}" in modules:
        return (modules[f"{module}.{name}"],)
    source = modules.get(module)
    if source is None:
        return ()
    seen = seen | {key}
    # Follow explicit re-exports, including package __init__ modules.
    if name is not None:
        exports: list[Source] = []
        for node, imported, symbol in top_level_imports(
            source.tree, package_name(module, source.path)
        ):
            if not isinstance(node, ast.ImportFrom):
                continue
            if any(
                alias.name == symbol
                and ((alias.asname or alias.name) == name or name == "*" or alias.name == "*")
                for alias in node.names
            ):
                exports.extend(_targets(imported, symbol, modules, seen))
        if exports:
            return tuple(exports)
    return (source,)


@cache
def _initialization_imports(tree: ast.Module, package: str | None) -> tuple[Edge, ...]:
    """Imports in module/class control flow execute; function bodies are deferred."""
    imports: list[ast.stmt] = []
    pending: list[ast.AST] = list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(node)
        else:
            pending.extend(ast.iter_child_nodes(node))
    return tuple(module_imports(ast.Module(body=imports, type_ignores=[]), package))


def loaded_sources(
    module: str,
    name: str | None,
    modules: Mapping[str, Source],
    module_names: Mapping[Path, str],
) -> Iterable[Source]:
    """Follow initializer execution and its transitive imports from the snapshot."""
    pending = [(module, name, False)]
    seen_imports: set[tuple[str, str | None, bool]] = set()
    expanded: set[Path] = set()
    while pending:
        imported, symbol, transitive = pending.pop()
        if (imported, symbol, transitive) in seen_imports:
            continue
        seen_imports.add((imported, symbol, transitive))
        targets = _targets(imported, symbol, modules, frozenset())
        # Include the named module even when resolving a re-export skips it.
        names = [imported, *(module_names[item.path] for item in targets)]
        loaded: dict[Path, Source] = {item.path: item for item in targets}
        for loaded_name in names:
            parts = loaded_name.split(".")
            for length in range(1, len(parts) + 1):
                item = modules.get(".".join(parts[:length]))
                if item is not None and (length == len(parts) or item.path.name == "__init__.py"):
                    loaded[item.path] = item
        for item in loaded.values():
            yield item
            if item.path in expanded:
                continue
            # Only package initialization starts traversal. Modules reached from
            # an initializer also execute their own imports transitively.
            if item.path.name == "__init__.py" or transitive:
                expanded.add(item.path)
                pending.extend(
                    (base, member, True)
                    for _, base, member in _initialization_imports(
                        item.tree, package_name(module_names[item.path], item.path)
                    )
                )
