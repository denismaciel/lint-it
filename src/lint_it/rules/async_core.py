from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.core import Finding, SourceFile, finding, loaded_names
from lint_it.policy import Layer
from lint_it.rules.shared.effects import is_async_effect


class AsyncCoreRule:
    """Core code awaits or schedules concurrent work.

    `await`, `async for`, `async with`, `asyncio` scheduling, threads and process
    pools belong in the shell. The core computes a decision from values; the
    shell decides when and how concurrently to carry it out.
    """

    code = "LIT206"
    name = "async-in-core"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        if not file.has_layer(Layer.CORE):
            return []
        findings = [
            finding(
                self,
                file,
                node,
                "async execution belongs in the shell; the core computes decisions from values",
            )
            for node in ast.walk(file.tree)
            if isinstance(node, (ast.Await, ast.AsyncFor, ast.AsyncWith))
        ]
        findings.extend(
            finding(self, file, node, "task and thread scheduling belongs in the shell")
            for node, names in loaded_names(file)
            if all(is_async_effect(name) for name in names)
        )
        return findings
