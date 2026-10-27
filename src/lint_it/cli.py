from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from lint_it import engine, reporting
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
    findings = engine.check(workspace, ALL_RULES, selected)
    files = len(workspace.sources) + len(workspace.parse_failures)
    output = reporting.report(
        findings, reporting.Summary(len(workspace.packages), files), args.output
    )
    if output:
        print(output)
    return 1 if findings else 0


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
    "explain": _explain,
    "classify": _classify,
    "init": _init,
    "rules": _rules,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return COMMANDS[args.command](args)
