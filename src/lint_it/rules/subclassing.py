from __future__ import annotations

import ast
import builtins
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from lint_it.core import Finding, SourceFile, finding
from lint_it.imports import absolute_module, package_name
from lint_it.symbols import UNKNOWN, module_symbols
from lint_it.workspace import Source

BUILTIN_EXCEPTIONS = frozenset(
    f"builtins.{name}"
    for name, value in vars(builtins).items()
    if isinstance(value, type) and issubclass(value, BaseException)
)
DECLARATIVE_BASES = frozenset(
    {
        "sqlalchemy.ext.declarative.declarative_base",
        "sqlalchemy.orm.DeclarativeBase",
        "sqlalchemy.orm.DeclarativeBaseNoMeta",
        "sqlalchemy.orm.declarative_base",
    }
)


@dataclass(frozen=True)
class _Scope:
    """A module's tree and resolved names, for following base classes into it."""

    tree: ast.Module
    symbols: Mapping[ast.expr, frozenset[str]]


Definition = tuple[ast.ClassDef | ast.expr, _Scope]


def _is_allowed(name: str, allowed: frozenset[str]) -> bool:
    return name in allowed or any(
        pattern.endswith(".*") and name.startswith(pattern[:-1]) for pattern in allowed
    )


def _all_in(names: frozenset[str], allowed: frozenset[str]) -> bool:
    return bool(names) and "?" not in names and all(_is_allowed(name, allowed) for name in names)


def _assigned_value(statement: ast.stmt, name: str) -> ast.expr | None:
    if isinstance(statement, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == name for target in statement.targets
    ):
        return statement.value
    if (
        isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and statement.target.id == name
    ):
        return statement.value
    return None


def _definition(
    name: str, modules: Mapping[str, Source], seen: frozenset[str]
) -> Definition | None:
    """The class or assigned value a qualified workspace name refers to, through re-exports."""
    module, _, attribute = name.rpartition(".")
    source = modules.get(module)
    if source is None or name in seen:
        return None
    package = package_name(module, source.path)
    for statement in source.tree.body:
        if isinstance(statement, ast.ClassDef) and statement.name == attribute:
            return statement, _Scope(source.tree, module_symbols(source.tree, package))
        value = _assigned_value(statement, attribute)
        if value is not None:
            return value, _Scope(source.tree, module_symbols(source.tree, package))
        if isinstance(statement, ast.ImportFrom):
            imported = absolute_module(statement, package)
            for alias in statement.names:
                if imported and (alias.asname or alias.name) == attribute:
                    return _definition(f"{imported}.{alias.name}", modules, seen | {name})
    return None


def _base_definitions(
    base: ast.expr, scope: _Scope, modules: Mapping[str, Source]
) -> list[Definition] | None:
    """Workspace definitions of a base expression; None if any part is unknown."""
    names = scope.symbols.get(base, UNKNOWN)
    if names == UNKNOWN:
        target = base.value if isinstance(base, ast.Subscript) else base
        local = next(
            (
                statement
                for statement in scope.tree.body
                if isinstance(target, ast.Name)
                and isinstance(statement, ast.ClassDef)
                and statement.name == target.id
            ),
            None,
        )
        return None if local is None else [(local, scope)]
    definitions = [_definition(name, modules, frozenset()) for name in names]
    return [item for item in definitions if item is not None] if all(definitions) else None


def _is_extendable(definition: Definition, allowed: frozenset[str]) -> bool:
    """A workspace class one step below an allowed base, e.g. ``Base(DeclarativeBase)``."""
    node, scope = definition
    if not isinstance(node, ast.ClassDef):
        return _all_in(scope.symbols.get(node, UNKNOWN), allowed)
    bases = [scope.symbols.get(base, UNKNOWN) for base in node.bases]
    return any(names != {"builtins.object"} for names in bases) and all(
        _all_in(names, allowed) for names in bases
    )


