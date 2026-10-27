from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.architecture import Architecture
from lint_it.core import Finding, finding
from lint_it.rules.shared.functional_core import CORE_MODULES, _is_domain_module
from lint_it.rules.shared.symbols import resolved_symbols

MUTABLE_TYPES = frozenset(
    {
        "builtins.list",
        "builtins.dict",
        "builtins.set",
        "typing.List",
        "typing.Dict",
        "typing.Set",
        "typing.MutableMapping",
        "typing.MutableSequence",
        "typing.MutableSet",
        "collections.abc.MutableMapping",
        "collections.abc.MutableSequence",
        "collections.abc.MutableSet",
    }
)


class ImmutableValueRule:
    code = "PAL021"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        if not _is_domain_module(filename, architecture, CORE_MODULES):
            return []
        symbols = resolved_symbols(tree)
        findings: list[Finding] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            decorators = [
                decorator
                for decorator in node.decorator_list
                if symbols.get(decorator.func if isinstance(decorator, ast.Call) else decorator)
                == frozenset({"dataclasses.dataclass"})
            ]
            if not decorators:
                continue
            if not any(
                isinstance(decorator, ast.Call)
                and any(
                    keyword.arg == "frozen"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                    for keyword in decorator.keywords
                )
                for decorator in decorators
            ):
                findings.append(
                    finding(
                        self,
                        filename,
                        node,
                        (
                            "domain dataclasses must be frozen; "
                            "return a replacement value for transitions"
                        ),
                    )
                )
            for statement in node.body:
                if not isinstance(statement, ast.AnnAssign):
                    continue
                annotation = statement.annotation
                if isinstance(annotation, ast.Subscript) and symbols.get(
                    annotation.value
                ) == frozenset({"typing.ClassVar"}):
                    continue
                if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
                    # String annotations are handled for the outer type by the resolver.
                    annotations: list[ast.AST] = [annotation]
                else:
                    annotations = list(ast.walk(annotation))
                if any(
                    symbols.get(item, frozenset()) & MUTABLE_TYPES
                    for item in annotations
                    if isinstance(item, ast.expr)
                ):
                    findings.append(
                        finding(
                            self,
                            filename,
                            statement,
                            (
                                "frozen records must not expose mutable collection fields; "
                                "use tuples, frozensets, or a read-only collection interface"
                            ),
                        )
                    )
        return findings
