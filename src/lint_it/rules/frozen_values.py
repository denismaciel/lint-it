from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.core import Finding, SourceFile, finding
from lint_it.policy import INNER_LAYERS

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


class FrozenValueRule:
    """A core or port dataclass is mutable.

    Dataclasses must be declared with `frozen=True`, and their fields may not be
    annotated with mutable collections (`list`, `dict`, `set`, or the `typing`
    and `collections.abc` mutable protocols). `ClassVar` fields are exempt. Use
    tuples, frozensets, or read-only `Mapping`/`Sequence` interfaces.
    """

    code = "LIT205"
    name = "frozen-values"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        if not file.has_layer(*INNER_LAYERS):
            return []
        symbols = file.symbols
        findings: list[Finding] = []
        for node in ast.walk(file.tree):
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
                        file,
                        node,
                        (
                            "core dataclasses must be frozen; "
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
                            file,
                            statement,
                            (
                                "frozen records must not expose mutable collection fields; "
                                "use tuples, frozensets, or a read-only collection interface"
                            ),
                        )
                    )
        return findings
