from __future__ import annotations

import ast
from types import MappingProxyType

UNKNOWN = frozenset({"?"})
BUILTINS = frozenset(
    {
        "open",
        "print",
        "input",
        "list",
        "dict",
        "set",
        "tuple",
        "frozenset",
        "getattr",
        "setattr",
        "delattr",
        "eval",
        "exec",
        "__import__",
        "object",
    }
)
INSTANCE_FACTORIES = MappingProxyType(
    {
        "logging.getLogger": "logging.Logger",
        "structlog.get_logger": "structlog.BoundLogger",
        "pathlib.Path.home": "pathlib.Path",
        "pathlib.Path.cwd": "pathlib.Path",
    }
)


def stored_names(node: ast.AST) -> set[str]:
    return {
        item.id
        for item in ast.walk(node)
        if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store)
    }


class _Locals(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.names.add(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.names.update(alias.asname or alias.name for alias in node.names)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass

    def visit_ListComp(self, node: ast.ListComp) -> None:
        pass

    def visit_SetComp(self, node: ast.SetComp) -> None:
        pass

    def visit_DictComp(self, node: ast.DictComp) -> None:
        pass

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        pass


def local_names(body: list[ast.stmt]) -> set[str]:
    visitor = _Locals()
    for statement in body:
        visitor.visit(statement)
    return visitor.names


class _Resolver(ast.NodeVisitor):
    def __init__(self, bindings: dict[str, frozenset[str]]) -> None:
        self.bindings = bindings.copy()
        self.references: dict[ast.expr, frozenset[str]] = {}
        self.function_parent: dict[str, frozenset[str]] | None = None

    def visit_Module(self, node: ast.Module) -> None:
        # Function globals are looked up when called, not when defined. A later
        # module rebinding must not leave a stale imported name in their scope.
        summary = _Resolver(self.bindings)
        for statement in node.body:
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                summary.visit(statement)
            elif isinstance(statement, ast.Assign):
                names = summary.names(statement.value)
                for target in statement.targets:
                    summary.bind(target, names)
            elif isinstance(statement, ast.AnnAssign):
                summary.bind(statement.target, summary.names(statement.value))
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                summary.bindings[statement.name] = UNKNOWN
            else:
                summary.bindings.update(dict.fromkeys(local_names([statement]), UNKNOWN))
        self.function_parent = summary.bindings
        for statement in node.body:
            self.visit(statement)

    def names(self, node: ast.expr | None) -> frozenset[str]:
        if node is None:
            return UNKNOWN
        if isinstance(node, ast.Name):
            return self.bindings.get(node.id, UNKNOWN)
        if isinstance(node, ast.Attribute):
            return frozenset(
                f"{name}.{node.attr}" if name != "?" else "?" for name in self.names(node.value)
            )
        if isinstance(node, ast.Call):
            return frozenset(INSTANCE_FACTORIES.get(name, name) for name in self.names(node.func))
        if isinstance(node, ast.Subscript):
            return self.names(node.value)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return self.names(node.left)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                return self.names(ast.parse(node.value, mode="eval").body)
            except SyntaxError:
                return UNKNOWN
        return UNKNOWN

    def visit(self, node: ast.AST) -> None:
        if isinstance(node, ast.expr):
            self.references[node] = self.names(node)
        super().visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.bindings[alias.asname or alias.name.split(".")[0]] = frozenset(
                {alias.name if alias.asname else alias.name.split(".")[0]}
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module:
            for alias in node.names:
                if alias.name != "*":
                    self.bindings[alias.asname or alias.name] = frozenset(
                        {f"{node.module}.{alias.name}"}
                    )

    def bind(self, target: ast.expr, names: frozenset[str]) -> None:
        for name in stored_names(target):
            self.bindings[name] = names if isinstance(target, ast.Name) else UNKNOWN

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        names = self.names(node.value)
        for target in node.targets:
            self.visit(target)
            self.bind(target, names)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.visit(node.annotation)
        if node.value is not None:
            self.visit(node.value)
        self.bind(
            node.target,
            self.names(node.annotation) if node.value is None else self.names(node.value),
        )

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self.bind(node.target, self.names(node.value))

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.generic_visit(node)
        self.bind(node.target, UNKNOWN)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            self.bind(target, UNKNOWN)

    def function(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> None:
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        if not isinstance(node, ast.Lambda):
            for decorator in node.decorator_list:
                self.visit(decorator)
            self.bindings[node.name] = UNKNOWN
        parameters = (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
            *((node.args.vararg,) if node.args.vararg else ()),
            *((node.args.kwarg,) if node.args.kwarg else ()),
        )
        for arg in parameters:
            if arg.annotation is not None:
                self.visit(arg.annotation)
        annotations = {arg.arg: self.names(arg.annotation) for arg in parameters}
        bindings = (
            self.function_parent if self.function_parent is not None else self.bindings
        ).copy()
        body = node.body if not isinstance(node, ast.Lambda) else []
        bindings.update(dict.fromkeys(local_names(body), UNKNOWN))
        bindings.update(annotations)
        for variadic in (node.args.vararg, node.args.kwarg):
            if variadic is not None:
                bindings[variadic.arg] = UNKNOWN
        child = _Resolver(bindings)
        if isinstance(node, ast.Lambda):
            child.visit(node.body)
        else:
            for statement in body:
                child.visit(statement)
        self.references.update(child.references)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for expression in (*node.bases, *node.decorator_list):
            self.visit(expression)
        for keyword in node.keywords:
            self.visit(keyword.value)
        child = _Resolver(self.bindings)
        child.function_parent = (
            self.function_parent if self.function_parent is not None else self.bindings
        ).copy()
        for statement in node.body:
            child.visit(statement)
        self.references.update(child.references)
        self.bindings[node.name] = UNKNOWN

    def branches(self, branches: list[list[ast.stmt]]) -> None:
        exits = []
        for body in branches:
            child = _Resolver(self.bindings)
            child.function_parent = self.function_parent
            for statement in body:
                child.visit(statement)
            self.references.update(child.references)
            exits.append(child.bindings)
        for name in set().union(*(branch.keys() for branch in exits)):
            self.bindings[name] = frozenset().union(
                *(branch.get(name, UNKNOWN) for branch in exits)
            )

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        self.branches([node.body, node.orelse])

    def visit_For(self, node: ast.For | ast.AsyncFor) -> None:
        self.visit(node.iter)
        self.bind(node.target, UNKNOWN)
        self.branches([[], node.body])
        for statement in node.orelse:
            self.visit(statement)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.visit_For(node)

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        self.branches([[], node.body])
        for statement in node.orelse:
            self.visit(statement)

    def visit_Try(self, node: ast.Try | ast.TryStar) -> None:
        # Exceptional control flow may observe any body prefix. Invalidate names
        # written there before merging handlers rather than inventing certainty.
        self.bindings.update(dict.fromkeys(local_names(node.body), UNKNOWN))
        for handler in node.handlers:
            if handler.name is not None:
                self.bindings[handler.name] = UNKNOWN
        self.branches([node.body + node.orelse, *(handler.body for handler in node.handlers)])
        for statement in node.finalbody:
            self.visit(statement)

    def visit_Match(self, node: ast.Match) -> None:
        self.visit(node.subject)
        for case in node.cases:
            for capture in ast.walk(case.pattern):
                if isinstance(capture, (ast.MatchAs, ast.MatchStar)) and capture.name:
                    self.bindings[capture.name] = UNKNOWN
                elif isinstance(capture, ast.MatchMapping) and capture.rest:
                    self.bindings[capture.rest] = UNKNOWN
            if case.guard is not None:
                self.visit(case.guard)
        self.branches([[], *(case.body for case in node.cases)])

    def visit_TryStar(self, node: ast.TryStar) -> None:
        self.visit_Try(node)

    def comprehension(
        self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
    ) -> None:
        child = _Resolver(self.bindings)
        for generator in node.generators:
            child.visit(generator.iter)
            child.bind(generator.target, UNKNOWN)
            for condition in generator.ifs:
                child.visit(condition)
        for value in [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]:
            child.visit(value)
        self.references.update(child.references)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self.comprehension(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self.comprehension(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self.comprehension(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self.comprehension(node)


def resolved_symbols(tree: ast.Module) -> dict[ast.expr, frozenset[str]]:
    resolver = _Resolver({name: frozenset({f"builtins.{name}"}) for name in BUILTINS})
    resolver.visit(tree)
    return resolver.references
