from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
from pathlib import Path

from lint_it.architecture import Source


def _imports(
    tree: ast.Module, module: str, is_package: bool
) -> Iterable[tuple[ast.AST, str, str | None]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node, alias.name, None
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parent = module.split(".") if is_package else module.split(".")[:-1]
                if node.level > len(parent):
                    continue
                prefix = parent[: len(parent) - node.level + 1]
                base = ".".join([*prefix, *base.split(".")]) if base else ".".join(prefix)
            for alias in node.names:
                yield node, base, alias.name


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
        for node, imported, symbol in _imports(
            source.tree, module, source.path.name == "__init__.py"
        ):
            if not isinstance(node, ast.ImportFrom) or node not in source.tree.body:
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


def _initialization_imports(tree: ast.Module) -> ast.Module:
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
    return ast.Module(body=imports, type_ignores=[])


def _loaded_sources(
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
                item_module = module_names[item.path]
                pending.extend(
                    (base, member, True)
                    for _, base, member in _imports(
                        _initialization_imports(item.tree),
                        item_module,
                        item.path.name == "__init__.py",
                    )
                )
