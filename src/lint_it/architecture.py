from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType


class PackageRole(StrEnum):
    APPLICATION = "application"
    CONTRACTS = "contracts"
    DOMAIN_LIBRARY = "domain-library"
    HEXAGONAL_APPLICATION = "hexagonal-application"
    INFRASTRUCTURE = "infrastructure"
    SDK = "sdk"
    TEST_SUPPORT = "test-support"
    TOOLING = "tooling"


class Layer(StrEnum):
    ADAPTER = "adapter"
    BOUNDARY = "boundary"
    FUNCTIONAL_CORE = "functional-core"
    IMPERATIVE_SHELL = "imperative-shell"
    MIGRATION = "migration"
    PACKAGE_MARKER = "package-marker"
    PORT = "port"
    TEST_SHELL = "test-shell"
    TRANSACTION_BOUNDARY = "transaction-boundary"


class ClassificationOrigin(StrEnum):
    DEFAULT = "default"
    OVERRIDE = "override"


@dataclass(frozen=True)
class LayerPattern:
    glob: str
    layer: Layer


@dataclass(frozen=True)
class LayoutOverride:
    glob: str
    issue: str
    layer: Layer
    reason: str


@dataclass(frozen=True)
class DependencyOverride:
    imported: str
    importer: str
    issue: str
    reason: str


@dataclass(frozen=True)
class Package:
    root: Path
    role: PackageRole
    layers: tuple[LayerPattern, ...]
    dependency_overrides: tuple[DependencyOverride, ...] = ()
    overrides: tuple[LayoutOverride, ...] = ()


@dataclass(frozen=True)
class Classification:
    package: Package
    layer: Layer
    origin: ClassificationOrigin


@dataclass(frozen=True)
class Source:
    path: Path
    tree: ast.Module
    module: str | None = None


@dataclass(frozen=True)
class WorkspaceIndex:
    ordered_packages: tuple[Package, ...]
    packages: Mapping[Path, Package | None]
    classifications: Mapping[Path, Classification | None]
    sources: Mapping[Path, Source]
    modules: Mapping[str, Source]
    module_names: Mapping[Path, str]


