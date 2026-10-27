from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from lint_it.config_values import (
    enum_value,
    non_empty_string,
    non_negative_int,
    reject_unknown_keys,
    relative_path,
    string_list,
)
from lint_it.globs import matches_glob
from lint_it.layouts import BUILT_IN, COMMON, LayerPattern
from lint_it.policy import FORBIDDEN_IMPORTS, LAYER_DEPENDENCIES, Layer, Policy

DEFAULT_POLICY = Policy()
MANIFEST = "lint-it.toml"
IGNORED_DIRECTORIES = frozenset(
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


class Kind(StrEnum):
    """What a package is to the rest of the workspace."""

    SERVER = "server"
    CLIENT = "client"
    LIBRARY = "library"


class Origin(StrEnum):
    LAYOUT = "layout"
    OVERRIDE = "override"


@dataclass(frozen=True)
class LayoutOverride:
    glob: str
    layer: Layer
    reason: str
    issue: str


@dataclass(frozen=True)
class DependencyOverride:
    importer: str
    imported: str
    reason: str
    issue: str


@dataclass(frozen=True)
class Package:
    root: Path
    kind: Kind
    layout: str
    layers: tuple[LayerPattern, ...]
    overrides: tuple[LayoutOverride, ...] = ()
    dependency_overrides: tuple[DependencyOverride, ...] = ()


@dataclass(frozen=True)
class Classification:
    package: Package
    layer: Layer
    origin: Origin
    glob: str


@dataclass(frozen=True)
class Source:
    path: Path
    tree: ast.Module
    module: str | None = None


@dataclass(frozen=True)
class ParseFailure:
    path: Path
    line: int
    column: int
    message: str


@dataclass(frozen=True)
class WorkspaceIndex:
    packages: Mapping[Path, Package | None]
    classifications: Mapping[Path, Classification | None]
    sources: Mapping[Path, Source]
    modules: Mapping[str, Source]
    module_names: Mapping[Path, str]
    server_modules: frozenset[str]


@dataclass(frozen=True)
class Workspace:
    """An immutable snapshot: configuration, packages and parsed sources."""

    root: Path
    packages: tuple[Package, ...]
    policy: Policy = DEFAULT_POLICY
    manifest: Path | None = None
    sources: tuple[Source, ...] = ()
    parse_failures: tuple[ParseFailure, ...] = ()
    override_budget: int = 0
    dependency_override_budget: int = 0
    index: WorkspaceIndex = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        packages: dict[Path, Package | None] = {}
        classifications: dict[Path, Classification | None] = {}
        sources: dict[Path, Source] = {}
        modules: dict[str, Source] = {}
        for source in self.sources:
            package = self._owner(source.path)
            packages[source.path] = package
            classifications[source.path] = _classification(source.path, package)
            sources.setdefault(source.path, source)
            module = source.module if source.module is not None else _module(source.path, package)
            if module is not None:
                modules[module] = source
        object.__setattr__(
            self,
            "index",
            WorkspaceIndex(
                packages=MappingProxyType(packages),
                classifications=MappingProxyType(classifications),
                sources=MappingProxyType(sources),
                modules=MappingProxyType(modules),
                module_names=MappingProxyType({item.path: name for name, item in modules.items()}),
                server_modules=frozenset(
                    name.split(".")[0]
                    for name, source in modules.items()
                    if (package := packages[source.path]) is not None
                    and package.kind is Kind.SERVER
                ),
            ),
        )

    def _owner(self, path: Path) -> Package | None:
        owners = [package for package in self.packages if path.is_relative_to(package.root)]
        return max(owners, key=lambda package: len(package.root.parts)) if owners else None

    def absolute(self, path: str | Path) -> Path:
        path = Path(path)
        return path if path.is_absolute() else self.root / path

    def package_for(self, path: str | Path) -> Package | None:
        path = self.absolute(path)
        if path in self.index.packages:
            return self.index.packages[path]
        return self._owner(path)

    def classify(self, path: str | Path) -> Classification | None:
        path = self.absolute(path)
        if path in self.index.classifications:
            return self.index.classifications[path]
        return _classification(path, self.package_for(path))

    def module_name(self, path: str | Path) -> str | None:
        path = self.absolute(path)
        return _module(path, self.package_for(path))

    def dependency_override_for(self, importer: Path, imported: Path) -> DependencyOverride | None:
        package = self.package_for(importer)
        if package is None or not imported.is_relative_to(package.root):
            return None
        pair = (
            importer.relative_to(package.root).as_posix(),
            imported.relative_to(package.root).as_posix(),
        )
        return next(
            (
                item
                for item in package.dependency_overrides
                if (item.importer, item.imported) == pair
            ),
            None,
        )

    def configuration_errors(self) -> tuple[str, ...]:
        """Problems with overrides and budgets, judged against the snapshot's files."""
        files = (*self.index.sources, *(failure.path for failure in self.parse_failures))
        errors: list[str] = []
        overridden: set[Path] = set()
        for package in self.packages:
            owned = tuple(path for path in files if self._owner(path) is package)
            relative = {path.relative_to(package.root).as_posix(): path for path in owned}
            location = package.root.relative_to(self.root).as_posix()
            pairs: set[tuple[str, str]] = set()
            for dependency in package.dependency_overrides:
                pair = (dependency.importer, dependency.imported)
                if pair in pairs:
                    errors.append(
                        f"duplicate dependency override in {location}: "
                        f"{dependency.importer} -> {dependency.imported}"
                    )
                pairs.add(pair)
                errors.extend(
                    f"stale dependency override {role} in {location}: {target}"
                    for role, target in (
                        ("importer", dependency.importer),
                        ("imported", dependency.imported),
                    )
                    if target not in relative
                )
            for override in package.overrides:
                matched = {
                    path for name, path in relative.items() if matches_glob(name, override.glob)
                }
                if not matched:
                    errors.append(f"stale layout override in {location}: {override.glob}")
                overridden |= matched
            for name in sorted(relative):
                globs = [item.glob for item in package.overrides if matches_glob(name, item.glob)]
                if len(globs) > 1:
                    errors.append(f"overlapping layout overrides for {name}: {', '.join(globs)}")
        if len(overridden) > self.override_budget:
            errors.append(
                f"layout override budget exceeded: {len(overridden)} files use overrides, "
                f"budget is {self.override_budget}"
            )
        dependency_overrides = sum(len(package.dependency_overrides) for package in self.packages)
        if dependency_overrides > self.dependency_override_budget:
            errors.append(
                f"dependency override budget exceeded: {dependency_overrides} edges use "
                f"overrides, budget is {self.dependency_override_budget}"
            )
        return tuple(sorted(errors))


def _module(path: Path, package: Package | None) -> str | None:
    if package is None or not path.is_relative_to(package.root / "src"):
        return None
    parts = path.relative_to(package.root / "src").with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _classification(path: Path, package: Package | None) -> Classification | None:
    if package is None:
        return None
    relative = path.relative_to(package.root).as_posix()
    overrides = [item for item in package.overrides if matches_glob(relative, item.glob)]
    if len(overrides) > 1:
        return None
    if overrides:
        override = overrides[0]
        return Classification(package, override.layer, Origin.OVERRIDE, override.glob)
    pattern = next(
        (item for item in reversed(package.layers) if matches_glob(relative, item.glob)), None
    )
    if pattern is None:
        return None
    return Classification(package, pattern.layer, Origin.LAYOUT, pattern.glob)


def _python_glob(value: object, field: str) -> str:
    glob = relative_path(value, field)
    if not glob.endswith(".py"):
        raise ValueError(f"{field} must select Python files: {glob}")
    return glob


def _override_glob(value: object) -> str:
    glob = _python_glob(value, "override.glob")
    wildcard = next((index for index, character in enumerate(glob) if character in "*?["), None)
    if wildcard is not None and len(PurePosixPath(glob[:wildcard].rstrip("/")).parts) < 3:
        raise ValueError(f"override.glob is too broad; scope it below a package area: {glob}")
    return glob


def _qualified_names(value: object, field: str) -> frozenset[str]:
    names = string_list(value, field)
    invalid = [name for name in names if not all(part.isidentifier() for part in name.split("."))]
    if invalid:
        raise ValueError(f"{field} must contain qualified Python names: {', '.join(invalid)}")
    return frozenset(names)


def _table(raw: Mapping[str, object], key: str) -> dict[str, object]:
    value = raw.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a table")
    return value


def _tables(raw: Mapping[str, object], key: str) -> list[dict[str, object]]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{key} must be an array of tables")
    return value


def _layouts(raw: dict[str, object]) -> dict[str, tuple[LayerPattern, ...]]:
    layouts = dict(BUILT_IN)
    for name, entry in raw.items():
        if name in layouts or not isinstance(entry, dict):
            raise ValueError(f"layout {name} must be a table and cannot redefine a built-in")
        reject_unknown_keys(entry, frozenset({"extends", "layers"}), f"layouts.{name}")
        base: tuple[LayerPattern, ...] = ()
        if "extends" in entry:
            parent = non_empty_string(entry["extends"], f"layouts.{name}.extends")
            if parent not in BUILT_IN:
                raise ValueError(
                    f"layouts.{name}.extends must be one of: {', '.join(BUILT_IN)}; got {parent!r}"
                )
            base = BUILT_IN[parent]
        entries = entry.get("layers")
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"layouts.{name}.layers must be a non-empty array")
        patterns = []
        for layer_entry in entries:
            if not isinstance(layer_entry, dict):
                raise ValueError(f"layouts.{name}.layers entries must be tables")
            reject_unknown_keys(layer_entry, frozenset({"glob", "layer"}), f"layouts.{name}.layers")
            patterns.append(
                LayerPattern(
                    _python_glob(layer_entry.get("glob"), f"layouts.{name}.layers.glob"),
                    enum_value(Layer, layer_entry.get("layer"), f"layouts.{name}.layers.layer"),
                )
            )
        layouts[name] = (*base, *patterns)
    return {name: (*patterns, *COMMON) for name, patterns in layouts.items()}


