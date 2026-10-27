from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.core import Finding, SourceFile, finding
from lint_it.policy import Layer


def _annotation_contains_bool(annotation: ast.expr | None) -> bool:
    if isinstance(annotation, ast.Name):
        return annotation.id == "bool"
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _annotation_contains_bool(annotation.left) or _annotation_contains_bool(
            annotation.right
        )
    if isinstance(annotation, ast.Subscript):
        name = annotation.value
        identifier = (
            name.id
            if isinstance(name, ast.Name)
            else name.attr
            if isinstance(name, ast.Attribute)
            else None
        )
        if identifier in {"Union", "Optional"}:
            items = (
                annotation.slice.elts
                if isinstance(annotation.slice, ast.Tuple)
                else (annotation.slice,)
            )
            return any(_annotation_contains_bool(item) for item in items)
    return False


class BooleanPolicyRule:
    """A public core function takes a boolean, or returns one without a predicate name.

    A `bool` parameter is a hidden mode switch; replace it with an enum or a
    named value type. A function returning `bool` must be named as a question,
    with one of the prefixes in `conventions.predicate_prefixes` (default `is_`,
    `has_`, `can_`, `should_`, `allows_`, `contains_`, `matches_`). Private
    functions are exempt.
    """

    code = "LIT401"
    name = "boolean-policy"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        if not file.has_layer(Layer.CORE):
            return []
        prefixes = file.workspace.policy.predicate_prefixes
        findings: list[Finding] = []
        for node in ast.walk(file.tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name.startswith("_"):
                continue
            arguments = (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            )
            findings.extend(
                finding(
                    self,
                    file,
                    argument,
                    f"policy input {argument.arg!r} is boolean; use a named enum or value type",
                )
                for argument in arguments
                if argument.arg not in {"self", "cls"}
                and _annotation_contains_bool(argument.annotation)
            )
            if _annotation_contains_bool(node.returns) and not node.name.startswith(prefixes):
                findings.append(
                    finding(
                        self,
                        file,
                        node,
                        f"decision {node.name!r} returns bool; return a named result or enum",
                    )
                )
        return findings
