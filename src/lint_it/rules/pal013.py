from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.architecture import Architecture
from lint_it.core import Finding, finding
from lint_it.rules.shared.functional_core import DECISION_MODULES, _is_domain_module

PREDICATE_PREFIXES = (
    "allows_",
    "can_",
    "contains_",
    "has_",
    "is_",
    "matches_",
    "should_",
)


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


class ExplicitPolicyTypesRule:
    code = "PAL013"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        if not _is_domain_module(filename, architecture, DECISION_MODULES):
            return []
        findings: list[Finding] = []
        for node in ast.walk(tree):
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
                    filename,
                    argument,
                    f"policy input {argument.arg!r} is boolean; use a named enum or value type",
                )
                for argument in arguments
                if argument.arg not in {"self", "cls"}
                and _annotation_contains_bool(argument.annotation)
            )
            if _annotation_contains_bool(node.returns) and not node.name.startswith(
                PREDICATE_PREFIXES
            ):
                findings.append(
                    finding(
                        self,
                        filename,
                        node,
                        f"decision {node.name!r} returns bool; return a named result or enum",
                    )
                )
        return findings
