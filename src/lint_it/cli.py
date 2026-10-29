from __future__ import annotations

import argparse
import gc
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from lint_it import baseline, engine, parallel, reporting
from lint_it.core import Finding, relative_name
from lint_it.layouts import BUILT_IN
from lint_it.loader import ManifestError, find_root, load_workspace
from lint_it.reporting import Format
from lint_it.rules.registry import ALL_RULES, MANIFEST, RULES_BY_CODE
from lint_it.workspace import MANIFEST as MANIFEST_NAME
from lint_it.workspace import Kind, Workspace

STARTER_MANIFEST = """\
# lint-it manifest: https://github.com/denismaciel/lint-it/blob/main/docs/configuration.md

[workspace]
kind = "{kind}"
layout = "{layout}"
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lint-it", description="Architecture rules for functional-core Python workspaces."
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    check = commands.add_parser("check", help="check the workspace")
    check.add_argument("paths", nargs="*", type=Path, help="only report findings under these paths")
    check.add_argument(
        "--root",
        type=Path,
        help="workspace root (default: nearest lint-it.toml, else nearest pyproject.toml)",
    )
    check.add_argument(
        "--format", type=Format, choices=list(Format), default=Format.TEXT, dest="output"
    )
    check.add_argument(
        "--jobs", type=int, help="worker processes (default: one per CPU; 1 checks in-process)"
    )
    check.add_argument(
        "--no-baseline", action="store_true", help="report findings the baseline lists, too"
    )

    baseline = commands.add_parser(
        "baseline", help="record current findings in the baseline file (workspace.baseline)"
    )
    baseline.add_argument("--root", type=Path)
    baseline.add_argument(
        "--prune", action="store_true", help="only drop entries that no longer match; never add"
    )
    baseline.add_argument("--jobs", type=int)

    report = commands.add_parser("report", help="summarize where findings are")
    report.add_argument("paths", nargs="*", type=Path)
    report.add_argument("--root", type=Path)
    report.add_argument("--top", type=int, default=15, help="rows per ranking (default 15)")
    report.add_argument(
        "--depth", type=int, default=3, help="directory levels per area (default 3)"
    )
    report.add_argument(
        "--format",
        type=Format,
        choices=(Format.TEXT, Format.JSON),
        default=Format.TEXT,
        dest="output",
    )
    report.add_argument("--jobs", type=int)

    explain = commands.add_parser("explain", help="show the documentation for a rule")
    explain.add_argument("code", help="rule code or name, e.g. LIT101 or layer-dependency")

    classify = commands.add_parser("classify", help="show the layer of each file and why")
    classify.add_argument("paths", nargs="+", type=Path)
    classify.add_argument("--root", type=Path)

    init = commands.add_parser("init", help="write a starter lint-it.toml")
    init.add_argument("--root", type=Path, default=Path())
    init.add_argument("--kind", choices=[kind.value for kind in Kind], default=Kind.SERVER.value)
    init.add_argument("--layout", choices=list(BUILT_IN), default="domains")

    rules = commands.add_parser("rules", help="list every rule")
    rules.add_argument("--format", choices=("text", "markdown"), default="text", dest="output")
    return parser


def _load(root: Path | None, output: Format) -> Workspace | None:
    root = find_root(Path.cwd()) if root is None else root.resolve()
    try:
        return load_workspace(root)
    except ManifestError as error:
        problem = Finding(MANIFEST_NAME, 1, 0, MANIFEST.code, str(error))
        stream = sys.stderr if output is Format.TEXT else sys.stdout
        print(reporting.report([problem], None, output), file=stream)
        return None


def _selected(paths: Sequence[Path], workspace: Workspace) -> tuple[Path, ...] | str:
    selected = tuple(path.resolve() for path in paths)
    for path in selected:
        if not path.exists():
            return f"no such file or directory: {path}"
        if not path.is_relative_to(workspace.root):
            return f"{path} is outside the workspace {workspace.root}"
    return selected


def _check(args: argparse.Namespace) -> int:
    workspace = _load(args.root, args.output)
    if workspace is None:
        return 2
    selected = _selected(args.paths, workspace)
    if isinstance(selected, str):
        print(f"lint-it: {selected}", file=sys.stderr)
        return 2
    if args.no_baseline:
        workspace = replace(workspace, baseline_path=None)
    result = engine.run(workspace, ALL_RULES, selected, parallel.checker(args.jobs))
    files = len(workspace.sources) + len(workspace.parse_failures)
    totals = reporting.Summary(
        len(workspace.packages), files, len(result.baselined), len(result.ignored)
    )
    output = reporting.report(result.findings, totals, args.output)
    if output:
        print(output)
    return 1 if result.findings else 0


def _baseline(args: argparse.Namespace) -> int:
    workspace = _load(args.root, Format.TEXT)
    if workspace is None:
        return 2
    path = workspace.baseline_path
    if path is None:
        print(
            "lint-it: set workspace.baseline in lint-it.toml, e.g. "
            'baseline = "lint-it-baseline.json"',
            file=sys.stderr,
        )
        return 2
    result = engine.run(
        replace(workspace, baseline_path=None), ALL_RULES, (), parallel.checker(args.jobs)
    )
    problems = [item for item in result.findings if item.code in engine.UNSUPPRESSIBLE]
    actual = Counter(
        engine.key(item) for item in result.findings if item.code not in engine.UNSUPPRESSIBLE
    )
    previous = workspace.baseline.counts
    counts = (
        {key: min(count, actual[key]) for key, count in previous.items()}
        if args.prune
        else dict(actual)
    )
    path.write_text(baseline.render(counts), encoding="utf-8")
    recorded = sum(counts.values())
    files = len({filename for (filename, _, _), count in counts.items() if count})
    print(
        f"wrote {relative_name(path, workspace.root)}: {recorded} findings in {files} files "
        f"(was {workspace.baseline.size})"
    )
    if problems:
        print(reporting.report(problems, None, Format.TEXT), file=sys.stderr)
        return 1
    return 0


def _report(args: argparse.Namespace) -> int:
    workspace = _load(args.root, args.output)
    if workspace is None:
        return 2
    selected = _selected(args.paths, workspace)
    if isinstance(selected, str):
        print(f"lint-it: {selected}", file=sys.stderr)
        return 2
    result = engine.run(workspace, ALL_RULES, selected, parallel.checker(args.jobs))
    stats = reporting.statistics(result, workspace, ALL_RULES, top=args.top, depth=args.depth)
    print(reporting.render_statistics(stats, args.output))
    return 0


def _explain(args: argparse.Namespace) -> int:
    rule = RULES_BY_CODE.get(args.code.upper()) or next(
        (rule for rule in ALL_RULES if rule.name == args.code), None
    )
    if rule is None:
        print(f"lint-it: unknown rule {args.code}; run `lint-it rules`", file=sys.stderr)
        return 2
    print(reporting.explain(rule))
    return 0


def _classify(args: argparse.Namespace) -> int:
    workspace = _load(args.root, Format.TEXT)
    if workspace is None:
        return 2
    selected = _selected(args.paths, workspace)
    if isinstance(selected, str):
        print(f"lint-it: {selected}", file=sys.stderr)
        return 2
    known = sorted(
        {
            *workspace.index.sources,
            *(failure.path for failure in workspace.parse_failures),
            *(path for path in selected if path.is_file()),
        }
    )
    for path in known:
        if any(path.is_relative_to(item) for item in selected):
            package = workspace.package_for(path)
            print(
                reporting.describe(
                    relative_name(path, workspace.root),
                    workspace.classify(path),
                    None if package is None else package.layout,
                )
            )
    return 0


def _init(args: argparse.Namespace) -> int:
    manifest = args.root / MANIFEST_NAME
    if manifest.exists():
        print(f"lint-it: {manifest} already exists", file=sys.stderr)
        return 2
    manifest.write_text(
        STARTER_MANIFEST.format(kind=args.kind, layout=args.layout), encoding="utf-8"
    )
    print(f"wrote {manifest}; run `lint-it check` next")
    return 0


def _rules(args: argparse.Namespace) -> int:
    if args.output == "markdown":
        print(reporting.rule_reference(ALL_RULES), end="")
    else:
        print(reporting.rule_table(ALL_RULES))
    return 0


COMMANDS = {
    "check": _check,
    "baseline": _baseline,
    "report": _report,
    "explain": _explain,
    "classify": _classify,
    "init": _init,
    "rules": _rules,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    # A run allocates millions of long-lived AST nodes and frees nothing until exit,
    # so cyclic collection only rescans them.
    gc.disable()
    try:
        return COMMANDS[args.command](args)
    finally:
        gc.enable()
