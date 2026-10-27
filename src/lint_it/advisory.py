from __future__ import annotations

import ast
import tomllib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from lint_it.architecture import _reject_unknown_keys
from lint_it.filesystem import iter_python_files


@dataclass(frozen=True)
class AdvisoryPolicy:
    boundary_file_names: tuple[str, ...]
    boundary_path_parts: tuple[str, ...]
    fastapi_default_call_names: tuple[str, ...]
    fastapi_route_decorator_names: tuple[str, ...]
    storage_scope: str
    sqlalchemy_adapter_path_part: str
    sqlalchemy_uow_path_part: str
    sqlite_adapter_path_part: str
    sqlite_uow_path: str
    composition_file: str
    sqlalchemy_storage_modules: tuple[str, ...]
    orm_model_modules: tuple[str, ...]
    orm_mapped_names: tuple[str, ...]
    module_aliases: Mapping[str, str]
    path_aliases: Mapping[str, str]
    shared_database_module: str
    storage_parent_modules: tuple[str, ...]


def normalize_aliases(value: str, aliases: Mapping[str, str]) -> str:
    for source, target in aliases.items():
        value = value.replace(source, target)
    return value


def load_policy(raw: dict[str, object]) -> AdvisoryPolicy:
    from dataclasses import fields

    expected = frozenset(field.name for field in fields(AdvisoryPolicy))
    _reject_unknown_keys(raw, expected, "advisory policy")
    if raw.keys() != expected:
        raise ValueError("advisory policy must specify every field")
    return AdvisoryPolicy(
        boundary_file_names=_strings(raw["boundary_file_names"]),
        boundary_path_parts=_strings(raw["boundary_path_parts"]),
        fastapi_default_call_names=_strings(raw["fastapi_default_call_names"]),
        fastapi_route_decorator_names=_strings(raw["fastapi_route_decorator_names"]),
        storage_scope=_text(raw["storage_scope"]),
        sqlalchemy_adapter_path_part=_text(raw["sqlalchemy_adapter_path_part"]),
        sqlalchemy_uow_path_part=_text(raw["sqlalchemy_uow_path_part"]),
        sqlite_adapter_path_part=_text(raw["sqlite_adapter_path_part"]),
        sqlite_uow_path=_text(raw["sqlite_uow_path"]),
        composition_file=_text(raw["composition_file"]),
        sqlalchemy_storage_modules=_strings(raw["sqlalchemy_storage_modules"]),
        orm_model_modules=_strings(raw["orm_model_modules"]),
        orm_mapped_names=_strings(raw["orm_mapped_names"]),
        module_aliases=_aliases(raw["module_aliases"]),
        path_aliases=_aliases(raw["path_aliases"]),
        shared_database_module=_text(raw["shared_database_module"]),
        storage_parent_modules=_strings(raw["storage_parent_modules"]),
    )


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("expected nonempty string")
    return value


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("expected string array")
    return tuple(_text(item) for item in value)


def _aliases(value: object) -> Mapping[str, str]:
    if not isinstance(value, dict):
        raise ValueError("expected alias table")
    return {_text(key): _text(item) for key, item in value.items()}


Diagnostic = tuple[int, int, str]


def normalized_filename(filename: str) -> str:
    value = filename.replace("\\", "/")
    if value.startswith("./"):
        return value[2:]
    return value


def is_boundary_file(filename: str, policy: AdvisoryPolicy) -> bool:
    normalized = normalized_filename(filename)
    if normalized.endswith(policy.boundary_file_names) or normalized.endswith("_test.py"):
        return True
    with_leading_slash = f"/{normalized}"
    return any(part in with_leading_slash for part in policy.boundary_path_parts)


def with_leading_slash(filename: str) -> str:
    return f"/{normalized_filename(filename)}"


def imported_modules(node: ast.Import | ast.ImportFrom) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if node.module is None:
        return ()
    return (node.module,)


def module_matches(module: str, target: str) -> bool:
    return module == target or module.startswith(f"{target}.")


def is_sqlalchemy_storage_path(path: str, policy: AdvisoryPolicy) -> bool:
    return policy.sqlalchemy_adapter_path_part in path or policy.sqlalchemy_uow_path_part in path


def is_sqlite_storage_path(path: str, policy: AdvisoryPolicy) -> bool:
    return policy.sqlite_adapter_path_part in path or path.endswith(policy.sqlite_uow_path)


def sqlalchemy_imported_modules(
    node: ast.Import | ast.ImportFrom, policy: AdvisoryPolicy
) -> tuple[str, ...]:
    modules = imported_modules(node)
    if not isinstance(node, ast.ImportFrom) or node.module is None:
        return modules
    if node.module not in policy.storage_parent_modules:
        return modules
    return (*modules, *(f"{node.module}.{alias.name}" for alias in node.names))


def is_sqlalchemy_storage_module(module: str, policy: AdvisoryPolicy) -> bool:
    normalized = normalize_aliases(module, policy.module_aliases)
    return any(module_matches(normalized, target) for target in policy.sqlalchemy_storage_modules)


