from __future__ import annotations

import pytest
from conftest import Project

CORE = "src/example/domains/orders/core.py"
MODEL = "src/example/domains/orders/model.py"
SERVICE = "src/example/domains/orders/service.py"
REPOSITORY = "src/example/domains/orders/persistence/repository.py"
ROUTER = "src/example/app/routers/orders.py"
API = "src/example/app/api.py"


@pytest.mark.parametrize(
    ("importer", "target", "message"),
    [
        (CORE, API, "core cannot import boundary module example.app.api"),
        (CORE, SERVICE, "core cannot import shell module example.domains.orders.service"),
        (MODEL, REPOSITORY, "core cannot import adapter module"),
        (SERVICE, REPOSITORY, "shell cannot import adapter module"),
        (SERVICE, ROUTER, "shell cannot import router module example.app.routers.orders"),
        (SERVICE, API, "shell cannot import boundary module"),
        (REPOSITORY, SERVICE, "adapter cannot import shell module"),
        (ROUTER, MODEL, "router cannot import core module"),
        (ROUTER, REPOSITORY, "router cannot import adapter module"),
    ],
)
def test_lit101_rejects_disallowed_layers(
    project: Project, importer: str, target: str, message: str
) -> None:
    module = target.removeprefix("src/").removesuffix(".py").replace("/", ".")
    project.write({target: "VALUE = 1\n", importer: f"from {module} import VALUE\n"})
    [finding] = project.findings(importer)

    assert finding.code == "LIT101"
    assert message in finding.message


@pytest.mark.parametrize(
    ("importer", "target"),
    [
        (CORE, MODEL),
        (CORE, "src/example/domains/orders/ports.py"),
        (SERVICE, CORE),
        (SERVICE, "src/example/domains/billing/service.py"),
        (REPOSITORY, MODEL),
        (ROUTER, SERVICE),
        (ROUTER, "src/example/app/dependencies.py"),
        (API, REPOSITORY),
        ("tests/test_orders.py", REPOSITORY),
    ],
)
def test_lit101_allows_permitted_layers(project: Project, importer: str, target: str) -> None:
    module = target.removeprefix("src/").removesuffix(".py").replace("/", ".")
    project.write({target: "VALUE = 1\n", importer: f"from {module} import VALUE\n"})
    assert project.codes(importer) == []


@pytest.mark.parametrize(
    "statement",
    [
        "from .persistence.repository import Repository",
        "from .persistence import repository",
        "import example.domains.orders.persistence.repository as repository",
    ],
)
def test_lit101_resolves_relative_and_aliased_imports(project: Project, statement: str) -> None:
    project.write({REPOSITORY: "class Repository: ...\n", SERVICE: statement})
    assert project.codes(SERVICE) == ["LIT101"]


@pytest.mark.parametrize(
    "statement",
    [
        "import example.domains.orders.model",
        "from example.domains.orders.model import Order",
        "from example.domains.orders import model",
        "from example import Order",
    ],
)
@pytest.mark.parametrize(
    "initializer", ["src/example/__init__.py", "src/example/domains/__init__.py"]
)
def test_lit101_follows_package_initializers(
    project: Project, statement: str, initializer: str
) -> None:
    project.write(
        {
            API: "",
            MODEL: "class Order: ...\n",
            "src/example/__init__.py": "from example.domains.orders.model import Order\n",
            CORE: statement,
        }
    )
    with (project.root / initializer).open("a") as file:
        file.write("from example.app.api import create_app\n")
    [finding] = project.findings(CORE)

    assert (finding.code, finding.line) == ("LIT101", 1)
    assert finding.message.endswith("example.app.api")


def test_lit101_follows_initializer_helpers_through_cycles(project: Project) -> None:
    project.write(
        {
            API: "",
            "src/example/__init__.py": "from example.domains.orders import model\n",
            MODEL: "import example\nfrom example.app.api import create_app\n",
            CORE: "from example.domains.orders.model import Order\n",
        }
    )
    assert [item.message for item in project.findings(CORE)] == [
        "core cannot import boundary module example.app.api"
    ]


def test_lit101_ignores_imports_deferred_in_initializer_functions(project: Project) -> None:
    project.write(
        {
            API: "",
            MODEL: "",
            "src/example/__init__.py": "def start():\n    from example.app.api import app\n",
            CORE: "from example.domains.orders.model import Order\n",
        }
    )
    assert project.codes(CORE) == []


def test_lit101_reports_each_target_module_once(project: Project) -> None:
    project.write(
        {
            API: "",
            CORE: "from example.app.api import a\nfrom example.app.api import b\n",
        }
    )
    assert project.codes(CORE) == ["LIT101"]


def test_lit101_crosses_packages(project: Project) -> None:
    project.package("packages/support", "support").manifest(
        '[[packages]]\npath = "packages/support"\nlayout = "flat"\n'
    ).write(
        {
            "packages/support/src/support/__init__.py": "from support.adapters.http import fetch\n",
            "packages/support/src/support/adapters/http.py": "def fetch(): ...\n",
            "packages/support/src/support/model.py": "class Value: ...\n",
            CORE: "from support.model import Value\n",
        }
    )
    [finding] = project.findings(CORE)
    assert finding.message == "core cannot import adapter module support.adapters.http"


def test_lit101_honors_dependency_overrides(project: Project) -> None:
    project.manifest(
        f"""
        [workspace]
        dependency_override_budget = 1

        [[dependency_overrides]]
        importer = "{CORE}"
        imported = "{API}"
        reason = "Move the contract into the domain"
        issue = "EX-1"
        """
    ).write({API: "", CORE: "from example.app.api import create_app\n"})
    assert project.findings() == []


