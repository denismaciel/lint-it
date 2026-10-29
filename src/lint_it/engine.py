from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from lint_it.baseline import Key
from lint_it.core import Finding, Rule, SourceFile, relative_name, sort_findings
from lint_it.globs import matches_glob
from lint_it.rules.registry import MANIFEST, PARSE_ERROR
from lint_it.workspace import MANIFEST as MANIFEST_NAME
from lint_it.workspace import Ignore, Source, Workspace

FileChecker = Callable[[Workspace, tuple[Rule, ...], Sequence[Source]], list[Finding]]

# Findings about the workspace itself are never ignored or baselined.
UNSUPPRESSIBLE = frozenset({PARSE_ERROR.code, MANIFEST.code})


@dataclass(frozen=True)
class Result:
    """``findings`` is what to report: new findings and workspace problems."""

    findings: tuple[Finding, ...]
    baselined: tuple[Finding, ...] = ()
    ignored: tuple[Finding, ...] = ()


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


def key(finding: Finding) -> Key:
    return (finding.filename, finding.code, finding.message)


def _ignore_codes(
    ignore: Ignore, rules: tuple[Rule, ...], manifest: str
) -> tuple[frozenset[str], list[Finding]]:
    codes: set[str] = set()
    problems: list[Finding] = []
    for name in ignore.rules:
        rule = next((rule for rule in rules if name in (rule.code, rule.name)), None)
        if rule is None:
            problems.append(
                Finding(manifest, 1, 0, MANIFEST.code, f"ignore names unknown rule {name}")
            )
        elif rule.code in UNSUPPRESSIBLE:
            problems.append(
                Finding(manifest, 1, 0, MANIFEST.code, f"{rule.code} cannot be ignored")
            )
        else:
            codes.add(rule.code)
    return frozenset(codes), problems


def _ignored_by(
    workspace: Workspace, finding: Finding, ignore: Ignore, codes: frozenset[str]
) -> bool:
    if finding.code not in codes:
        return False
    if ignore.paths and not any(matches_glob(finding.filename, glob) for glob in ignore.paths):
        return False
    if not ignore.layers:
        return True
    classification = workspace.classify(workspace.root / finding.filename)
    return classification is not None and workspace.policy.is_a(classification.name, ignore.layers)


def _describe(ignore: Ignore) -> str:
    rules = ", ".join(ignore.rules)
    scope = ", ".join([*ignore.paths, *sorted(ignore.layers)])
    return f"{rules} in {scope}" if scope else rules


def run(
    workspace: Workspace,
    rules: Iterable[Rule],
    selected: tuple[Path, ...] = (),
    checker: FileChecker | None = None,
) -> Result:
    """Check the snapshot; ``selected`` limits file findings to those paths.

    Findings matching an ``[[ignore]]`` entry are dropped, then those the
    baseline lists are set aside; a snapshot without ``baseline_path`` has none."""

    def is_selected(path: Path) -> bool:
        return not selected or any(path.is_relative_to(item) for item in selected)

    rules = tuple(rules)
    root = workspace.root
    manifest = relative_name(workspace.manifest, root) if workspace.manifest else MANIFEST_NAME
    problems = [
        Finding(manifest, 1, 0, MANIFEST.code, error) for error in workspace.configuration_errors()
    ]
    problems.extend(
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
    found = sort_findings((checker or check_files)(workspace, rules, sources))

    ignores = []
    for ignore in workspace.ignores:
        codes, invalid = _ignore_codes(ignore, rules, manifest)
        problems.extend(invalid)
        ignores.append((ignore, codes))
    used: set[int] = set()
    kept: list[Finding] = []
    ignored: list[Finding] = []
    for item in found:
        match = next(
            (
                index
                for index, (ignore, codes) in enumerate(ignores)
                if _ignored_by(workspace, item, ignore, codes)
            ),
            None,
        )
        if match is None:
            kept.append(item)
        else:
            used.add(match)
            ignored.append(item)
    if not selected:
        problems.extend(
            Finding(
                manifest, 1, 0, MANIFEST.code, f"ignore suppresses nothing: {_describe(ignore)}"
            )
            for index, (ignore, codes) in enumerate(ignores)
            if index not in used and codes
        )

    if workspace.baseline_path is None:
        return Result(tuple(sort_findings([*problems, *kept])), (), tuple(ignored))
    remaining = dict(workspace.baseline.counts)
    new: list[Finding] = []
    baselined: list[Finding] = []
    for item in kept:
        if remaining.get(key(item), 0) > 0:
            remaining[key(item)] -= 1
            baselined.append(item)
        else:
            new.append(item)
    stale = sum(
        count for (filename, _, _), count in remaining.items() if is_selected(root / filename)
    )
    if stale:
        problems.append(
            Finding(
                relative_name(workspace.baseline_path, root),
                1,
                0,
                MANIFEST.code,
                f"{stale} baseline {'entry' if stale == 1 else 'entries'} no longer "
                f"{'matches' if stale == 1 else 'match'} a finding; "
                "run `lint-it baseline --prune` to shrink the baseline",
            )
        )
    return Result(tuple(sort_findings([*problems, *new])), tuple(baselined), tuple(ignored))


def check(
    workspace: Workspace,
    rules: Iterable[Rule],
    selected: tuple[Path, ...] = (),
    checker: FileChecker | None = None,
) -> list[Finding]:
    """Findings to report for the snapshot; see ``run``."""
    return list(run(workspace, rules, selected, checker).findings)
