from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lint_it.architecture import Architecture


@dataclass(frozen=True)
class Finding:
    filename: str
    line: int
    column: int
    code: str
    message: str


class Rule(Protocol):
    code: str

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None
    ) -> Iterable[Finding]: ...


def normalized_filename(filename: str) -> str:
    value = filename.replace("\\", "/")
    return value[2:] if value.startswith("./") else value


def is_test_file(filename: str) -> bool:
    path = Path(normalized_filename(filename))
    return path.name.endswith("_test.py") or path.name.startswith("test_")


def finding(rule: Rule, filename: str, node: ast.AST, message: str) -> Finding:
    return Finding(
        filename=filename,
        line=getattr(node, "lineno", 1),
        column=getattr(node, "col_offset", 0),
        code=rule.code,
        message=message,
    )


def check_tree(
    tree: ast.AST, filename: str, rules: Iterable[Rule], architecture: Architecture | None = None
) -> list[Finding]:
    if not isinstance(tree, ast.Module):
        return []
    findings = [item for rule in rules for item in rule.check(tree, filename, architecture)]
    return sorted(
        findings,
        key=lambda item: (item.filename, item.line, item.column, item.code),
    )
