from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.core import Finding, SourceFile, finding
from lint_it.policy import matches_name
from lint_it.symbols import UNKNOWN


class ForbiddenCallRule:
    """A module calls a function its layer may not call.

    Nothing is forbidden by default. List qualified names per layer in
    `[forbidden_calls]`, with a trailing `.*` for a whole module: for example
    `time.sleep` and `asyncio.sleep` in Temporal workflow code, which must use
    the workflow's own timer. Calls are matched by resolved name, so aliases
    and `from` imports count. A custom layer inherits its base layer's list
    unless it has its own.
    """

    code = "LIT306"
    name = "forbidden-call"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        layer = file.layer_name
        forbidden = file.workspace.policy.forbidden_calls.get(layer) if layer else None
        if not forbidden:
            return []
        findings: list[Finding] = []
        for node in ast.walk(file.tree):
            if not isinstance(node, ast.Call):
                continue
            names = file.symbols.get(node.func, frozenset())
            if names == UNKNOWN:
                continue
            matched = sorted(name for name in names if matches_name(name, forbidden))
            if matched:
                findings.append(
                    finding(
                        self,
                        file,
                        node,
                        f"{layer} modules cannot call {', '.join(matched)}",
                        target=", ".join(matched),
                    )
                )
        return findings
