from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from types import MappingProxyType

from lint_it.architecture import Architecture
from lint_it.core import Finding, finding
from lint_it.rules.shared.functional_core import CORE_MODULES, _is_domain_module
from lint_it.rules.shared.symbols import resolved_symbols, stored_names

MUTATORS = MappingProxyType(
    {
        "builtins.list": frozenset(
            frozenset({"append", "extend", "insert", "remove", "pop", "clear", "sort", "reverse"})
        ),
        "builtins.dict": frozenset(frozenset({"clear", "pop", "popitem", "setdefault", "update"})),
        "builtins.set": frozenset(
            frozenset(
                {
                    "add",
                    "clear",
                    "discard",
                    "pop",
                    "remove",
                    "update",
                    "difference_update",
                    "intersection_update",
                    "symmetric_difference_update",
                }
            )
        ),
    }
)
TYPE_ALIASES = MappingProxyType(
    {
        "typing.List": "builtins.list",
        "typing.Dict": "builtins.dict",
        "typing.Set": "builtins.set",
        "typing.MutableSequence": "builtins.list",
        "collections.abc.MutableSequence": "builtins.list",
        "typing.MutableMapping": "builtins.dict",
        "collections.abc.MutableMapping": "builtins.dict",
        "typing.MutableSet": "builtins.set",
        "collections.abc.MutableSet": "builtins.set",
    }
)


@dataclass(frozen=True)
class _Origin:
    borrowed: str | None = None
    members: str | None = None
    kind: str | None = None


class _MutationVisitor(ast.NodeVisitor):
    def __init__(
        self,
        rule: BorrowedMutationRule,
        filename: str,
        symbols: dict[ast.expr, frozenset[str]],
        aliases: dict[str, _Origin],
    ) -> None:
        self.rule = rule
        self.filename = filename
        self.symbols = symbols
        self.aliases = aliases.copy()
        self.findings: list[Finding] = []

    def origin(self, node: ast.expr) -> _Origin:
        if isinstance(node, ast.Name):
            return self.aliases.get(node.id, _Origin())
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            base = self.origin(node.value)
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
                return _Origin(members=base.borrowed or base.members, kind=base.kind)
            return _Origin(borrowed=base.borrowed or base.members)
        if isinstance(node, (ast.List, ast.Dict, ast.Set)):
            kinds: dict[type[ast.expr], str] = {
                ast.List: "builtins.list",
                ast.Dict: "builtins.dict",
                ast.Set: "builtins.set",
            }
            kind = kinds[type(node)]
            values = node.values if isinstance(node, ast.Dict) else node.elts
            roots = {self.origin(value).borrowed for value in values} - {None}
            return _Origin(members=next(iter(roots)) if len(roots) == 1 else None, kind=kind)
        if isinstance(node, ast.Call):
            names = self.symbols.get(node.func, frozenset())
            if len(names) == 1 and (kind := next(iter(names))) in MUTATORS:
                source = self.origin(node.args[0]) if node.args else _Origin()
                return _Origin(members=source.borrowed or source.members, kind=kind)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "copy":
                source = self.origin(node.func.value)
                if source.kind in MUTATORS:
                    return _Origin(members=source.borrowed or source.members, kind=source.kind)
        return _Origin()

    def report(self, node: ast.AST, origin: _Origin) -> None:
        if origin.borrowed is not None:
            self.findings.append(
                finding(
                    self.rule,
                    self.filename,
                    node,
                    f"mutation of caller-owned {origin.borrowed!r}; build and return a new value",
                )
            )

    def write(self, target: ast.expr) -> None:
        if isinstance(target, (ast.Attribute, ast.Subscript)):
            self.report(target, self.origin(target.value))
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self.write(item)

    def bind(self, target: ast.expr, origin: _Origin) -> None:
        for name in stored_names(target):
            self.aliases[name] = (
                origin
                if isinstance(target, ast.Name)
                else _Origin(borrowed=origin.borrowed or origin.members)
            )

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        origin = self.origin(node.value)
        for target in node.targets:
            self.write(target)
            self.bind(target, origin)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
            self.write(node.target)
            self.bind(node.target, self.origin(node.value))

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self.bind(node.target, self.origin(node.value))

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.value)
        if isinstance(node.target, ast.Name):
            origin = self.origin(node.target)
            if origin.kind in MUTATORS:
                self.report(node, origin)
        else:
            self.write(node.target)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            self.write(target)
            self.bind(target, _Origin())

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            origin = self.origin(node.func.value)
            if node.func.attr in MUTATORS.get(origin.kind or "", frozenset()):
                self.report(node, origin)
        if (
            self.symbols.get(node.func)
            in (
                frozenset({"builtins.setattr"}),
                frozenset({"builtins.delattr"}),
                frozenset({"builtins.object.__setattr__"}),
            )
            and node.args
        ):
            self.report(node, self.origin(node.args[0]))
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.visit(node.iter)
        origin = self.origin(node.iter)
        self.bind(node.target, _Origin(borrowed=origin.borrowed or origin.members))
        self.branches([[], node.body])
        for statement in node.orelse:
            self.visit(statement)

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        self.branches([node.body, node.orelse])

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        self.branches([[], node.body])
        for statement in node.orelse:
            self.visit(statement)

    def visit_Try(self, node: ast.Try) -> None:
        self.branches([node.body + node.orelse, *(handler.body for handler in node.handlers)])
        for statement in node.finalbody:
            self.visit(statement)

    def branches(self, branches: list[list[ast.stmt]]) -> None:
        exits = []
        for body in branches:
            child = _MutationVisitor(self.rule, self.filename, self.symbols, self.aliases)
            for statement in body:
                child.visit(statement)
            self.findings.extend(child.findings)
            exits.append(child.aliases)
        for name in set().union(*(branch.keys() for branch in exits)):
            values = {branch.get(name, _Origin()) for branch in exits}
            self.aliases[name] = next(iter(values)) if len(values) == 1 else _Origin()

    def comprehension(
        self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
    ) -> None:
        child = _MutationVisitor(self.rule, self.filename, self.symbols, self.aliases)
        for generator in node.generators:
            child.visit(generator.iter)
            origin = child.origin(generator.iter)
            child.bind(generator.target, _Origin(borrowed=origin.borrowed or origin.members))
            for condition in generator.ifs:
                child.visit(condition)
        for expression in [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]:
            child.visit(expression)
        self.findings.extend(child.findings)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self.comprehension(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self.comprehension(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self.comprehension(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self.comprehension(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        pass

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        pass

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        pass

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass


def _parameter_kind(
    annotation: ast.expr | None, symbols: dict[ast.expr, frozenset[str]]
) -> str | None:
    names = symbols.get(annotation, frozenset()) if annotation is not None else frozenset()
    if len(names) != 1:
        return None
    name = next(iter(names))
    return TYPE_ALIASES.get(name, name)


class BorrowedMutationRule:
    code = "PAL019"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        if not _is_domain_module(filename, architecture, CORE_MODULES):
            return []
        symbols = resolved_symbols(tree)
        findings: list[Finding] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            parameters = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
            # Receiver ownership is unknown; frozen value records are enforced by PAL021.
            aliases = {
                arg.arg: _Origin(borrowed=arg.arg, kind=_parameter_kind(arg.annotation, symbols))
                for arg in parameters
                if arg.arg not in {"self", "cls"}
            }
            visitor = _MutationVisitor(self, filename, symbols, aliases)
            for statement in node.body:
                visitor.visit(statement)
            findings.extend(visitor.findings)
        return findings