def _policy(raw: dict[str, object], workspace: dict[str, object]) -> Policy:
    dependencies = dict(LAYER_DEPENDENCIES)
    for name, value in _table(raw, "layer_dependencies").items():
        layer = enum_value(Layer, name, "layer_dependencies key")
        if value == "*":
            dependencies.pop(layer, None)
        else:
            dependencies[layer] = frozenset(
                enum_value(Layer, item, f"layer_dependencies.{name}")
                for item in string_list(value, f"layer_dependencies.{name}")
            )
    forbidden = dict(FORBIDDEN_IMPORTS)
    for name, value in _table(raw, "forbidden_imports").items():
        layer = enum_value(Layer, name, "forbidden_imports key")
        forbidden[layer] = _qualified_names(value, f"forbidden_imports.{name}")
    for name, value in _table(raw, "extend_forbidden_imports").items():
        extra = _qualified_names(value, f"extend_forbidden_imports.{name}")
        layers = (
            tuple(Layer)
            if name == "*"
            else (enum_value(Layer, name, "extend_forbidden_imports key"),)
        )
        for layer in layers:
            forbidden[layer] = forbidden.get(layer, frozenset()) | extra
    conventions = _table(raw, "conventions")
    reject_unknown_keys(
        conventions, frozenset({"predicate_prefixes", "outcome_suffixes"}), "conventions"
    )
    defaults = DEFAULT_POLICY
    return Policy(
        layer_dependencies=MappingProxyType(dependencies),
        forbidden_imports=MappingProxyType(forbidden),
        predicate_prefixes=tuple(
            string_list(conventions["predicate_prefixes"], "conventions.predicate_prefixes")
        )
        if "predicate_prefixes" in conventions
        else defaults.predicate_prefixes,
        outcome_suffixes=tuple(
            string_list(conventions["outcome_suffixes"], "conventions.outcome_suffixes")
        )
        if "outcome_suffixes" in conventions
        else defaults.outcome_suffixes,
        effectful_types=_qualified_names(
            workspace.get("effectful_types", []), "workspace.effectful_types"
        ),
        clock_modules=_qualified_names(
            workspace.get("clock_modules", []), "workspace.clock_modules"
        ),
    )