@dataclass(frozen=True)
class Architecture:
    root: Path
    packages: tuple[Package, ...]
    sources: tuple[Source, ...] = ()
    effectful_types: frozenset[str] = frozenset()
    clock_modules: frozenset[str] = frozenset()
    dependency_override_budget: int | None = None
    override_budget: int | None = None
    index: WorkspaceIndex = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        ordered_packages = tuple(
            sorted(self.packages, key=lambda item: len(item.root.parts), reverse=True)
        )
        packages: dict[Path, Package | None] = {}
        classifications: dict[Path, Classification | None] = {}
        sources: dict[Path, Source] = {}
        modules: dict[str, Source] = {}
        for source in self.sources:
            path = source.path
            package = next(
                (item for item in ordered_packages if path.is_relative_to(item.root)), None
            )
            packages[path] = package
            classifications[path] = _classification(path, package)
            sources.setdefault(path, source)
            module = source.module if source.module is not None else _module_name(path, package)
            if module is not None:
                modules[module] = source
        object.__setattr__(
            self,
            "index",
            WorkspaceIndex(
                ordered_packages=ordered_packages,
                packages=MappingProxyType(packages),
                classifications=MappingProxyType(classifications),
                sources=MappingProxyType(sources),
                modules=MappingProxyType(modules),
                module_names=MappingProxyType({item.path: name for name, item in modules.items()}),
            ),
        )

    def package_for(self, filename: str | Path) -> Package | None:
        path = Path(filename)
        path = (self.root / path) if not path.is_absolute() else path
        if path in self.index.packages:
            return self.index.packages[path]
        return next(
            (
                package
                for package in self.index.ordered_packages
                if path.is_relative_to(package.root)
            ),
            None,
        )

    def dependency_override_for(
        self,
        importer: Path,
        imported: Path,
    ) -> DependencyOverride | None:
        package = self.package_for(importer)
        if package is None or not imported.is_relative_to(package.root):
            return None
        importer_path = importer.relative_to(package.root).as_posix()
        imported_path = imported.relative_to(package.root).as_posix()
        return next(
            (
                override
                for override in package.dependency_overrides
                if override.importer == importer_path and override.imported == imported_path
            ),
            None,
        )

    def classify(self, filename: str | Path) -> Classification | None:
        path = Path(filename)
        path = (self.root / path) if not path.is_absolute() else path
        if path in self.index.classifications:
            return self.index.classifications[path]
        return _classification(path, self.package_for(path))

    def module_name(self, path: Path) -> str | None:
        return _module_name(path, self.package_for(path))

    def configuration_errors(self, filenames: list[Path]) -> tuple[str, ...]:
        errors: list[str] = []
        overridden_files: set[Path] = set()
        for package in self.packages:
            nested_roots = tuple(
                candidate.root
                for candidate in self.packages
                if candidate is not package
                and len(candidate.root.parts) > len(package.root.parts)
                and candidate.root.is_relative_to(package.root)
            )
            package_files = tuple(
                path
                for path in filenames
                if path.is_relative_to(package.root)
                and not any(path.is_relative_to(root) for root in nested_roots)
            )
            package_relative_files = {
                path.relative_to(package.root).as_posix() for path in package_files
            }
            dependency_pairs: set[tuple[str, str]] = set()
            for dependency_override in package.dependency_overrides:
                pair = (dependency_override.importer, dependency_override.imported)
                if pair in dependency_pairs:
                    errors.append(
                        "duplicate dependency override in "
                        f"{package.root}: {dependency_override.importer} -> "
                        f"{dependency_override.imported}"
                    )
                dependency_pairs.add(pair)
                for field_name, dependency_path in (
                    ("importer", dependency_override.importer),
                    ("imported", dependency_override.imported),
                ):
                    if dependency_path not in package_relative_files:
                        errors.append(
                            f"stale dependency override {field_name} in "
                            f"{package.root}: {dependency_path}"
                        )
            for layout_override in package.overrides:
                path_matches = tuple(
                    path
                    for path in package_files
                    if PurePosixPath(path.relative_to(package.root).as_posix()).full_match(
                        layout_override.glob
                    )
                )
                if not path_matches:
                    errors.append(
                        f"stale layout override in {package.root}: {layout_override.glob}"
                    )
                overridden_files.update(path_matches)
            for path in package_files:
                relative = PurePosixPath(path.relative_to(package.root).as_posix())
                override_matches = tuple(
                    override for override in package.overrides if relative.full_match(override.glob)
                )
                if len(override_matches) > 1:
                    errors.append(
                        f"overlapping layout overrides for {path}: "
                        + ", ".join(override.glob for override in override_matches)
                    )
        if self.override_budget is not None and len(overridden_files) > self.override_budget:
            errors.append(
                f"layout override budget exceeded: {len(overridden_files)} files "
                f"use overrides, budget is {self.override_budget}"
            )
        dependency_override_count = sum(
            len(package.dependency_overrides) for package in self.packages
        )
        if (
            self.dependency_override_budget is not None
            and dependency_override_count > self.dependency_override_budget
        ):
            errors.append(
                "dependency override budget exceeded: "
                f"{dependency_override_count} edges use overrides, "
                f"budget is {self.dependency_override_budget}"
            )
        return tuple(sorted(errors))


