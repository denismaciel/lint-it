from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.architecture import Architecture, Layer, has_layer
from lint_it.core import Finding, finding, normalized_filename
from lint_it.imports import imported_modules


class NoDomainFastApiRule:
    code = "PAL007"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        classified = has_layer(filename, architecture, Layer.FUNCTIONAL_CORE, Layer.PORT)
        if classified is False or (
            classified is None and "/domains/" not in f"/{normalized_filename(filename)}"
        ):
            return []
        return [
            finding(self, filename, node, "domain modules cannot import FastAPI")
            for node, module in imported_modules(tree)
            if module == "fastapi" or module.startswith("fastapi.")
        ]
