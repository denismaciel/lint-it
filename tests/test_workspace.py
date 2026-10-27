from __future__ import annotations

from dataclasses import replace

import pytest
from conftest import Project

from lint_it import engine
from lint_it.layouts import LayerPattern
from lint_it.loader import ManifestError
from lint_it.policy import FORBIDDEN_IMPORTS, Layer
from lint_it.rules.registry import ALL_RULES
from lint_it.workspace import Kind, Origin


def layer_of(project: Project, path: str) -> Layer | None:
    project.write({path: ""})
    classification = project.load().classify(project.root / path)
    return None if classification is None else classification.layer


@pytest.mark.parametrize(
    ("path", "layer"),
    [
        ("src/example/__init__.py", Layer.MARKER),
        ("src/example/__main__.py", Layer.BOUNDARY),
        ("src/example/app/main.py", Layer.BOUNDARY),
        ("src/example/app/config.py", Layer.BOUNDARY),
        ("src/example/app/routers/orders.py", Layer.ROUTER),
        ("src/example/app/router/orders.py", Layer.ROUTER),
        ("src/example/app/api/orders_router.py", Layer.ROUTER),
        ("src/example/app/router.py", Layer.ROUTER),
        ("src/example/app/dependencies.py", Layer.TRANSACTION),
        ("src/example/domains/orders/core.py", Layer.CORE),
        ("src/example/domains/orders/model.py", Layer.CORE),
        ("src/example/domains/orders/approval/policy.py", Layer.CORE),
        ("src/example/domains/orders/ports.py", Layer.PORT),
        ("src/example/domains/orders/service.py", Layer.SHELL),
        ("src/example/domains/orders/boundary.py", Layer.BOUNDARY),
        ("src/example/domains/orders/persistence/repository.py", Layer.ADAPTER),
        ("src/example/projections/summary/model.py", Layer.CORE),
        ("src/example/projections/summary/persistence/queries.py", Layer.ADAPTER),
        ("src/example/shared/model.py", Layer.CORE),
        ("src/example/integrations/payments.py", Layer.ADAPTER),
        ("src/example/integrations/unit_of_work/sql.py", Layer.TRANSACTION),
        ("tests/domains/orders/test_core.py", Layer.TEST),
        ("conftest.py", Layer.TEST),
        ("scripts/backfill.py", Layer.BOUNDARY),
        ("examples/usage.py", Layer.BOUNDARY),
        ("migrations/versions/0001.py", Layer.TRANSACTION),
        ("src/example/orders.py", None),
        ("src/example/domains/orders/repository.py", None),
        ("setup.py", None),
    ],
)
def test_default_manifest_uses_the_domains_layout(
    project: Project, path: str, layer: Layer | None
) -> None:
    assert layer_of(project, path) == layer


@pytest.mark.parametrize(
    ("layout", "path", "layer"),
    [
        ("hexagonal", "src/example/rules.py", Layer.CORE),
        ("hexagonal", "src/example/domain/orders/ports.py", Layer.PORT),
        ("hexagonal", "src/example/application/orders.py", Layer.SHELL),
        ("hexagonal", "src/example/application/orders_errors.py", Layer.CORE),
        ("hexagonal", "src/example/adapters/sql/database.py", Layer.TRANSACTION),
        ("hexagonal", "src/example/web/routes.py", Layer.BOUNDARY),
        ("hexagonal", "src/example/development.py", Layer.BOUNDARY),
        ("flat", "src/example/anything/at/all.py", Layer.SHELL),
        ("flat", "src/example/model.py", Layer.CORE),
        ("flat", "src/example/ports.py", Layer.PORT),
        ("flat", "src/example/adapters/http.py", Layer.ADAPTER),
        ("flat", "src/example/cli.py", Layer.BOUNDARY),
        ("flat", "examples/usage.py", Layer.BOUNDARY),
        ("boundary", "src/example/schemas.py", Layer.BOUNDARY),
        ("test-support", "src/example/fakes.py", Layer.TEST),
    ],
)
def test_built_in_layouts(project: Project, layout: str, path: str, layer: Layer) -> None:
    project.manifest(f'[workspace]\nlayout = "{layout}"\n')
    assert layer_of(project, path) is layer


def test_packages_select_kind_and_layout(project: Project) -> None:
    project.package("packages/sdk", "sdk").package("packages/tools", "tools").manifest(
        """
        [workspace]
        kind = "server"

        [[packages]]
        path = "packages/sdk"
        kind = "client"
        layout = "boundary"

        [[packages]]
        path = "packages/tools"
        kind = "library"
        layout = "flat"
        """
    )
    workspace = project.load()
    kinds = {
        package.root.relative_to(project.root).as_posix(): (package.kind, package.layout)
        for package in workspace.packages
    }
    assert kinds == {
        ".": (Kind.SERVER, "domains"),
        "packages/sdk": (Kind.CLIENT, "boundary"),
        "packages/tools": (Kind.LIBRARY, "flat"),
    }


