from __future__ import annotations

from collections.abc import Iterable

from lint_it.core import Finding, SourceFile, finding, loaded_names
from lint_it.policy import INNER_LAYERS, Layer
from lint_it.rules.shared.effects import WALL_CLOCK, is_nondeterministic


class NondeterminismRule:
    """Code reads the clock, randomness, or fresh IDs directly.

    Core and port modules may not read any nondeterministic source (`time`,
    `datetime.now`, `uuid4`, `random`, `secrets`, `os.urandom`); pass the
    observed value in. Elsewhere only wall-clock reads are reported, so time
    flows through one clock you can control in tests. List that clock's modules
    in `workspace.clock_modules`; test modules are exempt. A custom layer with
    `deterministic = true`, such as Temporal workflow code, is held to the core
    standard.
    """

    code = "LIT201"
    name = "nondeterminism"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        inner = file.has_layer(*INNER_LAYERS) or file.is_deterministic
        if not inner and (
            file.layer in (None, Layer.TEST) or file.module in file.workspace.policy.clock_modules
        ):
            return []
        return [
            finding(
                self,
                file,
                node,
                f"{', '.join(sorted(names))} hides nondeterminism; "
                f"{file.layer_name} modules must be deterministic"
                if file.is_deterministic
                else f"{', '.join(sorted(names))} hides nondeterminism; "
                "pass the observed time, ID, or random value into the core"
                if inner
                else f"{', '.join(sorted(names))} reads wall time directly; "
                "use the clock listed in workspace.clock_modules",
                target=", ".join(sorted(names)),
            )
            for node, names in loaded_names(file)
            if all(is_nondeterministic(name) if inner else name in WALL_CLOCK for name in names)
        ]
