from __future__ import annotations

import ast
import importlib.metadata
import re
import sys
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lint_it.architecture import _reject_unknown_keys, _relative_package_path, _string


@dataclass(frozen=True)
class RuntimePackage:
    root: str
    distribution: str
    allowed: frozenset[str]
    forbidden: frozenset[str]


@dataclass(frozen=True)
class RuntimePolicy:
    packages: Mapping[str, RuntimePackage]
    retired: tuple[str, ...]


def load_policy(raw: dict[str, Any]) -> RuntimePolicy:
    _reject_unknown_keys(raw, frozenset({"packages", "retired"}), "runtime policy")
    entries = raw.get("packages")
    if not isinstance(entries, dict) or not entries:
        raise ValueError("packages must be a non-empty table")
    packages = {}
    for name, entry in entries.items():
        if not name.isidentifier() or not isinstance(entry, dict):
            raise ValueError("each package must be a module name and table")
        _reject_unknown_keys(
            entry, frozenset({"root", "distribution", "allowed", "forbidden"}), "runtime package"
        )
        allowed = _modules(entry.get("allowed", []))
        if set(allowed) - entries.keys():
            raise ValueError(f"unknown allowed runtime package for {name}")
        packages[name] = RuntimePackage(
            _relative_package_path(entry.get("root"), "package.root"),
            _string(entry.get("distribution"), "package.distribution"),
            frozenset(allowed),
            frozenset(_modules(entry.get("forbidden", []))),
        )
    return RuntimePolicy(packages, tuple(_modules(raw.get("retired", []))))


def _modules(value: object) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str)
        or not item
        or not all(part.isidentifier() for part in item.split("."))
        for item in value
    ):
        raise ValueError("module lists must contain exact qualified names")
    return value


def runtime_distributions(lock: dict[str, Any], package: str) -> set[str]:
    pending: list[tuple[str, tuple[str, ...]]] = [(package, ())]
    visited: set[tuple[str, tuple[str, ...]]] = set()
    while pending:
        name, extras = pending.pop()
        if (name, extras) in visited:
            continue
        visited.add((name, extras))
        for entry in lock.get("package", []):
            if entry["name"] != name:
                continue
            dependencies = list(entry.get("dependencies", []))
            for extra in extras:
                dependencies.extend(entry.get("optional-dependencies", {}).get(extra, []))
            pending.extend(
                (dependency["name"], tuple(dependency.get("extra", [])))
                for dependency in dependencies
            )
    return {name for name, _ in visited}


def installed_module_providers() -> dict[str, set[str]]:
    providers: dict[str, set[str]] = {}
    for distribution in importlib.metadata.distributions():
        name = re.sub(r"[-_.]+", "-", distribution.metadata["Name"]).lower()
        for file in distribution.files or ():
            if file.suffix not in {".py", ".so", ".pyd"}:
                continue
            parts = [*file.parts[:-1], file.name.split(".")[0]]
            if parts[-1] == "__init__":
                parts.pop()
            if parts and all(part.isidentifier() for part in parts):
                for length in range(1, len(parts) + 1):
                    providers.setdefault(".".join(parts[:length]), set()).add(name)
    return providers


def dependency_violation(
    imported: str, allowed: set[str], providers: dict[str, set[str]], policy: RuntimePolicy
) -> str | None:
    namespace = imported.split(".")[0]
    if namespace in policy.packages or namespace in sys.stdlib_module_names:
        return None
    module = imported
    while module:
        candidates = providers.get(module)
        if candidates is not None:
            if candidates & allowed:
                return None
            return (
                f"PKG003 {imported} requires an undeclared runtime dependency "
                f"({', '.join(sorted(candidates))})"
            )
        module = module.rpartition(".")[0]
    return f"PKG003 cannot resolve runtime dependency for {imported}"


def type_checking_lines(tree: ast.Module) -> set[int]:
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        condition = node.test
        if (isinstance(condition, ast.Name) and condition.id == "TYPE_CHECKING") or (
            isinstance(condition, ast.Attribute)
            and isinstance(condition.value, ast.Name)
            and condition.value.id == "typing"
            and condition.attr == "TYPE_CHECKING"
        ):
            for statement in node.body:
                lines.update(
                    descendant.lineno
                    for descendant in ast.walk(statement)
                    if isinstance(descendant, ast.Import | ast.ImportFrom)
                )
    return lines