def test_nested_packages_own_their_files(project: Project) -> None:
    project.package("packages/support", "support").write(
        {"packages/support/src/support/domains/orders/core.py": ""}
    )
    workspace = project.load()
    core = project.root / "packages/support/src/support/domains/orders/core.py"
    package = workspace.package_for(core)

    assert package is not None and package.root == project.root / "packages/support"
    assert workspace.module_name(core) == "support.domains.orders.core"
    assert workspace.index.modules["support.domains.orders.core"].path == core
    assert workspace.classify(core.relative_to(project.root)) == workspace.classify(core)


def test_custom_layout_extends_a_built_in(project: Project) -> None:
    project.manifest(
        """
        [workspace]
        layout = "orders"

        [layouts.orders]
        extends = "hexagonal"
        layers = [{ glob = "src/*/clock.py", layer = "adapter" }]
        """
    )
    assert layer_of(project, "src/example/clock.py") is Layer.ADAPTER
    assert layer_of(project, "src/example/web/app.py") is Layer.BOUNDARY
    assert layer_of(project, "tests/test_clock.py") is Layer.TEST


def test_custom_layout_without_base_only_knows_its_globs(project: Project) -> None:
    project.manifest(
        """
        [workspace]
        layout = "mine"

        [layouts.mine]
        layers = [{ glob = "src/*/decisions.py", layer = "core" }]
        """
    )
    assert layer_of(project, "src/example/decisions.py") is Layer.CORE
    assert layer_of(project, "src/example/domains/orders/core.py") is None


def test_classification_records_the_matching_pattern(project: Project) -> None:
    project.write({"src/example/domains/orders/core.py": ""})
    classification = project.load().classify(project.root / "src/example/domains/orders/core.py")

    assert classification is not None
    assert classification.origin is Origin.LAYOUT
    assert classification.glob == "src/*/domains/**/core.py"


def test_replacing_packages_reclassifies_sources(project: Project) -> None:
    project.write({"src/example/domains/orders/core.py": ""})
    original = project.load()
    changed = replace(
        original,
        packages=(
            replace(original.packages[0], layers=(LayerPattern("src/**/*.py", Layer.BOUNDARY),)),
        ),
    )
    core = project.root / "src/example/domains/orders/core.py"
    before, after = original.classify(core), changed.classify(core)
    assert before is not None and before.layer is Layer.CORE
    assert after is not None and after.layer is Layer.BOUNDARY


OVERRIDE = """
[[overrides]]
glob = "{glob}"
layer = "{layer}"
reason = "Legacy module waiting for the orders split"
issue = "EX-1"
"""


def test_override_reclassifies_one_file(project: Project) -> None:
    project.manifest(
        "[workspace]\noverride_budget = 1\n"
        + OVERRIDE.format(glob="src/example/orders.py", layer="shell")
    )
    project.write({"src/example/orders.py": ""})
    classification = project.load().classify(project.root / "src/example/orders.py")

    assert classification is not None
    assert (classification.layer, classification.origin) == (Layer.SHELL, Origin.OVERRIDE)
    assert project.findings() == []


def test_override_budget_counts_files(project: Project) -> None:
    project.manifest(
        "[workspace]\noverride_budget = 1\n"
        + OVERRIDE.format(glob="src/example/legacy/*.py", layer="shell")
    )
    project.write({"src/example/legacy/first.py": "", "src/example/legacy/second.py": ""})
    [problem] = project.findings()

    assert (problem.filename, problem.line, problem.code) == ("lint-it.toml", 1, "LIT003")
    assert "override budget exceeded: 2 files use overrides, budget is 1" in problem.message


def test_stale_and_overlapping_overrides_are_findings(project: Project) -> None:
    project.manifest(
        "[workspace]\noverride_budget = 5\n"
        + OVERRIDE.format(glob="src/example/orders.py", layer="shell")
        + OVERRIDE.format(glob="src/example/orders.py", layer="boundary")
        + OVERRIDE.format(glob="src/example/missing.py", layer="boundary")
    )
    project.write({"src/example/orders.py": ""})
    messages = [item.message for item in project.findings() if item.code == "LIT003"]

    assert project.load().classify(project.root / "src/example/orders.py") is None
    assert any("overlapping layout overrides for src/example/orders.py" in m for m in messages)
    assert any("stale layout override in .: src/example/missing.py" in m for m in messages)
    assert project.codes("src/example/orders.py") == ["LIT002"]


