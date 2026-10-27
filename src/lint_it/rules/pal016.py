from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.architecture import Architecture, classification_for
from lint_it.core import Finding, finding


class ClassificationRule:
    code = "PAL016"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        if architecture is None or classification_for(filename, architecture) is not None:
            return []
        return [
            finding(
                self,
                filename,
                tree,
                "Python file has no canonical or overridden package/layer classification",
            )
        ]