def _is_declarative(definition: Definition) -> bool:
    node, scope = definition
    names = (
        [scope.symbols.get(base, UNKNOWN) for base in node.bases]
        if isinstance(node, ast.ClassDef)
        else [scope.symbols.get(node, UNKNOWN)]
    )
    return any(_all_in(item, DECLARATIVE_BASES) for item in names)


def _is_plain(definition: Definition) -> bool:
    node, scope = definition
    return isinstance(node, ast.ClassDef) and all(
        scope.symbols.get(base, UNKNOWN) == {"builtins.object"} for base in node.bases
    )


def _is_exception(
    definition: Definition, modules: Mapping[str, Source], seen: frozenset[int]
) -> bool:
    node, scope = definition
    if not isinstance(node, ast.ClassDef) or id(node) in seen:
        return False
    for base in node.bases:
        if _all_in(scope.symbols.get(base, UNKNOWN), BUILTIN_EXCEPTIONS):
            return True
        parents = _base_definitions(base, scope, modules) or []
        if any(_is_exception(parent, modules, seen | {id(node)}) for parent in parents):
            return True
    return False


class SubclassingRule:
    """A class extends a base that is not on the allowlist.

    Inheritance couples a class to its parent's internals; prefer composition,
    functions over values, and `Protocol`s for shared interfaces. A class may
    extend a name in `conventions.allowed_bases` (default: every builtin, such
    as `Exception`, plus `typing.Protocol`/`NamedTuple`/`TypedDict`/`Generic`,
    `enum` bases, Pydantic `BaseModel`/`RootModel`/`BaseSettings`, and
    SQLAlchemy declarative bases and `TypeDecorator`), or a workspace class that
    directly extends one: a shared `Base(DeclarativeBase)` for tables, a common
    `Model(BaseModel)`, a `DomainError(Exception)`, or a `Protocol` a fake
    implements. Deeper hierarchies are reported, except for exceptions, which
    may nest to any depth. A table that extends a declarative base may also mix
    in plain workspace classes, such as a `ProjectOwned` holding shared columns.
    Entries ending in `.*` allow a whole module. Set `conventions.allowed_bases`
    to replace the list, or `conventions.extend_allowed_bases` to add to it.
    """

    code = "LIT403"
    name = "restricted-subclassing"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        if file.layer is None:
            return []
        allowed = file.workspace.policy.allowed_bases
        modules = file.workspace.index.modules
        scope = _Scope(file.tree, file.symbols)
        findings: list[Finding] = []
        for node in ast.walk(file.tree):
            if not isinstance(node, ast.ClassDef):
                continue
            rejected: list[tuple[ast.expr, str]] = []
            mixins: list[tuple[ast.expr, str]] = []
            declarative = False
            for base in node.bases:
                names = scope.symbols.get(base, UNKNOWN)
                if _all_in(names, DECLARATIVE_BASES):
                    declarative = True
                if _all_in(names, allowed):
                    continue
                described = (
                    f"'{ast.unparse(base)}', a workspace class"
                    if names == UNKNOWN
                    else ", ".join(sorted(names))
                )
                definitions = _base_definitions(base, scope, modules)
                if definitions is None or any(item[0] is node for item in definitions):
                    if names == UNKNOWN:
                        described = f"'{ast.unparse(base)}', which lint-it cannot resolve"
                    rejected.append((base, described))
                    continue
                if all(_is_declarative(item) for item in definitions):
                    declarative = True
                if all(
                    _is_extendable(item, allowed) or _is_exception(item, modules, frozenset())
                    for item in definitions
                ):
                    continue
                if all(_is_plain(item) for item in definitions):
                    mixins.append((base, described))
                else:
                    rejected.append((base, described))
            for base, described in rejected if declarative else rejected + mixins:
                findings.append(
                    finding(
                        self,
                        file,
                        base,
                        f"'{node.name}' extends {described}, which is not an allowed base; "
                        "compose, or implement a Protocol "
                        "(extend conventions.allowed_bases for framework bases)",
                    )
                )
        return findings
