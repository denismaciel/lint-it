from __future__ import annotations

from collections.abc import Iterable

from lint_it.core import Finding, SourceFile, finding
from lint_it.imports import imported_modules
from lint_it.workspace import Kind


class ClientImportRule:
    """A client package imports a server package from the same workspace.

    Packages with `kind = "client"` (SDKs, wire contracts) ship to consumers that
    do not have the server installed. They may import libraries and other
    clients, never modules owned by a `kind = "server"` package.
    """

    code = "LIT103"
    name = "client-imports-server"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        package = file.workspace.package_for(file.path)
        if package is None or package.kind is not Kind.CLIENT:
            return []
        server_modules = file.workspace.index.server_modules
        return [
            finding(self, file, node, f"client packages cannot import server module {module}")
            for node, module in imported_modules(file.tree)
            if module.split(".")[0] in server_modules
        ]
