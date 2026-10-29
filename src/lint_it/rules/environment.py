from __future__ import annotations

from collections.abc import Iterable

from lint_it.core import Finding, SourceFile, finding, loaded_names
from lint_it.policy import Layer
from lint_it.rules.shared.effects import is_environment

ENVIRONMENT_LAYERS = (Layer.BOUNDARY, Layer.TRANSACTION, Layer.TEST)


class EnvironmentAccessRule:
    """Code outside the edges reads environment variables.

    `os.environ`, `os.getenv` and their bytes variants, through any alias, are
    allowed only in boundary, transaction and test modules. Read configuration
    once at startup and pass typed values inward.
    """

    code = "LIT301"
    name = "environment-access"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        if file.layer is None or file.has_layer(*ENVIRONMENT_LAYERS):
            return []
        return [
            finding(
                self,
                file,
                node,
                f"{file.layer_name} modules cannot read the environment; "
                "read configuration at a boundary and pass it in",
            )
            for node, names in loaded_names(file)
            if all(is_environment(name) for name in names)
        ]
