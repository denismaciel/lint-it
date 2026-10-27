from __future__ import annotations

import ast
from collections.abc import Iterable

from lint_it.architecture import Architecture
from lint_it.core import Finding, finding, normalized_filename
from lint_it.rules.shared.symbols import resolved_symbols


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _environment_prefix(node: ast.ClassDef) -> str | None:
    for statement in node.body:
        if not isinstance(statement, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id == "model_config"
            for target in statement.targets
        ):
            continue
        if not isinstance(statement.value, ast.Call):
            return None
        if _name(statement.value.func) != "SettingsConfigDict":
            return None
        for keyword in statement.value.keywords:
            if (
                keyword.arg == "env_prefix"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ):
                return keyword.value.value or None
    return None


class RuntimeSettingsRule:
    code = "PAL018"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        symbols = resolved_symbols(tree)
        runtime_model_names = {
            _name(node.returns)
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name in {"load_config", "load_settings"}
            and node.returns is not None
        }
        classes = []
        framework_settings = set()
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {name for base in node.bases for name in symbols.get(base, ())}
            if "pydantic_settings.BaseSettings" in bases:
                classes.append(node)
                framework_settings.add(node)
            elif "pydantic.BaseModel" in bases and node.name in runtime_model_names:
                classes.append(node)
        if not classes:
            return []

        findings: list[Finding] = []
        normalized = normalized_filename(filename)
        has_loader = any(
            isinstance(node, ast.FunctionDef) and node.name == "load_settings" for node in tree.body
        )
        for settings_class in classes:
            if not normalized.endswith("/app/config.py"):
                findings.append(
                    finding(
                        self,
                        filename,
                        settings_class,
                        "runtime settings must live in app/config.py",
                    )
                )
            if settings_class.name != "Settings":
                findings.append(
                    finding(
                        self,
                        filename,
                        settings_class,
                        "runtime settings class must be named Settings",
                    )
                )
            prefix = (
                _environment_prefix(settings_class)
                if settings_class in framework_settings
                else _module_environment_prefix(tree)
            )
            if prefix is None:
                findings.append(
                    finding(
                        self,
                        filename,
                        settings_class,
                        "runtime Settings must declare a non-empty env_prefix",
                    )
                )
            if not has_loader:
                findings.append(
                    finding(
                        self,
                        filename,
                        settings_class,
                        "runtime settings modules must expose load_settings()",
                    )
                )
        return findings


def _module_environment_prefix(tree: ast.Module) -> str | None:
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "ENV_PREFIX"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value or None
    return None
