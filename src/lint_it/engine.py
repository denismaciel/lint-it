from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from lint_it.core import Finding, Rule, SourceFile, relative_name, sort_findings
from lint_it.rules.registry import MANIFEST, PARSE_ERROR
from lint_it.workspace import MANIFEST as MANIFEST_NAME
from lint_it.workspace import Source, Workspace

FileChecker = Callable[[Workspace, tuple[Rule, ...], Sequence[Source]], list[Finding]]


def check_files(
    workspace: Workspace, rules: tuple[Rule, ...], sources: Sequence[Source]
) -> list[Finding]:
    """Rule findings for ``sources``, which must belong to the snapshot."""
    return [
        item
        for source in sources
        for rule in rules
        for item in rule.check(SourceFile(source.tree, source.path, workspace))
    ]


def check(
    workspace: Workspace,
    rules: Iterable[Rule],
    selected: tuple[Path, ...] = (),
    checker: FileChecker | None = None,
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
    sources = [source for source in workspace.sources if is_selected(source.path)]
    findings.extend((checker or check_files)(workspace, tuple(rules), sources))
    return sort_findings(findings)
