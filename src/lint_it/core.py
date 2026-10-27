from __future__ import annotations

import ast
import inspect
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Protocol

from lint_it.imports import package_name
from lint_it.policy import Layer
from lint_it.symbols import resolved_symbols
from lint_it.workspace import Classification, Workspace


@dataclass(frozen=True)
class Finding:
    filename: str
    line: int
    column: int
    code: str
    message: str


@dataclass(frozen=True)
class SourceFile:
    """One parsed workspace file plus analysis shared by every rule that checks it."""

    tree: ast.Module
    path: Path
    workspace: Workspace

    @cached_property
    def filename(self) -> str:
        return relative_name(self.path, self.workspace.root)

    @cached_property
    def classification(self) -> Classification | None:
        return self.workspace.classify(self.path)

    @cached_property
    def layer(self) -> Layer | None:
        return None if self.classification is None else self.classification.layer

    def has_layer(self, *layers: Layer) -> bool:
        return self.layer in layers

    @cached_property
    def module(self) -> str | None:
        return self.workspace.module_name(self.path)

    @cached_property
    def package(self) -> str | None:
        """Anchor for this file's relative imports; None without a module identity."""
        return None if self.module is None else package_name(self.module, self.path)

    @cached_property
    def symbols(self) -> Mapping[ast.expr, frozenset[str]]:
        return resolved_symbols(self.tree, self.package)


class Rule(Protocol):
    """A rule's docstring is its documentation: a summary line, then the details."""

    code: str
    name: str

    def check(self, file: SourceFile) -> Iterable[Finding]: ...


def summary(rule: Rule) -> str:
    return documentation(rule).partition("\n")[0]


def documentation(rule: Rule) -> str:
    return inspect.cleandoc(type(rule).__doc__ or rule.name)


def relative_name(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()


def finding(rule: Rule, file: SourceFile, node: ast.AST, message: str) -> Finding:
    return Finding(
        filename=file.filename,
        line=getattr(node, "lineno", 1),
        column=getattr(node, "col_offset", 0),
        code=rule.code,
        message=message,
    )


def loaded_names(file: SourceFile) -> Iterable[tuple[ast.expr, frozenset[str]]]:
    """Resolved names the file reads, e.g. ``os.getenv`` behind any alias."""
    return (
        (node, names)
        for node, names in file.symbols.items()
        if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load) and names
    )


def sort_findings(findings: Iterable[Finding]) -> list[Finding]:
    """Ordered and deduplicated: an alias and its attribute can resolve to the same finding."""
    return sorted(
        set(findings), key=lambda item: (item.filename, item.line, item.column, item.code)
    )
