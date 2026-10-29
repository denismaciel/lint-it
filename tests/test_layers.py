from __future__ import annotations

import pytest
from conftest import Project

from lint_it import reporting
from lint_it.loader import ManifestError
from lint_it.policy import Layer

WORKFLOW = "src/example/workflows/orders.py"
ACTIVITY = "src/example/workflows/activities.py"
SERVICE = "src/example/domains/orders/service.py"
REPOSITORY = "src/example/domains/orders/persistence/repository.py"
MODEL = "src/example/domains/orders/model.py"
ROUTER = "src/example/app/routers/orders.py"

WORKFLOW_LAYOUT = """
[workspace]
layout = "temporal"

[layers.workflow]
base = "router"
deterministic = true

[layouts.temporal]
extends = "domains"
layers = [
  { glob = "src/*/workflows/*.py", layer = "workflow" },
  { glob = "src/*/workflows/activities.py", layer = "transaction" },
]
"""


@pytest.fixture
def workflows(project: Project) -> Project:
    return project.manifest(WORKFLOW_LAYOUT)


def module(path: str) -> str:
    return path.removeprefix("src/").removesuffix(".py").replace("/", ".")


def test_custom_layer_classifies_by_name_and_follows_its_base(workflows: Project) -> None:
    workflows.write({WORKFLOW: ""})
    classification = workflows.load().classify(workflows.root / WORKFLOW)

    assert classification is not None
    assert (classification.name, classification.layer) == ("workflow", Layer.ROUTER)
    assert reporting.describe(WORKFLOW, classification, "temporal") == (
        f"{WORKFLOW}: workflow (a router) (temporal layout, src/*/workflows/*.py)"
    )


def test_custom_layer_gets_its_base_layer_rules(workflows: Project) -> None:
    assert workflows.lint(WORKFLOW, "client = PaymentClient()\n") == ["LIT303"]


def test_custom_layer_inherits_base_dependencies(workflows: Project) -> None:
    workflows.write({REPOSITORY: "VALUE = 1\n", ACTIVITY: "VALUE = 1\n"})

    assert workflows.lint(WORKFLOW, f"from {module(REPOSITORY)} import VALUE\n") == ["LIT101"]
    assert workflows.lint(WORKFLOW, f"from {module(ACTIVITY)} import VALUE\n") == []


def test_custom_layer_counts_as_its_base_when_imported(workflows: Project) -> None:
    workflows.write({WORKFLOW: "VALUE = 1\n"})

    # Routers may import routers, and a workflow is a router.
    assert workflows.lint(ROUTER, f"from {module(WORKFLOW)} import VALUE\n") == []
    [finding] = workflows.write({SERVICE: f"from {module(WORKFLOW)} import VALUE\n"}).findings(
        SERVICE
    )
    assert finding.message == f"shell cannot import workflow module {module(WORKFLOW)}"
    assert finding.target == module(WORKFLOW)


def test_custom_layer_dependencies_can_be_set(workflows: Project) -> None:
    workflows.write(
        {
            "lint-it.toml": WORKFLOW_LAYOUT + '\n[layer_dependencies]\nworkflow = ["core"]\n',
            MODEL: "VALUE = 1\n",
            ACTIVITY: "VALUE = 1\n",
        }
    )

    assert workflows.lint(WORKFLOW, f"from {module(MODEL)} import VALUE\n") == []
    assert workflows.lint(WORKFLOW, f"from {module(ACTIVITY)} import VALUE\n") == ["LIT101"]


def test_deterministic_layer_rejects_every_nondeterministic_source(workflows: Project) -> None:
    [finding] = workflows.write({WORKFLOW: "from uuid import uuid4\nID = uuid4()\n"}).findings(
        WORKFLOW
    )

    assert finding.code == "LIT201"
    assert (
        finding.message == "uuid.uuid4 hides nondeterminism; workflow modules must be deterministic"
    )


def test_custom_layer_inherits_forbidden_imports_and_extensions(project: Project) -> None:
    project.manifest(
        WORKFLOW_LAYOUT
        + """
        [forbidden_imports]
        router = ["sqlalchemy", "httpx"]

        [extend_forbidden_imports]
        "*" = ["legacy"]
        workflow = ["requests"]
        """
    )
    forbidden = project.load().policy.forbidden_imports

    assert forbidden["workflow"] == {"sqlalchemy", "httpx", "legacy", "requests"}
    assert forbidden[Layer.ROUTER] == {"sqlalchemy", "httpx", "legacy"}


