from __future__ import annotations

import pytest
from conftest import Project

from lint_it.loader import ManifestError

BILLING = "src/example/domains/billing/service.py"
BILLING_CORE = "src/example/domains/billing/core.py"
BILLING_REPOSITORY = "src/example/domains/billing/persistence/repository.py"
ORDERS_CORE = "src/example/domains/orders/core.py"
ORDERS_MODEL = "src/example/domains/orders/model.py"
ORDERS_SERVICE = "src/example/domains/orders/service.py"
ORDERS_PORTS = "src/example/domains/orders/ports.py"
ORDERS_BOUNDARY = "src/example/domains/orders/boundary.py"
ORDERS_REPOSITORY = "src/example/domains/orders/persistence/repository.py"
BILLING_DEPENDS_ON_ORDERS = '[domains]\nbilling = ["orders"]\norders = []\n'


def module(path: str) -> str:
    return path.removeprefix("src/").removesuffix(".py").replace("/", ".")


def importing(project: Project, importer: str, target: str) -> list[str]:
    project.write({target: "VALUE = 1\n"})
    return [
        item.message
        for item in project.write({importer: f"from {module(target)} import VALUE\n"}).findings(
            importer
        )
        if item.code == "LIT104"
    ]


@pytest.mark.parametrize("target", [ORDERS_CORE, ORDERS_MODEL, ORDERS_SERVICE])
def test_declared_dependency_allows_public_modules(project: Project, target: str) -> None:
    project.manifest(BILLING_DEPENDS_ON_ORDERS)
    assert importing(project, BILLING, target) == []


def test_undeclared_dependency_is_reported(project: Project) -> None:
    assert importing(project, BILLING, ORDERS_SERVICE) == [
        "billing domain cannot import example.domains.orders.service: "
        "orders is not in domains.billing"
    ]


def test_dependencies_point_one_way(project: Project) -> None:
    project.manifest(BILLING_DEPENDS_ON_ORDERS)
    assert importing(project, "src/example/domains/orders/service.py", BILLING_CORE) == [
        "orders domain cannot import example.domains.billing.core: billing is not in domains.orders"
    ]


@pytest.mark.parametrize("target", [ORDERS_PORTS, ORDERS_BOUNDARY, ORDERS_REPOSITORY])
def test_declared_dependency_keeps_internals_private(project: Project, target: str) -> None:
    project.manifest(BILLING_DEPENDS_ON_ORDERS)
    assert importing(project, BILLING_REPOSITORY, target) == [
        f"billing domain cannot import {module(target)}: "
        "only the core and shell modules of orders are public"
    ]


@pytest.mark.parametrize(
    "target",
    [
        "src/example/domains/orders/persistence/tables.py",
        "src/example/domains/orders/approval/policy.py",
        "src/example/shared/core.py",
        "src/example/projections/summary/model.py",
        "src/example/integrations/payments.py",
    ],
)
def test_own_domain_and_non_domains_are_unrestricted(project: Project, target: str) -> None:
    assert importing(project, ORDERS_REPOSITORY, target) == []


def test_non_domain_importers_are_unrestricted(project: Project) -> None:
    assert importing(project, "src/example/app/dependencies.py", ORDERS_REPOSITORY) == []


def test_re_exports_cannot_launder_internals(project: Project) -> None:
    project.manifest(BILLING_DEPENDS_ON_ORDERS).write(
        {
            ORDERS_PORTS: "class Payments: ...\n",
            ORDERS_SERVICE: "from example.domains.orders.ports import Payments\n",
        }
    )
    [finding] = [
        item
        for item in project.write(
            {BILLING: "from example.domains.orders.service import Payments\n"}
        ).findings(BILLING)
        if item.code == "LIT104"
    ]
    assert finding.target == "example.domains.orders.ports"


def test_package_import_reports_each_module_once(project: Project) -> None:
    project.write({ORDERS_SERVICE: "VALUE = 1\n", "src/example/domains/orders/__init__.py": ""})
    source = "from example.domains.orders import service\nimport example.domains.orders.service\n"
    findings = [
        item.target
        for item in project.write({BILLING: source}).findings(BILLING)
        if item.code == "LIT104"
    ]
    assert findings == ["example.domains.orders.service"]


def test_dependency_override_exempts_one_edge(project: Project) -> None:
    project.manifest(
        "[workspace]\ndependency_override_budget = 1\n"
        + BILLING_DEPENDS_ON_ORDERS
        + f"""
        [[dependency_overrides]]
        importer = "{BILLING_REPOSITORY}"
        imported = "{ORDERS_REPOSITORY}"
        reason = "Invoices join order rows until billing owns a projection"
        issue = "BILL-1"
        """
    )
    assert importing(project, BILLING_REPOSITORY, ORDERS_REPOSITORY) == []


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        ('[domains]\nbilling = ["orders"]\norders = ["billing"]', "billing -> orders -> billing"),
        (
            '[domains]\na = ["b"]\nb = ["c"]\nc = ["a"]\nd = []',
            "domains form a cycle: a -> b -> c -> a",
        ),
        ('[domains]\norders = ["orders"]', "domains.orders cannot depend on itself"),
        ('[domains]\nbilling = ["orders"]', "domains.billing names undeclared domains: orders"),
        ('[domains]\n"order-items" = []', "domains key must be a Python identifier"),
        ('[domains]\nbilling = "orders"', "domains.billing must be"),
    ],
)
def test_invalid_graph_is_a_manifest_error(project: Project, manifest: str, message: str) -> None:
    project.manifest(manifest)
    with pytest.raises(ManifestError, match=message):
        project.load()


def test_declared_domain_without_package_is_stale(project: Project) -> None:
    project.manifest(BILLING_DEPENDS_ON_ORDERS).write({BILLING: "", ORDERS_CORE: ""})
    assert project.load().configuration_errors() == ()

    project.manifest(BILLING_DEPENDS_ON_ORDERS + "legacy = []\n")
    assert project.load().configuration_errors() == (
        "declared domain matches no domains/ package: legacy",
    )
