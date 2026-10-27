from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping

from lint_it.core import Finding, SourceFile, finding
from lint_it.imports import package_name
from lint_it.rules.shared.import_graph import module_imports
from lint_it.workspace import Source


def _reexported(
    module: str,
    symbol: str | None,
    modules: Mapping[str, Source],
    forbidden: frozenset[str],
    seen: frozenset[tuple[str, str | None]],
) -> set[str]:
    """Forbidden top-level packages reachable by importing ``symbol`` from ``module``."""
    key = (module, symbol)
    if key in seen:
        return set()
    root = module.split(".")[0]
    if root in forbidden:
        return {root}
    source = modules.get(module)
    if source is None or symbol is None:
        return set()
    reached: set[str] = set()
    for node, imported, member in module_imports(source.tree, package_name(module, source.path)):
        if node not in source.tree.body:
            continue
        if isinstance(node, ast.ImportFrom):
            exported = any(
                alias.name == member
                and ((alias.asname or alias.name) == symbol or "*" in (alias.name, symbol))
                for alias in node.names
            )
        elif isinstance(node, ast.Import):
            exported = any(
                alias.name == imported and (alias.asname or alias.name.split(".")[0]) == symbol
                for alias in node.names
            )
        else:
            continue
        if exported:
            reached |= _reexported(imported, member, modules, forbidden, seen | {key})
    return reached


class ForbiddenImportRule:
    """A module imports a third-party package its layer may not use.

    By default core and port modules may not import I/O clients (`httpx`,
    `requests`, `redis`, `sqlite3`, `subprocess`, ...) or frameworks (`fastapi`,
    `starlette`, `sqlalchemy`, `pydantic`, `pydantic_settings`); shell modules
    may not import frameworks; routers may not import `sqlalchemy`. Set
    `[forbidden_imports]` to change the lists. Every import statement counts,
    including deferred and `TYPE_CHECKING` ones, and a workspace module that
    re-exports a forbidden name is treated as that package.
    """

    code = "LIT102"
    name = "forbidden-import"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        layer = file.layer
        forbidden = file.workspace.policy.forbidden_imports.get(layer) if layer else None
        if not forbidden:
            return []
        modules = file.workspace.index.modules
        findings: list[Finding] = []
        for node in ast.walk(file.tree):
            if not isinstance(node, ast.Import | ast.ImportFrom):
                continue
            statement = ast.Module(body=[node], type_ignores=[])
            reached = {
                package
                for _, imported, symbol in module_imports(statement, file.package)
                for package in _reexported(imported, symbol, modules, forbidden, frozenset())
            }
            if reached:
                findings.append(
                    finding(
                        self,
                        file,
                        node,
                        f"{layer} modules cannot import {', '.join(sorted(reached))}",
                    )
                )
        return findings