def _module_name(path: Path, package: Package | None) -> str | None:
    if package is None or not path.is_relative_to(package.root / "src"):
        return None
    parts = path.relative_to(package.root / "src").with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _classification(path: Path, package: Package | None) -> Classification | None:
    if package is None:
        return None
    relative_path = PurePosixPath(path.relative_to(package.root).as_posix())
    matching_overrides = tuple(
        override for override in package.overrides if relative_path.full_match(override.glob)
    )
    if len(matching_overrides) > 1:
        return None
    if matching_overrides:
        matching_override = next(iter(matching_overrides))
        return Classification(
            package=package,
            layer=matching_override.layer,
            origin=ClassificationOrigin.OVERRIDE,
        )
    layer = next(
        (
            pattern.layer
            for pattern in reversed(package.layers)
            if relative_path.full_match(pattern.glob)
        ),
        None,
    )
    if layer is None:
        return None
    return Classification(package=package, layer=layer, origin=ClassificationOrigin.DEFAULT)


CONFIG_FILENAME = "lint-it.toml"
IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".direnv",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "target",
    }
)

_COMMON_PATTERNS = (
    LayerPattern("conftest.py", Layer.TEST_SHELL),
    LayerPattern("tests/**/*.py", Layer.TEST_SHELL),
    LayerPattern("scripts/**/*.py", Layer.BOUNDARY),
    LayerPattern("examples/**/*.py", Layer.BOUNDARY),
    LayerPattern("migrations/**/*.py", Layer.MIGRATION),
    LayerPattern("src/**/__init__.py", Layer.PACKAGE_MARKER),
)

_DOMAIN_PATTERNS = (
    LayerPattern("src/*/domains/**/boundary.py", Layer.BOUNDARY),
    LayerPattern("src/*/domains/**/model.py", Layer.FUNCTIONAL_CORE),
    LayerPattern("src/*/domains/**/core.py", Layer.FUNCTIONAL_CORE),
    LayerPattern("src/*/domains/**/policy.py", Layer.FUNCTIONAL_CORE),
    LayerPattern("src/*/domains/**/event.py", Layer.FUNCTIONAL_CORE),
    LayerPattern("src/*/domains/**/ports.py", Layer.PORT),
    LayerPattern("src/*/domains/**/service.py", Layer.IMPERATIVE_SHELL),
    LayerPattern("src/*/domains/**/persistence/**/*.py", Layer.ADAPTER),
)

_PROJECTION_PATTERNS = (
    LayerPattern("src/*/projections/**/model.py", Layer.FUNCTIONAL_CORE),
    LayerPattern("src/*/projections/**/ports.py", Layer.PORT),
    LayerPattern("src/*/projections/**/service.py", Layer.IMPERATIVE_SHELL),
    LayerPattern("src/*/projections/**/persistence/**/*.py", Layer.ADAPTER),
)

_SHARED_PATTERNS = (
    LayerPattern("src/*/shared/model.py", Layer.FUNCTIONAL_CORE),
    LayerPattern("src/*/shared/core.py", Layer.FUNCTIONAL_CORE),
    LayerPattern("src/*/shared/policy.py", Layer.FUNCTIONAL_CORE),
    LayerPattern("src/*/shared/ports.py", Layer.PORT),
    LayerPattern("src/*/shared/persistence/**/*.py", Layer.ADAPTER),
)

_APPLICATION_PATTERNS = (
    *_DOMAIN_PATTERNS,
    *_PROJECTION_PATTERNS,
    *_SHARED_PATTERNS,
    LayerPattern("src/*/app/**/*.py", Layer.BOUNDARY),
    LayerPattern("src/*/app/dependencies.py", Layer.TRANSACTION_BOUNDARY),
    LayerPattern("src/*/integrations/**/*.py", Layer.ADAPTER),
    LayerPattern("src/*/integrations/unit_of_work/**/*.py", Layer.TRANSACTION_BOUNDARY),
)

