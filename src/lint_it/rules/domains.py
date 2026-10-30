from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from lint_it.core import Finding, SourceFile, finding
from lint_it.policy import Layer, domain_of
from lint_it.rules.shared.import_graph import loaded_sources, module_imports

PUBLIC_LAYERS = frozenset({Layer.CORE, Layer.SHELL})


class DomainDependencyRule:
    """A domain imports another domain it does not declare, or that domain's internals.

    A module under `<package>/domains/<name>/` belongs to domain `<name>`. It may
    import another domain only when `[domains]` lists that domain among its
    dependencies, and then only its core and shell modules (`core.py`,
    `model.py`, `service.py`, ...); ports, adapters such as `persistence/`, and
    boundaries stay private to their domain. Undeclared imports always fail,
    so a workspace without `[domains]` keeps its domains independent. The
    graph is checked when the manifest loads: every domain a dependency names
    needs its own entry, and a cycle is a manifest error. `shared/`,
    `projections/` and everything outside `domains/` are not domains. Imports
    are followed through package `__init__` modules and re-exports, as for
    LIT101, and `[[dependency_overrides]]` exempts one deliberate edge.
    """

    code = "LIT104"
    name = "cross-domain-import"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        owner = None if file.module is None else domain_of(file.module)
        if owner is None:
            return []
        workspace = file.workspace
        policy, index = workspace.policy, workspace.index
        declared = policy.domain_dependencies.get(owner[1], frozenset())
        findings: list[Finding] = []
        seen: set[Path] = set()
        for node, imported, symbol in module_imports(file.tree, file.package):
            for target in loaded_sources(imported, symbol, index.modules, index.module_names):
                module = index.module_names.get(target.path)
                target_owner = None if module is None else domain_of(module)
                classification = workspace.classify(target.path)
                if (
                    module is None
                    or target_owner is None
                    or target_owner[0] != owner[0]
                    or target_owner == owner
                    or target.path in seen
                    or (classification is not None and classification.layer is Layer.MARKER)
                    or workspace.dependency_override_for(file.path, target.path) is not None
                ):
                    continue
                domain = target_owner[1]
                if domain not in declared:
                    message = (
                        f"{owner[1]} domain cannot import {module}: "
                        f"{domain} is not in domains.{owner[1]}"
                    )
                elif classification is None or not policy.is_a(classification.name, PUBLIC_LAYERS):
                    message = (
                        f"{owner[1]} domain cannot import {module}: only the core and shell "
                        f"modules of {domain} are public"
                    )
                else:
                    continue
                seen.add(target.path)
                findings.append(finding(self, file, node, message, target=module))
        return findings