def test_forbidden_calls_match_resolved_names(workflows: Project) -> None:
    workflows.manifest(
        WORKFLOW_LAYOUT + '\n[forbidden_calls]\nworkflow = ["time.sleep", "asyncio.*"]\n'
    )
    [first, second] = workflows.write(
        {
            WORKFLOW: """
            import asyncio
            from time import sleep as pause

            async def run():
                pause(1)
                await asyncio.sleep(1)
            """
        }
    ).findings(WORKFLOW)

    assert (first.code, first.message) == ("LIT306", "workflow modules cannot call time.sleep")
    assert (second.target, second.line) == ("asyncio.sleep", 7)
    assert workflows.lint(ROUTER, "import time\ntime.sleep(1)\n") == []


def test_forbidden_calls_are_inherited_from_the_base_layer(workflows: Project) -> None:
    workflows.manifest(WORKFLOW_LAYOUT + '\n[forbidden_calls]\nrouter = ["time.sleep"]\n')

    assert workflows.lint(WORKFLOW, "import time\ntime.sleep(1)\n") == ["LIT306"]


def test_allowed_dependencies_admit_named_modules_for_listed_layers(project: Project) -> None:
    project.manifest(
        """
        [[allowed_dependencies]]
        layers = ["shell"]
        modules = ["example.domains.orders.persistence.*"]
        reason = "Repositories are the persistence port until domains split"
        """
    )
    project.write({REPOSITORY: "VALUE = 1\n"})

    assert project.lint(SERVICE, f"from {module(REPOSITORY)} import VALUE\n") == []
    assert project.lint(ROUTER, f"from {module(REPOSITORY)} import VALUE\n") == ["LIT101"]


def test_allowed_dependencies_without_layers_apply_everywhere(project: Project) -> None:
    project.manifest(
        f"""
        [[allowed_dependencies]]
        modules = ["{module(REPOSITORY)}"]
        reason = "Shared repository"
        """
    )
    project.write({REPOSITORY: "VALUE = 1\n"})

    assert project.lint(ROUTER, f"from {module(REPOSITORY)} import VALUE\n") == []


def test_allowed_dependency_matching_no_module_is_stale(project: Project) -> None:
    project.manifest(
        """
        [[allowed_dependencies]]
        modules = ["example.gone"]
        reason = "Removed long ago"
        """
    )
    project.write({MODEL: ""})

    assert [item.message for item in project.findings() if item.code == "LIT003"] == [
        "allowed dependency matches no workspace module: example.gone"
    ]


def test_custom_layout_globs_win_over_conventions_but_not_markers(project: Project) -> None:
    project.manifest(
        """
        [workspace]
        layout = "mine"

        [layouts.mine]
        layers = [
          { glob = "src/**/*.py", layer = "shell" },
          { glob = "tests/fixtures/**/*.py", layer = "boundary" },
        ]
        """
    )
    project.write(
        {"tests/fixtures/data.py": "", "tests/test_orders.py": "", "src/example/__init__.py": ""}
    )
    workspace = project.load()

    def layer(path: str) -> str | None:
        classification = workspace.classify(project.root / path)
        return None if classification is None else classification.name

    assert layer("tests/fixtures/data.py") == "boundary"
    assert layer("tests/test_orders.py") == "test"
    assert layer("src/example/__init__.py") == "marker"


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        ("[layers.core]\nbase = 'shell'", "layers.core must be a new layer name"),
        ("[layers.flow]\nbase = 'kernel'", "layers.flow.base must be one of"),
        ("[layers.flow]\nbase = 'marker'", "layers.flow.base cannot be marker"),
        ("[layers.flow]\nbase = 'router'\nfast = true", "unknown layers.flow field: fast"),
        ("[layers.flow]\nbase = 'router'\ndeterministic = 1", "deterministic must be true"),
        ('[layer_dependencies]\nflow = ["core"]', "layer_dependencies key must be one of"),
        ('[forbidden_calls]\ncore = ["time sleep"]', "forbidden_calls.core must contain"),
        (
            '[[allowed_dependencies]]\nmodules = []\nreason = "x"',
            "allowed_dependencies.modules must name at least one module",
        ),
        (
            '[[allowed_dependencies]]\nmodules = ["example.x"]',
            "allowed_dependencies.reason must be a non-empty string",
        ),
        (
            '[[allowed_dependencies]]\nlayers = ["flow"]\nmodules = ["example.x"]\nreason = "x"',
            "allowed_dependencies.layers must be one of",
        ),
    ],
)
def test_invalid_layer_configuration_names_the_problem(
    project: Project, manifest: str, message: str
) -> None:
    project.manifest(manifest)
    with pytest.raises(ManifestError, match=message):
        project.load()
