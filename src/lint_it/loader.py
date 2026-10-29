from __future__ import annotations

import ast
import tomllib
from dataclasses import replace
from pathlib import Path

from lint_it import baseline
from lint_it.workspace import (
    IGNORED_DIRECTORIES,
    MANIFEST,
    ParseFailure,
    Source,
    Workspace,
    load_manifest,
)


class ManifestError(Exception):
    """The manifest cannot be read or does not describe a usable workspace."""


def find_root(start: Path) -> Path:
    """The nearest directory at or above ``start`` with a manifest, else with a
    ``pyproject.toml``, else ``start`` itself."""
    start = start.resolve()
    for marker in (MANIFEST, "pyproject.toml"):
        for directory in (start, *start.parents):
            if (directory / marker).is_file():
                return directory
    return start


def _walk(root: Path, pattern: str) -> list[Path]:
    return sorted(
        path.resolve()
        for path in root.rglob(pattern)
        if not IGNORED_DIRECTORIES.intersection(path.relative_to(root).parts)
    )


def load_workspace(root: Path) -> Workspace:
    root = root.resolve()
    manifest = root / MANIFEST
    try:
        raw = tomllib.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {}
        workspace = load_manifest(
            root,
            raw,
            frozenset(path.parent for path in _walk(root, "pyproject.toml")),
            manifest if manifest.is_file() else None,
        )
        if workspace.baseline_path is not None and workspace.baseline_path.is_file():
            workspace = replace(
                workspace,
                baseline=baseline.parse(workspace.baseline_path.read_text(encoding="utf-8")),
            )
    except ValueError as error:
        raise ManifestError(str(error)) from error
    sources: list[Source] = []
    failures: list[ParseFailure] = []
    for path in sorted(
        {path for package in workspace.packages for path in _walk(package.root, "*.py")}
    ):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as error:
            failures.append(
                ParseFailure(path, error.lineno or 1, max((error.offset or 1) - 1, 0), error.msg)
            )
            continue
        sources.append(Source(path, tree))
    return replace(workspace, sources=tuple(sources), parse_failures=tuple(failures))
