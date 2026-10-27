from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from lint_it.core import Finding, Rule, SourceFile, relative_name, sort_findings
from lint_it.rules.registry import MANIFEST, PARSE_ERROR
from lint_it.workspace import MANIFEST as MANIFEST_NAME
from lint_it.workspace import Workspace


def check(
    workspace: Workspace, rules: Iterable[Rule], selected: tuple[Path, ...] = ()
) -> list[Finding]:
    """Findings for the snapshot; ``selected`` limits file findings to those paths."""

    def is_selected(path: Path) -> bool:
        return not selected or any(path.is_relative_to(item) for item in selected)

    root = workspace.root
    manifest = relative_name(workspace.manifest, root) if workspace.manifest else MANIFEST_NAME
    findings = [
        Finding(manifest, 1, 0, MANIFEST.code, error) for error in workspace.configuration_errors()
    ]
    findings.extend(
        Finding(
            relative_name(failure.path, root),
            failure.line,
            failure.column,
            PARSE_ERROR.code,
            f"file cannot be parsed: {failure.message}",
        )
        for failure in workspace.parse_failures
        if is_selected(failure.path)
    )
    rules = tuple(rules)
    for source in workspace.sources:
        if is_selected(source.path):
            file = SourceFile(source.tree, source.path, workspace)
            findings.extend(item for rule in rules for item in rule.check(file))
    return sort_findings(findings)
