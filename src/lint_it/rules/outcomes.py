from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.core import Finding, SourceFile, finding
from lint_it.policy import Layer


def _exception_names(node: ast.expr | None) -> tuple[str, ...]:
    if node is None:
        return ()
    if isinstance(node, ast.Tuple):
        return tuple(name for item in node.elts for name in _exception_names(item))
    if isinstance(node, ast.Call):
        return _exception_names(node.func)
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        return (node.attr,)
    return ()


class ExpectedOutcomeRule:
    """Core code raises or catches an expected outcome.

    "Not found", "denied" or "expired" are ordinary results of a decision, not
    failures. Exceptions whose names end with a suffix from
    `conventions.outcome_suffixes` (default `NotFound`, `AlreadyExists`,
    `Conflict`, `Denied`, `Expired`, `Forbidden`, `Rejected`, `Unauthorized`,
    `Unavailable`) may not be raised or caught in core modules; return a named
    result type instead.
    """

    code = "LIT402"
    name = "expected-outcome"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        if not file.has_layer(Layer.CORE):
            return []
        suffixes = file.workspace.policy.outcome_suffixes
        findings: list[Finding] = []
        for node in ast.walk(file.tree):
            if isinstance(node, ast.Raise):
                names = _exception_names(node.exc)
                message = "expected outcomes must be returned as named results, not raised"
            elif isinstance(node, ast.ExceptHandler):
                names = _exception_names(node.type)
                message = "expected outcomes must be matched as named results, not caught"
            else:
                continue
            if any(name.endswith(suffixes) for name in names):
                findings.append(finding(self, file, node, message))
        return findings
