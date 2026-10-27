from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from lint_it.architecture import Architecture, Layer
from lint_it.core import Finding, finding
from lint_it.rules.shared.import_graph import _imports, _loaded_sources

_INWARD_LAYERS = frozenset({Layer.FUNCTIONAL_CORE, Layer.PORT})


class LayerDependencyRule:
    code = "PAL017"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        if architecture is None:
            return []
        importer = Path(filename)
        source = architecture.classify(importer)
        if source is None or source.layer not in _INWARD_LAYERS:
            return []
        modules = architecture.index.modules
        module = architecture.module_name(importer)
        if module is None:
            return []
        findings: list[Finding] = []
        seen: set[Path] = set()
        for node, imported, symbol in _imports(tree, module, importer.name == "__init__.py"):
            for target_source in _loaded_sources(
                imported, symbol, modules, architecture.index.module_names
            ):
                target = architecture.classify(target_source.path)
                if (
                    target is None
                    or target_source.path in seen
                    or target.layer in _INWARD_LAYERS
                    or target.layer is Layer.PACKAGE_MARKER
                ):
                    continue
                if architecture.dependency_override_for(importer, target_source.path) is not None:
                    continue
                seen.add(target_source.path)
                findings.append(
                    finding(
                        self,
                        filename,
                        node,
                        f"{source.layer.value} cannot import {target.layer.value} module "
                        f"{target_source.path.relative_to(target.package.root)}",
                    )
                )
        return findings
