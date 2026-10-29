from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from lint_it.core import Finding, SourceFile, finding
from lint_it.policy import Layer
from lint_it.rules.shared.import_graph import loaded_sources, module_imports


class LayerDependencyRule:
    """A module imports a layer its own layer may not depend on.

    The allowed targets per layer come from `[layer_dependencies]`; by default
    core and port import only core and port, shell adds shell, adapter adds
    adapter, and routers import shell, boundary, router and transaction modules.
    Other layers are unrestricted. A custom layer uses its base layer's entry
    unless it has its own, and counts as its base layer when imported. Imports
    are followed through package `__init__` modules and re-exports, so a package
    initializer cannot launder a forbidden dependency. Each forbidden module is
    reported once per importer. Declare modules a layer may always use with
    `[[allowed_dependencies]]`, or record one deliberate edge with
    `[[dependency_overrides]]`.
    """

    code = "LIT101"
    name = "layer-dependency"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        workspace, layer = file.workspace, file.layer_name
        policy = workspace.policy
        allowed = policy.layer_dependencies.get(layer) if layer else None
        if layer is None or allowed is None or file.package is None:
            return []
        index = workspace.index
        findings: list[Finding] = []
        seen: set[Path] = set()
        for node, imported, symbol in module_imports(file.tree, file.package):
            for target in loaded_sources(imported, symbol, index.modules, index.module_names):
                classification = workspace.classify(target.path)
                module = index.module_names.get(target.path, target.path.name)
                if (
                    classification is None
                    or target.path in seen
                    or target.path == file.path
                    or policy.is_a(classification.name, allowed)
                    or classification.layer is Layer.MARKER
                    or policy.allows_dependency(layer, module)
                    or workspace.dependency_override_for(file.path, target.path) is not None
                ):
                    continue
                seen.add(target.path)
                findings.append(
                    finding(
                        self,
                        file,
                        node,
                        f"{layer} cannot import {classification.name} module {module}",
                        target=module,
                    )
                )
        return findings