def load_manifest(
    root: Path,
    raw: dict[str, object],
    project_roots: frozenset[Path],
    manifest: Path | None = None,
) -> Workspace:
    """Build a source-less snapshot from parsed manifest data; raises ValueError."""
    reject_unknown_keys(
        raw,
        frozenset(
            {
                "workspace",
                "packages",
                "layouts",
                "layer_dependencies",
                "forbidden_imports",
                "extend_forbidden_imports",
                "conventions",
                "overrides",
                "dependency_overrides",
            }
        ),
        "manifest",
    )
    workspace = _table(raw, "workspace")
    reject_unknown_keys(
        workspace,
        frozenset(
            {
                "kind",
                "layout",
                "effectful_types",
                "clock_modules",
                "override_budget",
                "dependency_override_budget",
            }
        ),
        "workspace",
    )
    if not project_roots:
        raise ValueError(f"no pyproject.toml found under {root}")
    layouts = _layouts(_table(raw, "layouts"))
    default_kind = enum_value(Kind, workspace.get("kind", "server"), "workspace.kind")
    default_layout = _layout_name(workspace.get("layout", "domains"), "workspace.layout", layouts)

    configured: dict[Path, tuple[Kind, str]] = {}
    for entry in _tables(raw, "packages"):
        reject_unknown_keys(entry, frozenset({"path", "kind", "layout"}), "packages")
        package_root = root / relative_path(entry.get("path"), "packages.path")
        if package_root in configured:
            raise ValueError(f"duplicate package entry: {package_root.relative_to(root)}")
        if package_root not in project_roots:
            raise ValueError(f"package has no pyproject.toml: {package_root.relative_to(root)}")
        configured[package_root] = (
            enum_value(Kind, entry.get("kind", default_kind), "packages.kind"),
            _layout_name(entry.get("layout", default_layout), "packages.layout", layouts),
        )

    overrides: dict[Path, list[LayoutOverride]] = {}
    for entry in _tables(raw, "overrides"):
        reject_unknown_keys(
            entry, frozenset({"package", "glob", "layer", "reason", "issue"}), "overrides"
        )
        package_root = _package_root(root, entry, "overrides", project_roots)
        overrides.setdefault(package_root, []).append(
            LayoutOverride(
                glob=_override_glob(entry.get("glob")),
                layer=enum_value(Layer, entry.get("layer"), "overrides.layer"),
                reason=non_empty_string(entry.get("reason"), "overrides.reason"),
                issue=non_empty_string(entry.get("issue"), "overrides.issue"),
            )
        )

    dependency_overrides: dict[Path, list[DependencyOverride]] = {}
    for entry in _tables(raw, "dependency_overrides"):
        reject_unknown_keys(
            entry,
            frozenset({"package", "importer", "imported", "reason", "issue"}),
            "dependency_overrides",
        )
        package_root = _package_root(root, entry, "dependency_overrides", project_roots)
        dependency_overrides.setdefault(package_root, []).append(
            DependencyOverride(
                importer=_python_glob(entry.get("importer"), "dependency_overrides.importer"),
                imported=_python_glob(entry.get("imported"), "dependency_overrides.imported"),
                reason=non_empty_string(entry.get("reason"), "dependency_overrides.reason"),
                issue=non_empty_string(entry.get("issue"), "dependency_overrides.issue"),
            )
        )

    packages = []
    for package_root in sorted(project_roots):
        kind, layout = configured.get(package_root, (default_kind, default_layout))
        packages.append(
            Package(
                root=package_root,
                kind=kind,
                layout=layout,
                layers=layouts[layout],
                overrides=tuple(overrides.get(package_root, ())),
                dependency_overrides=tuple(dependency_overrides.get(package_root, ())),
            )
        )
    return Workspace(
        root=root,
        packages=tuple(packages),
        policy=_policy(raw, workspace),
        manifest=manifest,
        override_budget=non_negative_int(
            workspace.get("override_budget", 0), "workspace.override_budget"
        ),
        dependency_override_budget=non_negative_int(
            workspace.get("dependency_override_budget", 0), "workspace.dependency_override_budget"
        ),
    )


def _layout_name(value: object, field: str, layouts: Mapping[str, object]) -> str:
    name = non_empty_string(value, field)
    if name not in layouts:
        raise ValueError(f"{field} must be one of: {', '.join(layouts)}; got {name!r}")
    return name


def _package_root(
    root: Path, entry: dict[str, object], table: str, project_roots: frozenset[Path]
) -> Path:
    package_root = root / relative_path(entry.get("package", "."), f"{table}.package")
    if package_root not in project_roots:
        raise ValueError(f"{table}.package has no pyproject.toml: {package_root.relative_to(root)}")
    return package_root
