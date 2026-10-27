from __future__ import annotations

from collections.abc import Iterable

from lint_it.core import Finding, SourceFile, finding, loaded_names
from lint_it.policy import INNER_LAYERS
from lint_it.rules.shared.effects import is_io


class IoCallRule:
    """Core or port code performs I/O.

    Covers files and paths (`open`, `Path.read_text`, `shutil`, `tempfile`),
    processes and the OS (`os.system`, `sys.exit`), standard streams, logging,
    `print`/`input`, and any call into an I/O client package. Do the I/O in the
    shell and pass the result into the core.
    """

    code = "LIT202"
    name = "io-in-core"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        if not file.has_layer(*INNER_LAYERS):
            return []
        return [
            finding(
                self,
                file,
                node,
                f"{', '.join(sorted(names))} performs I/O; pass its result into the core",
            )
            for node, names in loaded_names(file)
            if all(is_io(name) for name in names)
        ]