def imports(tree: ast.Module, module: str, *, initializer: bool) -> Iterable[tuple[int, str]]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                aliases[name.asname or name.name.split(".")[0]] = name.name
                yield node.lineno, name.name
        elif isinstance(node, ast.ImportFrom):
            prefix = node.module or ""
            if node.level:
                parent = module.split(".") if initializer else module.split(".")[:-1]
                prefix = ".".join(
                    [*parent[: len(parent) - node.level + 1], *prefix.split(".")]
                ).rstrip(".")
            yield node.lineno, prefix
            for name in node.names:
                qualified = f"{prefix}.{name.name}"
                aliases[name.asname or name.name] = qualified
                yield node.lineno, qualified
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        target = node.func
        callable_name = ""
        if isinstance(target, ast.Name):
            callable_name = aliases.get(target.id, target.id)
        elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
            callable_name = f"{aliases.get(target.value.id, target.value.id)}.{target.attr}"
        if callable_name not in {"importlib.import_module", "__import__"}:
            continue
        argument = node.args[0]
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            yield node.lineno, argument.value


def violations(
    source: str, owner: str, module: str, *, initializer: bool, policy: RuntimePolicy
) -> list[tuple[int, str]]:
    findings: set[tuple[int, str]] = set()
    for line, imported in imports(ast.parse(source), module, initializer=initializer):
        namespace = imported.split(".")[0]
        forbidden = namespace in policy.packages and namespace not in policy.packages[owner].allowed
        forbidden |= any(
            imported == name or imported.startswith(name + ".")
            for name in policy.packages[owner].forbidden
        )
        forbidden |= any(
            imported == old or imported.startswith(old + ".") for old in policy.retired
        )
        if forbidden:
            findings.add((line, f"PKG001 {owner} cannot import {imported}"))
        if namespace in policy.packages and any(
            part == "tests" or part.startswith("test_") or part.endswith("_test")
            for part in imported.split(".")[1:]
        ):
            findings.add((line, f"PKG002 production code cannot import test helper {imported}"))
    return sorted(findings)


def check(workspace: Path, policy: RuntimePolicy) -> list[str]:
    findings: list[str] = []
    lock_path = workspace / "uv.lock"
    lock = tomllib.loads(lock_path.read_text()) if lock_path.is_file() else None
    providers = installed_module_providers() if lock is not None else {}
    for owner, package in policy.packages.items():
        relative = package.root
        allowed = runtime_distributions(lock, package.distribution) if lock is not None else set()
        root = workspace / relative
        if not root.is_dir():
            findings.append(f"PKG001 missing package source: {relative}")
            continue
        for path in sorted(root.rglob("*.py")):
            if (
                path.name == "conftest.py"
                or path.name.startswith("test_")
                or path.name.endswith("_test.py")
                or "tests" in path.relative_to(root).parts
            ):
                continue
            relative_module = path.relative_to(root.parent).with_suffix("")
            module = ".".join(relative_module.parts).removesuffix(".__init__")
            for line, message in violations(
                path.read_text(),
                owner,
                module,
                initializer=path.name == "__init__.py",
                policy=policy,
            ):
                findings.append(f"{path.relative_to(workspace)}:{line}: {message}")
            if lock is not None:
                tree = ast.parse(path.read_text())
                type_only = type_checking_lines(tree)
                for line, imported in imports(
                    tree,
                    module,
                    initializer=path.name == "__init__.py",
                ):
                    if line in type_only:
                        continue
                    dependency_error = dependency_violation(imported, allowed, providers, policy)
                    if dependency_error:
                        findings.append(f"{path.relative_to(workspace)}:{line}: {dependency_error}")
    return sorted(set(findings))


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Check installed runtime package boundaries")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        policy = load_policy(tomllib.loads(args.config.read_text()))
        if not (args.workspace / "uv.lock").is_file():
            raise ValueError("runtime dependency checks require uv.lock")
        findings = check(args.workspace, policy)
    except (ValueError, OSError, SyntaxError) as error:
        parser.error(str(error))
    for finding in findings:
        print(finding)
    if not findings:
        print("Runtime package boundaries passed")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