def argument_defaults(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[ast.expr, ...]:
    kw_defaults = tuple(default for default in node.args.kw_defaults if default is not None)
    return (*node.args.defaults, *kw_defaults)


def call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def is_fastapi_default(node: ast.expr, policy: AdvisoryPolicy) -> bool:
    return isinstance(node, ast.Call) and call_name(node) in policy.fastapi_default_call_names


def decorator_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Call):
        return decorator_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def has_fastapi_route_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef, policy: AdvisoryPolicy
) -> bool:
    return any(
        decorator_name(decorator) in policy.fastapi_route_decorator_names
        for decorator in node.decorator_list
    )


def class_base_names(node: ast.ClassDef) -> tuple[str, ...]:
    return tuple(ast.unparse(base) for base in node.bases)


def is_protocol_class(node: ast.ClassDef) -> bool:
    return any(base == "Protocol" or base.endswith(".Protocol") for base in class_base_names(node))


def is_exception_class(node: ast.ClassDef) -> bool:
    if node.name.endswith(("Error", "Exception")):
        return True
    return any(
        base in {"Exception", "BaseException"} or base.endswith((".Exception", ".BaseException"))
        for base in class_base_names(node)
    )


def is_boundary_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef, policy: AdvisoryPolicy
) -> bool:
    defaults = argument_defaults(node)
    return has_fastapi_route_decorator(node, policy) or (
        bool(defaults) and all(is_fastapi_default(default, policy) for default in defaults)
    )


class Checker:
    def __init__(self, tree: ast.Module, filename: str, policy: AdvisoryPolicy) -> None:
        self.policy = policy
        self.tree = tree
        self.filename = filename

    def diagnostics(self) -> Iterator[Diagnostic]:
        policy = self.policy
        yield from self.check_storage_imports()
        if is_boundary_file(self.filename, policy):
            return
        yield from self.check_body(self.tree.body, in_protocol=False, in_exception=False)

    def check_storage_imports(self) -> Iterator[Diagnostic]:
        policy = self.policy
        normalized = normalized_filename(self.filename)
        path = with_leading_slash(normalized)
        path = normalize_aliases(path, policy.path_aliases)
        if policy.storage_scope not in path:
            return
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Import | ast.ImportFrom):
                continue
            modules = imported_modules(node)
            for module in modules:
                module = normalize_aliases(module, policy.module_aliases)
                if module_matches(module, "sqlalchemy") and (
                    not is_sqlalchemy_storage_path(path, policy)
                ):
                    yield (node.lineno, node.col_offset, "PLC002")
                if module_matches(module, "sqlite3") and (not is_sqlite_storage_path(path, policy)):
                    yield (node.lineno, node.col_offset, "PLC003")
                if (
                    module_matches(module, policy.shared_database_module)
                    and (not path.endswith(policy.composition_file))
                    and (not is_sqlalchemy_storage_path(path, policy))
                ):
                    yield (node.lineno, node.col_offset, "PLC004")
                if (
                    isinstance(node, ast.ImportFrom)
                    and module in policy.orm_model_modules
                    and any(alias.name in policy.orm_mapped_names for alias in node.names)
                    and (not is_sqlalchemy_storage_path(path, policy))
                ):
                    yield (node.lineno, node.col_offset, "PLC006")
            if (
                any(
                    is_sqlalchemy_storage_module(module, policy)
                    for module in sqlalchemy_imported_modules(node, policy)
                )
                and (not is_sqlalchemy_storage_path(path, policy))
                and (not path.endswith(policy.composition_file))
            ):
                yield (node.lineno, node.col_offset, "PLC005")

    def check_body(
        self, body: list[ast.stmt], in_protocol: bool, in_exception: bool
    ) -> Iterator[Diagnostic]:
        for node in body:
            yield from self.check_statement(node, in_protocol, in_exception)

    def check_statement(
        self, node: ast.stmt, in_protocol: bool, in_exception: bool
    ) -> Iterator[Diagnostic]:
        policy = self.policy
        if isinstance(node, ast.ClassDef):
            yield from self.check_body(
                node.body,
                in_protocol=in_protocol or is_protocol_class(node),
                in_exception=in_exception or is_exception_class(node),
            )
            return
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if (
                argument_defaults(node)
                and (not is_boundary_function(node, policy))
                and (not in_protocol)
                and (not (in_exception and node.name == "__init__"))
            ):
                yield (node.lineno, node.col_offset, "PLC001")
            yield from self.check_body(
                node.body, in_protocol=in_protocol, in_exception=in_exception
            )
            return
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                yield from self.check_statement(child, in_protocol, in_exception)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Check advisory defaults and storage boundaries")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        policy = load_policy(tomllib.loads(args.config.read_text()))
        paths = iter_python_files(args.paths)
        if not paths or any(not path.exists() for path in args.paths):
            raise ValueError("paths must exist and select Python files")
        findings = [
            f"{path}:{line}:{column + 1}: {code}"
            for path in paths
            for line, column, code in Checker(
                ast.parse(path.read_text()), str(path), policy
            ).diagnostics()
        ]
    except (ValueError, OSError, SyntaxError) as error:
        parser.error(str(error))
    for item in findings:
        print(item)
    return int(bool(findings))