def test_dependency_overrides_are_validated(project: Project) -> None:
    project.manifest(
        """
        [[dependency_overrides]]
        importer = "src/example/domains/orders/core.py"
        imported = "src/example/app/missing.py"
        reason = "Temporary inversion"
        issue = "EX-1"
        """
    )
    project.write({"src/example/domains/orders/core.py": ""})
    messages = [item.message for item in project.findings()]

    assert any("stale dependency override imported" in message for message in messages)
    assert any("dependency override budget exceeded" in message for message in messages)


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        ('version = "2"', "unknown manifest field: version"),
        ("[workspace]\noverride_buget = 2", "unknown workspace field: override_buget"),
        ('[workspace]\nkind = "service"', "workspace.kind must be one of: server, client"),
        ('[workspace]\nlayout = "web"', "workspace.layout must be one of: domains, hexagonal"),
        ('[[packages]]\npath = "packages/missing"', "package has no pyproject.toml"),
        ("[[packages]]\npath = '../elsewhere'", "packages.path must be a relative path"),
        ("[layouts.flat]\nlayers = []", "cannot redefine a built-in"),
        ("[layouts.mine]\nlayers = []", "layouts.mine.layers must be a non-empty array"),
        ('[layouts.mine]\nextends = "web"\nlayers = [1]', "layouts.mine.extends must be one of"),
        (
            "[layouts.mine]\nlayers = [{ glob = 'src/a.py', layer = 'functional-core' }]",
            "layouts.mine.layers.layer must be one of: core, port, shell",
        ),
        (
            "[layouts.mine]\nlayers = [{ glob = 'src/a.txt', layer = 'core' }]",
            "must select Python files",
        ),
        (
            OVERRIDE.format(glob="src/**/*.py", layer="shell"),
            "override.glob is too broad",
        ),
        (
            OVERRIDE.format(glob="src/example/a.py", layer="shell").replace("EX-1", ""),
            "overrides.issue must be a non-empty string",
        ),
        ('[workspace]\neffectful_types = ["x.*"]', "workspace.effectful_types must contain"),
        ("[workspace]\nclock_modules = [1]", "workspace.clock_modules must be an array"),
        ('[layer_dependencies]\ncore = ["kernel"]', "layer_dependencies.core must be one of"),
        ('[forbidden_imports]\nwidget = ["x"]', "forbidden_imports key must be one of"),
        (
            '[extend_forbidden_imports]\nwidget = ["x"]',
            "extend_forbidden_imports key must be one of",
        ),
        ("[conventions]\nprefixes = []", "unknown conventions field: prefixes"),
        ("[workspace\n", "Expected ']'"),
    ],
)
def test_invalid_manifests_name_the_problem(project: Project, manifest: str, message: str) -> None:
    project.manifest(manifest)
    with pytest.raises(ManifestError, match=message.replace("[", r"\[").replace("*", r"\*")):
        project.load()


def test_workspace_without_projects_is_a_manifest_error(tmp_path) -> None:
    with pytest.raises(ManifestError, match=r"no pyproject\.toml"):
        Project(tmp_path).load()


def test_policy_sections_replace_built_in_entries(project: Project) -> None:
    project.manifest(
        """
        [layer_dependencies]
        shell = "*"
        core = ["core"]

        [forbidden_imports]
        router = []
        shell = ["boto3"]

        [conventions]
        predicate_prefixes = ["is_"]
        outcome_suffixes = ["Missing"]
        """
    )
    policy = project.load().policy

    assert Layer.SHELL not in policy.layer_dependencies
    assert policy.layer_dependencies[Layer.CORE] == {Layer.CORE}
    assert policy.layer_dependencies[Layer.ADAPTER] == {Layer.CORE, Layer.PORT, Layer.ADAPTER}
    assert policy.forbidden_imports[Layer.ROUTER] == frozenset()
    assert policy.forbidden_imports[Layer.SHELL] == {"boto3"}
    assert "httpx" in policy.forbidden_imports[Layer.CORE]
    assert (policy.predicate_prefixes, policy.outcome_suffixes) == (("is_",), ("Missing",))


def test_extend_forbidden_imports_adds_to_every_named_layer(project: Project) -> None:
    project.manifest(
        """
        [forbidden_imports]
        shell = ["boto3"]

        [extend_forbidden_imports]
        "*" = ["legacy"]
        shell = ["redis"]
        """
    )
    forbidden = project.load().policy.forbidden_imports

    assert forbidden[Layer.SHELL] == {"boto3", "legacy", "redis"}
    assert forbidden[Layer.CORE] == FORBIDDEN_IMPORTS[Layer.CORE] | {"legacy"}
    assert all("legacy" in forbidden[layer] for layer in Layer)


def test_snapshot_is_independent_of_later_edits(project: Project) -> None:
    project.write({"src/example/domains/orders/core.py": "import httpx\n"})
    snapshot = project.load()
    (project.root / "src/example/domains/orders/core.py").write_text("")
    (project.root / "pyproject.toml").unlink()

    assert [item.code for item in engine.check(snapshot, ALL_RULES)] == ["LIT102"]