_HEXAGONAL_APPLICATION_PATTERNS = (
    LayerPattern("src/*/*.py", Layer.FUNCTIONAL_CORE),
    LayerPattern("src/*/domain/**/*.py", Layer.FUNCTIONAL_CORE),
    LayerPattern("src/*/domain/**/ports.py", Layer.PORT),
    LayerPattern("src/*/application/**/*.py", Layer.IMPERATIVE_SHELL),
    LayerPattern("src/*/application/**/ports.py", Layer.PORT),
    LayerPattern("src/*/application/**/errors.py", Layer.FUNCTIONAL_CORE),
    LayerPattern("src/*/application/**/*_errors.py", Layer.FUNCTIONAL_CORE),
    LayerPattern("src/*/adapters/**/*.py", Layer.ADAPTER),
    LayerPattern("src/*/adapters/**/database.py", Layer.TRANSACTION_BOUNDARY),
    LayerPattern("src/*/web/**/*.py", Layer.BOUNDARY),
    LayerPattern("src/*/app/**/*.py", Layer.BOUNDARY),
    LayerPattern("src/*/config.py", Layer.BOUNDARY),
    LayerPattern("src/*/development.py", Layer.BOUNDARY),
    LayerPattern("src/*/main.py", Layer.BOUNDARY),
    LayerPattern("src/*/worker.py", Layer.BOUNDARY),
    LayerPattern("src/*/canary.py", Layer.BOUNDARY),
    LayerPattern("src/*/ops.py", Layer.BOUNDARY),
    LayerPattern("src/*/clock.py", Layer.ADAPTER),
    LayerPattern("src/*/banner.py", Layer.ADAPTER),
    LayerPattern("src/*/components.py", Layer.ADAPTER),
    LayerPattern("src/*/utils.py", Layer.ADAPTER),
)

_INFRASTRUCTURE_PATTERNS = (
    LayerPattern("src/*/model.py", Layer.FUNCTIONAL_CORE),
    LayerPattern("src/*/core.py", Layer.FUNCTIONAL_CORE),
    LayerPattern("src/*/policy.py", Layer.FUNCTIONAL_CORE),
    LayerPattern("src/*/ports.py", Layer.PORT),
    LayerPattern("src/*/adapters/**/*.py", Layer.ADAPTER),
    LayerPattern("src/*/runtime.py", Layer.IMPERATIVE_SHELL),
    LayerPattern("src/*/service.py", Layer.IMPERATIVE_SHELL),
    LayerPattern("src/*/development.py", Layer.BOUNDARY),
)

_TOOLING_PATTERNS = (
    LayerPattern("src/**/*.py", Layer.IMPERATIVE_SHELL),
    LayerPattern("src/*/cli.py", Layer.BOUNDARY),
    LayerPattern("src/*/architecture.py", Layer.FUNCTIONAL_CORE),
    LayerPattern("src/*/core.py", Layer.FUNCTIONAL_CORE),
    LayerPattern("src/*/imports.py", Layer.FUNCTIONAL_CORE),
    LayerPattern("src/*/rules/**/*.py", Layer.FUNCTIONAL_CORE),
)

_PROFILE_PATTERNS = MappingProxyType(
    {
        PackageRole.APPLICATION: _APPLICATION_PATTERNS,
        PackageRole.CONTRACTS: (LayerPattern("src/**/*.py", Layer.BOUNDARY),),
        PackageRole.DOMAIN_LIBRARY: (*_DOMAIN_PATTERNS, *_SHARED_PATTERNS),
        PackageRole.HEXAGONAL_APPLICATION: _HEXAGONAL_APPLICATION_PATTERNS,
        PackageRole.INFRASTRUCTURE: _INFRASTRUCTURE_PATTERNS,
        PackageRole.SDK: (LayerPattern("src/**/*.py", Layer.BOUNDARY),),
        PackageRole.TEST_SUPPORT: (LayerPattern("src/**/*.py", Layer.TEST_SHELL),),
        PackageRole.TOOLING: _TOOLING_PATTERNS,
    }
)


def _profile_patterns(role: PackageRole) -> tuple[LayerPattern, ...]:
    return (*_PROFILE_PATTERNS[role], *_COMMON_PATTERNS)


def _relative_package_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must be a relative path inside the workspace")
    return path.as_posix()


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _reject_unknown_keys(value: dict[str, object], allowed: frozenset[str], field: str) -> None:
    unknown = sorted(value.keys() - allowed)
    if unknown:
        raise ValueError(f"unknown {field} field: {', '.join(unknown)}")


