from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.architecture import Architecture, PackageRole, classification_for
from lint_it.core import Finding, finding, normalized_filename
from lint_it.imports import imported_modules

SERVER_MODULES = ("ariadne", "finance_api", "api")
BOUNDARY_PACKAGE_SUFFIXES = ("-contracts", "-sdk", "_contracts", "_sdk")


class NoServerImportsRule:
    code = "PAL008"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        classification = classification_for(filename, architecture)
        if classification is not None:
            if classification.package.role not in {PackageRole.CONTRACTS, PackageRole.SDK}:
                return []
        else:
            normalized = f"/{normalized_filename(filename)}"
            parts = normalized.split("/")
            try:
                package_name = parts[parts.index("packages") + 1]
            except ValueError, IndexError:
                return []
            if not package_name.endswith(BOUNDARY_PACKAGE_SUFFIXES):
                return []
        server_modules = set(SERVER_MODULES)
        if architecture is not None:
            server_modules.update(
                name.split(".")[0]
                for name, source in architecture.index.modules.items()
                if (package := architecture.package_for(source.path)) is not None
                and package.role in {PackageRole.APPLICATION, PackageRole.HEXAGONAL_APPLICATION}
            )
        return [
            finding(
                self,
                filename,
                node,
                f"contracts and SDK packages cannot import server module {module}",
            )
            for node, module in imported_modules(tree)
            if any(module == root or module.startswith(f"{root}.") for root in server_modules)
        ]