def test_lit101_matrix_is_configurable(project: Project) -> None:
    project.manifest('[layer_dependencies]\nshell = "*"\ncore = ["core", "port", "shell"]\n')
    project.write({REPOSITORY: "", CORE: "", SERVICE: "from .persistence import repository\n"})
    project.write({CORE: "from example.domains.orders import service\n"})
    assert project.codes(SERVICE) == []
    assert project.codes(CORE) == []


@pytest.mark.parametrize(
    "statement",
    [
        "import pydantic as validation",
        "from pydantic import BaseModel as Payload",
        "from pydantic.v1 import BaseModel",
        "import pydantic_settings",
        "import sqlalchemy.orm",
        "from sqlalchemy.ext.asyncio import AsyncSession",
        "from fastapi import APIRouter",
    ],
)
def test_lit102_rejects_frameworks_in_shell(project: Project, statement: str) -> None:
    [finding] = project.write({SERVICE: statement}).findings(SERVICE)
    assert (finding.code, finding.line) == ("LIT102", 1)
    assert finding.message.startswith("shell modules cannot import ")


@pytest.mark.parametrize(
    "statement", ["import httpx", "import subprocess", "from redis import Redis"]
)
@pytest.mark.parametrize("path", [CORE, MODEL, "src/example/domains/orders/ports.py"])
def test_lit102_rejects_io_clients_in_core_and_ports(
    project: Project, path: str, statement: str
) -> None:
    assert project.lint(path, statement) == ["LIT102"]


@pytest.mark.parametrize(
    "path",
    [
        REPOSITORY,
        API,
        "src/example/app/config.py",
        "src/example/app/dependencies.py",
        "src/example/domains/orders/boundary.py",
        "tests/test_orders.py",
    ],
)
def test_lit102_allows_frameworks_at_edges_and_adapters(project: Project, path: str) -> None:
    assert (
        project.lint(path, "from sqlalchemy import select\nfrom pydantic import BaseModel\n") == []
    )


def test_lit102_keeps_sqlalchemy_out_of_routers(project: Project) -> None:
    assert project.lint(ROUTER, "from sqlalchemy.exc import IntegrityError\n") == ["LIT102"]
    assert project.lint(ROUTER, "from fastapi import APIRouter\n") == []


@pytest.mark.parametrize(
    ("exports", "statement"),
    [
        ("from pydantic import BaseModel as Payload", "from example.shared.model import Payload"),
        ("import pydantic_settings as settings", "from example.shared.model import settings"),
        ("from .validation import Payload", "from example.shared.model import Payload"),
    ],
)
def test_lit102_follows_reexports(project: Project, exports: str, statement: str) -> None:
    project.write(
        {
            "src/example/shared/validation.py": "from pydantic import BaseModel as Payload\n",
            "src/example/shared/model.py": exports,
            SERVICE: statement,
        }
    )
    assert "pydantic" in project.findings(SERVICE)[-1].message


def test_lit102_reexport_alias_must_match(project: Project) -> None:
    project.write(
        {
            "src/example/shared/model.py": "import json as plain, pydantic as validation\n",
            SERVICE: "from example.shared.model import plain\n",
        }
    )
    assert project.codes(SERVICE) == []
    project.write({SERVICE: "from example.shared.model import validation\n"})
    assert project.codes(SERVICE) == ["LIT102"]


def test_lit102_reexport_cycles_terminate(project: Project) -> None:
    project.write(
        {
            "src/example/shared/model.py": "from .core import Payload\n",
            "src/example/shared/core.py": "from .model import Payload\n",
            SERVICE: "from example.shared.model import Payload\n",
        }
    )
    assert project.codes(SERVICE) == []


def test_lit102_reports_one_finding_per_statement(project: Project) -> None:
    project.write({SERVICE: "import pydantic, pydantic_settings\nimport sqlalchemy\n"})
    findings = project.findings(SERVICE)

    assert [item.line for item in findings] == [1, 2]
    assert findings[0].message.endswith("pydantic, pydantic_settings")


def test_lit102_checks_deferred_and_type_checking_imports(project: Project) -> None:
    project.write(
        {
            SERVICE: """\
                from typing import TYPE_CHECKING
                if TYPE_CHECKING:
                    from pydantic import BaseModel
                async def run():
                    from pydantic import Field
            """
        }
    )
    assert [item.line for item in project.findings(SERVICE)] == [3, 5]


def test_lit102_lists_are_configurable(project: Project) -> None:
    project.manifest('[forbidden_imports]\nshell = ["boto3"]\ncore = []\n')
    assert project.lint(SERVICE, "import pydantic\nimport boto3.session\n") == ["LIT102"]
    assert project.lint(CORE, "import httpx\n") == []


def _client_workspace(project: Project, statement: str) -> str:
    project.package("packages/sdk", "sdk").package("packages/contracts", "contracts").manifest(
        """
        [[packages]]
        path = "packages/sdk"
        kind = "client"
        layout = "boundary"

        [[packages]]
        path = "packages/contracts"
        kind = "library"
        layout = "boundary"
        """
    ).write(
        {
            "src/example/app/config.py": "VALUE = 1\n",
            "packages/contracts/src/contracts/__init__.py": "",
            "packages/sdk/src/sdk/client.py": statement,
        }
    )
    return "packages/sdk/src/sdk/client.py"


def test_lit103_rejects_server_imports_from_clients(project: Project) -> None:
    path = _client_workspace(project, "from example.app.config import VALUE\n")
    [finding] = project.findings(path)
    assert (finding.code, finding.message) == (
        "LIT103",
        "client packages cannot import server module example.app.config",
    )


def test_lit103_allows_library_imports_from_clients(project: Project) -> None:
    path = _client_workspace(project, "from contracts import Order\n")
    assert project.codes(path) == []