def _override_glob(value: object) -> str:
    glob = _relative_package_path(value, "override.glob")
    if ".py" not in glob:
        raise ValueError("override.glob must select Python files")
    wildcard_positions = tuple(index for index, character in enumerate(glob) if character in "*?[")
    prefix = glob[: min(wildcard_positions)].rstrip("/") if wildcard_positions else glob
    if wildcard_positions and len(PurePosixPath(prefix).parts) < 3:
        raise ValueError(f"override.glob is too broad; scope it below a package area: {glob}")
    return glob


def load_manifest(
    root: Path, raw: dict[str, object], project_roots: frozenset[Path]
) -> Architecture:
    _reject_unknown_keys(
        raw,
        frozenset({"workspace", "packages", "overrides", "dependency_overrides", "profiles"}),
        "manifest",
    )
    workspace = raw.get("workspace", {})
    if not isinstance(workspace, dict):
        raise ValueError("workspace must be a table")
    _reject_unknown_keys(
        workspace,
        frozenset(
            {
                "default_profile",
                "effectful_types",
                "clock_modules",
                "dependency_override_budget",
                "override_budget",
            }
        ),
        "workspace",
    )
    effectful_types = workspace.get("effectful_types", [])
    if not isinstance(effectful_types, list) or any(
        not isinstance(item, str)
        or "." not in item
        or not all(part.isidentifier() for part in item.split("."))
        for item in effectful_types
    ):
        raise ValueError("workspace.effectful_types must be an array of qualified type names")
    clock_modules = workspace.get("clock_modules", [])
    if not isinstance(clock_modules, list) or any(
        not isinstance(item, str) or not all(part.isidentifier() for part in item.split("."))
        for item in clock_modules
    ):
        raise ValueError("workspace.clock_modules must be an array of exact module names")
    profiles = {role.value: (role, _profile_patterns(role)) for role in PackageRole}
    custom_profiles = raw.get("profiles", {})
    if not isinstance(custom_profiles, dict):
        raise ValueError("profiles must be a table")
    for name, profile in custom_profiles.items():
        if name in profiles or not isinstance(profile, dict):
            raise ValueError(f"invalid or duplicate profile: {name}")
        _reject_unknown_keys(profile, frozenset({"role", "layers"}), "profile")
        role = PackageRole(_string(profile.get("role"), "profile.role"))
        layers = profile.get("layers")
        if not isinstance(layers, list) or not layers:
            raise ValueError("profile.layers must be a non-empty array")
        patterns = []
        for entry in layers:
            if not isinstance(entry, dict):
                raise ValueError("profile layer must be a table")
            _reject_unknown_keys(entry, frozenset({"glob", "layer"}), "profile layer")
            glob = _relative_package_path(entry.get("glob"), "profile layer.glob")
            if not glob.endswith(".py"):
                raise ValueError("profile layer.glob must select Python files")
            patterns.append(
                LayerPattern(glob, Layer(_string(entry.get("layer"), "profile layer.layer")))
            )
        profiles[name] = (role, (*patterns, *_COMMON_PATTERNS))
    default_profile = _string(workspace.get("default_profile", "application"), "default_profile")
    if default_profile not in profiles:
        raise ValueError(f"unknown profile: {default_profile}")
    override_budget = _non_negative_int(
        workspace.get("override_budget", 0), "workspace.override_budget"
    )
    dependency_override_budget = _non_negative_int(
        workspace.get("dependency_override_budget", 0),
        "workspace.dependency_override_budget",
    )
    if not project_roots:
        raise ValueError("workspace contains no pyproject.toml")

    configured: dict[Path, str] = {}
    entries = raw.get("packages", [])
    if not isinstance(entries, list):
        raise ValueError("packages must be an array of tables")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("each package entry must be a table")
        _reject_unknown_keys(entry, frozenset({"path", "profile", "layers"}), "package")
        if "layers" in entry:
            raise ValueError("package entries select profiles, not layer maps")
        relative = _relative_package_path(entry.get("path"), "package.path")
        package_root = root / relative
        if package_root in configured:
            raise ValueError(f"duplicate package configuration: {relative}")
        profile_name = _string(entry.get("profile", default_profile), "package.profile")
        if profile_name not in profiles:
            raise ValueError(f"unknown profile: {profile_name}")
        configured[package_root] = profile_name

    unknown = sorted(configured.keys() - project_roots)
    if unknown:
        raise ValueError(
            "configured package has no pyproject.toml: " + ", ".join(str(path) for path in unknown)
        )

    overrides_by_package: dict[Path, list[LayoutOverride]] = {}
    overrides = raw.get("overrides", [])
    if not isinstance(overrides, list):
        raise ValueError("overrides must be an array of tables")
    for entry in overrides:
        if not isinstance(entry, dict):
            raise ValueError("each override must be a table")
        _reject_unknown_keys(
            entry,
            frozenset({"package", "glob", "layer", "reason", "issue"}),
            "override",
        )
        relative = _relative_package_path(entry.get("package"), "override.package")
        package_root = root / relative
        if package_root not in project_roots:
            raise ValueError(f"override package has no pyproject.toml: {relative}")
        overrides_by_package.setdefault(package_root, []).append(
            LayoutOverride(
                glob=_override_glob(entry.get("glob")),
                issue=_string(entry.get("issue"), "override.issue"),
                layer=Layer(_string(entry.get("layer"), "override.layer")),
                reason=_string(entry.get("reason"), "override.reason"),
            )
        )

    dependency_overrides_by_package: dict[Path, list[DependencyOverride]] = {}
    dependency_overrides = raw.get("dependency_overrides", [])
    if not isinstance(dependency_overrides, list):
        raise ValueError("dependency_overrides must be an array of tables")
    for entry in dependency_overrides:
        if not isinstance(entry, dict):
            raise ValueError("each dependency override must be a table")
        _reject_unknown_keys(
            entry,
            frozenset({"package", "importer", "imported", "reason", "issue"}),
            "dependency override",
        )
        relative = _relative_package_path(
            entry.get("package"),
            "dependency_override.package",
        )
        package_root = root / relative
        if package_root not in project_roots:
            raise ValueError(f"dependency override package has no pyproject.toml: {relative}")
        importer = _relative_package_path(
            entry.get("importer"),
            "dependency_override.importer",
        )
        imported = _relative_package_path(
            entry.get("imported"),
            "dependency_override.imported",
        )
        if not importer.endswith(".py") or not imported.endswith(".py"):
            raise ValueError("dependency override paths must select Python files")
        dependency_overrides_by_package.setdefault(package_root, []).append(
            DependencyOverride(
                imported=imported,
                importer=importer,
                issue=_string(entry.get("issue"), "dependency_override.issue"),
                reason=_string(entry.get("reason"), "dependency_override.reason"),
            )
        )

    packages = tuple(
        Package(
            root=package_root,
            role=profiles[configured.get(package_root, default_profile)][0],
            layers=profiles[configured.get(package_root, default_profile)][1],
            dependency_overrides=tuple(dependency_overrides_by_package.get(package_root, ())),
            overrides=tuple(overrides_by_package.get(package_root, ())),
        )
        for package_root in sorted(project_roots)
    )
    return Architecture(
        root=root,
        packages=packages,
        effectful_types=frozenset(effectful_types),
        clock_modules=frozenset(clock_modules),
        dependency_override_budget=dependency_override_budget,
        override_budget=override_budget,
    )


def classification_for(filename: str, architecture: Architecture | None) -> Classification | None:
    return None if architecture is None else architecture.classify(filename)


def has_layer(filename: str, architecture: Architecture | None, *layers: Layer) -> bool | None:
    classification = classification_for(filename, architecture)
    return None if classification is None else classification.layer in layers
