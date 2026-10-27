from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
from pathlib import Path

from lint_it.architecture import Architecture, Layer, Source
from lint_it.core import Finding, finding
from lint_it.rules.shared.import_graph import _imports, _loaded_sources

VALIDATION_FRAMEWORKS = ("pydantic", "pydantic_settings")


def _framework_reexports(
    module: str,
    symbol: str | None,
    modules: Mapping[str, Source],
    seen: frozenset[tuple[str, str | None]],
) -> set[str]:
    key = (module, symbol)
    if key in seen:
        return set()
    root = module.split(".")[0]
    if root in VALIDATION_FRAMEWORKS:
        return {root}
    source = modules.get(module)
    if source is None or symbol is None:
        return set()
    dependencies: set[str] = set()
    for node, imported, member in _imports(source.tree, module, source.path.name == "__init__.py"):
        if node not in source.tree.body:
            continue
        if isinstance(node, ast.ImportFrom):
            exported = any(
                alias.name == member
                and ((alias.asname or alias.name) == symbol or alias.name == "*" or symbol == "*")
                for alias in node.names
            )
        elif isinstance(node, ast.Import):
            exported = any(
                alias.name == imported and (alias.asname or alias.name.split(".")[0]) == symbol
                for alias in node.names
            )
        else:
            exported = False
        if exported:
            dependencies.update(_framework_reexports(imported, member, modules, seen | {key}))
    return dependencies


class ServiceBoundaryDependencyRule:
    code = "PAL024"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        path = Path(filename)
        if (
            architecture is None
            or "domains" not in path.parts
            or not (path.name == "service.py" or path.name.endswith("_service.py"))
        ):
            return []
        classification = architecture.classify(path)
        if classification is None or classification.layer is not Layer.IMPERATIVE_SHELL:
            return []
        module = architecture.module_name(path)
        if module is None:
            return []
        modules = architecture.index.modules
        findings: list[Finding] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Import | ast.ImportFrom):
                continue
            dependencies: set[str] = set()
            statement = ast.Module(body=[node], type_ignores=[])
            for _, imported, symbol in _imports(statement, module, False):
                dependencies.update(_framework_reexports(imported, symbol, modules, frozenset()))
                for target in _loaded_sources(
                    imported, symbol, modules, architecture.index.module_names
                ):
                    target_layer = architecture.classify(target.path)
                    if target_layer is not None and target_layer.layer is Layer.BOUNDARY:
                        dependencies.add(
                            architecture.module_name(target.path)
                            or target.path.relative_to(architecture.root).as_posix()
                        )
            if dependencies:
                findings.append(
                    finding(
                        self,
                        filename,
                        node,
                        "services cannot import boundary/framework dependencies: "
                        + ", ".join(sorted(dependencies)),
                    )
                )
        return findings
