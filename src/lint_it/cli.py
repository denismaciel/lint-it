from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from lint_it.architecture import ClassificationOrigin
from lint_it.filesystem import (
    check_paths,
    workspace_architecture,
    workspace_project_roots,
    workspace_python_files,
)
from lint_it.rules.registry import ALL_RULES


def main() -> int:
    parser = argparse.ArgumentParser(description="Run lint-it application architecture rules.")
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument(
        "--workspace",
        type=Path,
        help="check every registered project and fail when project/file coverage is incomplete",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if args.workspace is not None and args.paths:
        parser.error("paths cannot be combined with --workspace")

    paths = args.paths or [Path("src")]
    workspace_errors: list[str] = []
    architecture = None
    if args.workspace is not None:
        try:
            architecture = workspace_architecture(args.workspace)
        except ValueError as error:
            parser.error(str(error))
        configured = {package.root for package in architecture.packages}
        discovered = workspace_project_roots(architecture.root)
        missing = sorted(discovered - configured)
        stale = sorted(configured - discovered)
        if missing or stale:
            details = [
                *(f"unregistered Python project: {path}" for path in missing),
                *(f"configured project has no pyproject.toml: {path}" for path in stale),
            ]
            workspace_errors.extend(details)
        paths = workspace_python_files(architecture)
        workspace_errors.extend(architecture.configuration_errors(paths))

    findings = check_paths(paths, ALL_RULES, architecture)
    if args.as_json:
        print(json.dumps([asdict(item) for item in findings], indent=2))
    else:
        for item in findings:
            print(f"{item.filename}:{item.line}:{item.column + 1}: {item.code} {item.message}")
        if workspace_errors:
            print("\n".join(workspace_errors))
        elif architecture is not None:
            origins = tuple(
                classification.origin
                for path in paths
                if (classification := architecture.classify(path)) is not None
            )
            dependency_override_count = sum(
                len(package.dependency_overrides) for package in architecture.packages
            )
            print(
                f"lint-it: {len(architecture.packages)} projects, "
                f"{len(paths)} Python files, {len(ALL_RULES)} rules, "
                f"{origins.count(ClassificationOrigin.DEFAULT)} defaults, "
                f"{origins.count(ClassificationOrigin.OVERRIDE)} layout overrides, "
                f"{dependency_override_count} dependency overrides, "
                "0 suppressions (unsupported)"
            )
    return 1 if findings or workspace_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
