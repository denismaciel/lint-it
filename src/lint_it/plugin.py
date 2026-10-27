from __future__ import annotations

import ast
from collections.abc import Iterator

from lint_it.core import check_tree
from lint_it.filesystem import architecture_for
from lint_it.rules.registry import ALL_RULES

Error = tuple[int, int, str, type]


class LintItChecker:
    name = "lint-it"
    version = "0.9.0"

    def __init__(self, tree: ast.AST, filename: str) -> None:
        self.tree = tree
        self.filename = filename

    def run(self) -> Iterator[Error]:
        for item in check_tree(
            self.tree, self.filename, ALL_RULES, architecture_for(self.filename)
        ):
            yield (
                item.line,
                item.column,
                f"{item.code} {item.message}",
                type(self),
            )
