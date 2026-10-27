from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.core import Finding, SourceFile, finding, loaded_names
from lint_it.policy import INNER_LAYERS
from lint_it.rules.shared.effects import is_ambient
from lint_it.symbols import local_names


def _scope_nodes(body: list[ast.stmt]) -> Iterable[ast.AST]:
    for node in body:
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield from _descendants(node)


def _descendants(node: ast.AST) -> Iterable[ast.AST]:
    for child in ast.iter_child_nodes(node):
        yield child
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from _descendants(child)


class AmbientStateRule:
    """Core or port code reads or writes state it was not given.

    Reports process-wide context (working directory, locale, decimal context,
    context variables), writes through `global`/`nonlocal`, and reads of
    mutable module-level collections. Pass the value in and return the new
    state instead. Environment variables are covered by LIT301.
    """

    code = "LIT203"
    name = "ambient-state"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        if not file.has_layer(*INNER_LAYERS):
            return []
        tree, symbols = file.tree, file.symbols
        findings = [
            finding(
                self,
                file,
                node,
                f"{', '.join(sorted(names))} uses ambient state; "
                "pass an explicit value or policy into the core",
            )
            for node, names in loaded_names(file)
            if all(is_ambient(name) for name in names)
        ]
        parents = {
            child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
        }
        mutable_globals: set[str] = set()
        for statement in tree.body:
            if isinstance(statement, (ast.Assign, ast.AnnAssign)) and statement.value is not None:
                value = statement.value
                if isinstance(
                    value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)
                ) or (
                    isinstance(value, ast.Call)
                    and symbols.get(value.func)
                    in (
                        frozenset({"builtins.list"}),
                        frozenset({"builtins.dict"}),
                        frozenset({"builtins.set"}),
                    )
                ):
                    targets = (
                        statement.targets
                        if isinstance(statement, ast.Assign)
                        else [statement.target]
                    )
                    mutable_globals.update(
                        target.id for target in targets if isinstance(target, ast.Name)
                    )
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            nodes = tuple(_scope_nodes(node.body))
            external = {
                name
                for child in nodes
                if isinstance(child, (ast.Global, ast.Nonlocal))
                for name in child.names
            }
            parameters = {
                arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
            }
            parameters.update(
                arg.arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None
            )
            shadowed = local_names(node.body) | parameters
            parent = parents.get(node)
            while parent is not None:
                if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    outer_parameters = (
                        *parent.args.posonlyargs,
                        *parent.args.args,
                        *parent.args.kwonlyargs,
                    )
                    shadowed.update(argument.arg for argument in outer_parameters)
                    if not isinstance(parent, ast.Lambda):
                        shadowed.update(local_names(parent.body))
                parent = parents.get(parent)
            shadowed.difference_update(external)
            for child in nodes:
                if (
                    isinstance(child, ast.Name)
                    and isinstance(child.ctx, (ast.Store, ast.Del))
                    and child.id in external
                ):
                    findings.append(
                        finding(
                            self,
                            file,
                            child,
                            f"write to global/nonlocal {child.id!r}; "
                            "return the updated state instead",
                        )
                    )
                elif (
                    isinstance(child, ast.Name)
                    and isinstance(child.ctx, ast.Load)
                    and child.id in mutable_globals - shadowed
                ):
                    findings.append(
                        finding(
                            self,
                            file,
                            child,
                            f"mutable module state {child.id!r}; "
                            "use an immutable constant or pass a snapshot",
                        )
                    )
        return findings
