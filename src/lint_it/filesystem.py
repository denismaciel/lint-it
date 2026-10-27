from __future__ import annotations

import ast
import tomllib
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

from lint_it.architecture import (
    CONFIG_FILENAME,
    IGNORED_DIRECTORY_NAMES,
    Architecture,
    Source,
    load_manifest,
)
from lint_it.core import Finding, Rule, check_tree


def iter_python_files(paths: Iterable[Path]) -> list[Path]:
    files: set[Path] = set()
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            files.add(path.resolve())
        elif path.is_dir():
            files.update(
                candidate.resolve()
                for candidate in path.rglob("*.py")
                if not IGNORED_DIRECTORY_NAMES.intersection(candidate.parts)
            )
    return sorted(files)


def workspace_project_roots(root: Path) -> set[Path]:
    return {
        path.parent.resolve()
        for path in root.rglob("pyproject.toml")
        if not IGNORED_DIRECTORY_NAMES.intersection(path.parts)
    }


def workspace_python_files(architecture: Architecture) -> list[Path]:
    return [source.path for source in architecture.sources]


def load_architecture(config_path: Path) -> Architecture:
    config = config_path.resolve()
    architecture = load_manifest(
        config.parent,
        tomllib.loads(config.read_text()),
        frozenset(workspace_project_roots(config.parent)),
    )
    sources = tuple(
        Source(
            path, ast.parse(path.read_text(), filename=str(path)), architecture.module_name(path)
        )
        for path in iter_python_files(package.root for package in architecture.packages)
    )
    return replace(architecture, sources=sources)


def architecture_for(filename: str) -> Architecture | None:
    path = Path(filename).resolve()
    if not path.is_file():
        return None
    for parent in path.parents:
        config = parent / CONFIG_FILENAME
        if config.is_file():
            return load_architecture(config)
    return None


def workspace_architecture(root: Path) -> Architecture:
    config = root.resolve() / CONFIG_FILENAME
    if not config.is_file():
        raise ValueError(f"workspace is missing {CONFIG_FILENAME}: {root}")
    return load_architecture(config)


def check_paths(
    paths: Iterable[Path], rules: Iterable[Rule], architecture: Architecture | None = None
) -> list[Finding]:
    selected = tuple(rules)
    snapshots: dict[Path, Architecture] = {}
    findings: list[Finding] = []
    for path in iter_python_files(paths):
        snapshot = architecture or next(
            (item for root, item in snapshots.items() if path.is_relative_to(root)), None
        )
        if snapshot is None:
            snapshot = architecture_for(str(path))
            if snapshot is not None:
                snapshots[snapshot.root] = snapshot
        source = snapshot.index.sources.get(path) if snapshot else None
        tree = source.tree if source is not None else None
        if tree is None:
            tree = ast.parse(path.read_text(), filename=str(path))
        findings.extend(check_tree(tree, str(path), selected, snapshot))
    return sorted(findings, key=lambda item: (item.filename, item.line, item.column, item.code))
