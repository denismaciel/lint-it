from dataclasses import replace
from pathlib import Path

import pytest

from lint_it.architecture import (
    Architecture,
    Classification,
    ClassificationOrigin,
    Layer,
    LayerPattern,
    PackageRole,
)
from lint_it.filesystem import (
    workspace_architecture,
    workspace_project_roots,
    workspace_python_files,
)


def test_linter_workspace_has_complete_project_and_file_coverage() -> None:
    workspace = Path(__file__).resolve().parents[1]
    architecture = workspace_architecture(workspace)

    assert architecture.packages
    assert {package.root for package in architecture.packages} == workspace_project_roots(workspace)
    assert all(
        architecture.classify(path) is not None for path in workspace_python_files(architecture)
    )


def test_new_source_location_is_unclassified_until_manifested(tmp_path: Path) -> None:
    package = tmp_path / "app"
    package.mkdir()
    (package / "pyproject.toml").write_text('[project]\nname="app"\nversion="1"\n')
    source = package / "outside.py"
    source.write_text("value = 1\n")
    (tmp_path / "lint-it.toml").write_text("")

    assert workspace_architecture(tmp_path).classify(source) is None


def _write_project(root: Path, name: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "1"\n')


def _write_python(root: Path, relative: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("value = 1\n")
    return path


def _classification(architecture: Architecture, path: Path) -> Classification:
    classification = architecture.classify(path)
    assert classification is not None
    return classification


def test_manifest_discovers_projects_and_applies_role_profiles(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path, "example")
    support = tmp_path / "packages" / "support"
    _write_project(support, "support")
    tooling = tmp_path / "packages" / "tooling"
    _write_project(tooling, "tooling")
    marker = _write_python(tmp_path, "src/example/__init__.py")
    app = _write_python(tmp_path, "src/example/app/main.py")
    core = _write_python(tmp_path, "src/example/domains/orders/core.py")
    repository = _write_python(tmp_path, "src/example/domains/orders/persistence/repository.py")
    test = _write_python(tmp_path, "tests/domains/orders/test_core.py")
    port = _write_python(support, "src/support/ports.py")
    tooling_cli = _write_python(tooling, "src/tooling/cli.py")
    tooling_core = _write_python(tooling, "src/tooling/core.py")
    (tmp_path / "lint-it.toml").write_text(
        """
[workspace]
default_profile = "application"

[[packages]]
path = "packages/support"
profile = "infrastructure"

[[packages]]
path = "packages/tooling"
profile = "tooling"
""".strip()
    )

    architecture = workspace_architecture(tmp_path)

    assert len(architecture.packages) == 3
    assert _classification(architecture, marker).layer is Layer.PACKAGE_MARKER
    assert _classification(architecture, app).layer is Layer.BOUNDARY
    assert _classification(architecture, core).layer is Layer.FUNCTIONAL_CORE
    assert _classification(architecture, repository).layer is Layer.ADAPTER
    assert _classification(architecture, test).layer is Layer.TEST_SHELL
    assert _classification(architecture, port).layer is Layer.PORT
    assert _classification(architecture, port).package.role is PackageRole.INFRASTRUCTURE
    assert _classification(architecture, tooling_cli).layer is Layer.BOUNDARY
    assert _classification(architecture, tooling_core).layer is Layer.FUNCTIONAL_CORE
    assert _classification(architecture, core).origin is ClassificationOrigin.DEFAULT


def test_manifest_classifies_nested_domain_features_and_projections(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path, "example")
    nested_core = _write_python(
        tmp_path,
        "src/example/domains/orders/approval/core.py",
    )
    nested_port = _write_python(
        tmp_path,
        "src/example/domains/orders/approval/ports.py",
    )
    projection = _write_python(
        tmp_path,
        "src/example/projections/order_summary/model.py",
    )
    projection_repository = _write_python(
        tmp_path,
        "src/example/projections/order_summary/persistence/repository.py",
    )
    (tmp_path / "lint-it.toml").write_text("")

    architecture = workspace_architecture(tmp_path)

    assert _classification(architecture, nested_core).layer is Layer.FUNCTIONAL_CORE
    assert _classification(architecture, nested_port).layer is Layer.PORT
    assert _classification(architecture, projection).layer is Layer.FUNCTIONAL_CORE
    assert _classification(architecture, projection_repository).layer is Layer.ADAPTER


def test_manifest_rejects_noncanonical_path_without_override(tmp_path: Path) -> None:
    _write_project(tmp_path, "example")
    source = _write_python(tmp_path, "src/example/orders.py")
    (tmp_path / "lint-it.toml").write_text("")

    assert workspace_architecture(tmp_path).classify(source) is None


def test_manifest_applies_audited_narrow_override(tmp_path: Path) -> None:
    _write_project(tmp_path, "example")
    source = _write_python(tmp_path, "src/example/orders.py")
    (tmp_path / "lint-it.toml").write_text(
        """
[workspace]
override_budget = 1

[[overrides]]
package = "."
glob = "src/example/orders.py"
layer = "imperative-shell"
reason = "Move this legacy module after the layout engine lands"
issue = "PERSONAL-1"
""".strip()
    )

    architecture = workspace_architecture(tmp_path)
    classification = architecture.classify(source)

    assert classification is not None
    assert classification.layer is Layer.IMPERATIVE_SHELL
    assert classification.origin is ClassificationOrigin.OVERRIDE
    assert architecture.configuration_errors([source]) == ()


def test_manifest_enforces_override_file_budget(tmp_path: Path) -> None:
    _write_project(tmp_path, "example")
    first = _write_python(tmp_path, "src/example/legacy/first.py")
    second = _write_python(tmp_path, "src/example/legacy/second.py")
    (tmp_path / "lint-it.toml").write_text(
        """
[workspace]
override_budget = 1

[[overrides]]
package = "."
glob = "src/example/legacy/*.py"
layer = "imperative-shell"
reason = "Legacy area is being migrated"
issue = "PERSONAL-1"
""".strip()
    )

    errors = workspace_architecture(tmp_path).configuration_errors([first, second])

    assert any("override budget exceeded" in error for error in errors)


@pytest.mark.parametrize("missing", ["reason", "issue"])
def test_manifest_requires_override_audit_metadata(tmp_path: Path, missing: str) -> None:
    _write_project(tmp_path, "example")
    values = {
        "reason": 'reason = "Legacy module"',
        "issue": 'issue = "PERSONAL-1"',
    }
    values[missing] = ""
    (tmp_path / "lint-it.toml").write_text(
        f"""
[workspace]
override_budget = 3

[[overrides]]
package = "."
glob = "src/example/orders.py"
layer = "imperative-shell"
{values["reason"]}
{values["issue"]}
""".strip()
    )

    with pytest.raises(ValueError, match=f"override.{missing}"):
        workspace_architecture(tmp_path)


def test_manifest_rejects_workspace_wide_override(tmp_path: Path) -> None:
    _write_project(tmp_path, "example")
    (tmp_path / "lint-it.toml").write_text(
        """
[[overrides]]
package = "."
glob = "src/**/*.py"
layer = "imperative-shell"
reason = "Too broad"
issue = "PERSONAL-1"
""".strip()
    )

    with pytest.raises(ValueError, match="too broad"):
        workspace_architecture(tmp_path)


def test_manifest_reports_stale_and_overlapping_overrides(tmp_path: Path) -> None:
    _write_project(tmp_path, "example")
    source = _write_python(tmp_path, "src/example/orders.py")
    (tmp_path / "lint-it.toml").write_text(
        """
[[overrides]]
package = "."
glob = "src/example/orders.py"
layer = "imperative-shell"
reason = "Legacy module"
issue = "PERSONAL-1"

[[overrides]]
package = "."
glob = "src/example/orders.py"
layer = "boundary"
reason = "Conflicting classification"
issue = "PERSONAL-2"

[[overrides]]
package = "."
glob = "src/example/missing.py"
layer = "boundary"
reason = "Already migrated"
issue = "PERSONAL-3"
""".strip()
    )

    architecture = workspace_architecture(tmp_path)
    errors = architecture.configuration_errors([source])

    assert architecture.classify(source) is None
    assert any("overlapping layout overrides" in error for error in errors)
    assert any("stale layout override" in error for error in errors)


def test_manifest_rejects_explicit_layer_maps(tmp_path: Path) -> None:
    _write_project(tmp_path, "example")
    (tmp_path / "lint-it.toml").write_text(
        """
[[packages]]
path = "."
profile = "application"
layers = [{ glob = "src/**/*.py", layer = "imperative-shell" }]
""".strip()
    )

    with pytest.raises(ValueError, match="select profiles, not layer maps"):
        workspace_architecture(tmp_path)


def test_manifest_rejects_unknown_configuration_fields(tmp_path: Path) -> None:
    _write_project(tmp_path, "example")
    (tmp_path / "lint-it.toml").write_text(
        """
[workspace]
default_profile = "application"
override_buget = 2
""".strip()
    )

    with pytest.raises(ValueError, match="unknown workspace field: override_buget"):
        workspace_architecture(tmp_path)


def test_manifest_rejects_version_field(tmp_path: Path) -> None:
    _write_project(tmp_path, "example")
    (tmp_path / "lint-it.toml").write_text('version = "2"\n')

    with pytest.raises(ValueError, match="unknown manifest field: version"):
        workspace_architecture(tmp_path)


def test_manifest_validates_dependency_override_paths_and_budget(tmp_path: Path) -> None:
    _write_project(tmp_path, "example")
    _write_python(tmp_path, "src/example/domains/orders/core.py")
    (tmp_path / "lint-it.toml").write_text(
        """
[workspace]
dependency_override_budget = 0

[[dependency_overrides]]
package = "."
importer = "src/example/domains/orders/core.py"
imported = "src/example/app/missing.py"
reason = "Temporary dependency inversion"
issue = "PERSONAL-1"
""".strip()
    )

    architecture = workspace_architecture(tmp_path)
    errors = architecture.configuration_errors([tmp_path / "src/example/domains/orders/core.py"])

    assert any("stale dependency override imported" in error for error in errors)
    assert any("dependency override budget exceeded" in error for error in errors)


def test_workspace_index_preserves_nested_package_ownership_and_unparsed_paths(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path, "example")
    nested = tmp_path / "packages/support"
    _write_project(nested, "support")
    core = _write_python(nested, "src/support/domains/orders/core.py")
    (tmp_path / "lint-it.toml").write_text("")
    architecture = workspace_architecture(tmp_path)

    assert _classification(architecture, core).package.root == nested
    assert architecture.classify(core.relative_to(tmp_path)) == architecture.classify(core)
    assert architecture.module_name(core) == "support.domains.orders.core"
    assert architecture.index.modules["support.domains.orders.core"].path == core
    unparsed = core.with_name("model.py")
    assert _classification(architecture, unparsed).layer is Layer.FUNCTIONAL_CORE
    package = architecture.package_for(unparsed)
    assert package is not None
    assert package.root == nested


def test_replacing_snapshot_packages_reclassifies_sources(tmp_path: Path) -> None:
    _write_project(tmp_path, "example")
    core = _write_python(tmp_path, "src/example/domains/orders/core.py")
    (tmp_path / "lint-it.toml").write_text("")
    original = workspace_architecture(tmp_path)
    changed = replace(
        original,
        packages=(
            replace(
                original.packages[0],
                layers=(LayerPattern("src/**/*.py", Layer.BOUNDARY),),
            ),
        ),
    )

    assert _classification(original, core).layer is Layer.FUNCTIONAL_CORE
    assert _classification(changed, core).layer is Layer.BOUNDARY


@pytest.mark.parametrize("profile", ["infrastructure", "hexagonal-application"])
def test_development_entrypoints_and_examples_are_boundaries(tmp_path: Path, profile: str) -> None:
    _write_project(tmp_path, "example")
    development = _write_python(tmp_path, "src/example/development.py")
    example = _write_python(tmp_path, "examples/usage.py")
    model = _write_python(tmp_path, "src/example/model.py")
    (tmp_path / "lint-it.toml").write_text(f'[[packages]]\npath = "."\nprofile = "{profile}"\n')
    architecture = workspace_architecture(tmp_path)

    assert _classification(architecture, development).layer is Layer.BOUNDARY
    assert _classification(architecture, example).layer is Layer.BOUNDARY
    assert _classification(architecture, model).layer is Layer.FUNCTIONAL_CORE
