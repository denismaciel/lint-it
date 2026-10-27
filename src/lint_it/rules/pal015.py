from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.architecture import Architecture
from lint_it.core import Finding, finding
from lint_it.rules.shared.functional_core import DECISION_MODULES, _is_domain_module

EXPECTED_OUTCOME_SUFFIXES = (
    "AlreadyExists",
    "Conflict",
    "Denied",
    "Expired",
    "Forbidden",
    "NotFound",
    "Rejected",
    "Unauthorized",
    "Unavailable",
)


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


def _is_expected_outcome(name: str) -> bool:
    return name.endswith(EXPECTED_OUTCOME_SUFFIXES)


class ExpectedOutcomeRule:
    code = "PAL015"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        if not _is_domain_module(filename, architecture, DECISION_MODULES):
            return []
        findings: list[Finding] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise):
                names = _exception_names(node.exc)
                if any(_is_expected_outcome(name) for name in names):
                    findings.append(
                        finding(
                            self,
                            filename,
                            node,
                            "expected domain outcomes must be returned as named "
                            "results, not raised",
                        )
                    )
            elif isinstance(node, ast.ExceptHandler):
                names = _exception_names(node.type)
                if any(_is_expected_outcome(name) for name in names):
                    findings.append(
                        finding(
                            self,
                            filename,
                            node,
                            "expected domain outcomes must be matched as named results, not caught",
                        )
                    )
        return findings
