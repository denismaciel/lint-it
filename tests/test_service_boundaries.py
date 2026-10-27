import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from lint_it.core import Finding
from lint_it.filesystem import check_paths, workspace_architecture
from lint_it.plugin import LintItChecker
from lint_it.rules.pal024 import ServiceBoundaryDependencyRule
from lint_it.rules.registry import ALL_RULES

SERVICE = "src/example/domains/orders/service.py"


def project(tmp_path: Path, sources: dict[str, str]) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="example"\nversion="1"\n')
    (tmp_path / "lint-it.toml").write_text(
        '[workspace]\ndefault_profile="service-layout"\n'
        '[profiles.service-layout]\nrole="application"\nlayers=[\n'
        '{glob="src/*/domains/**/service.py",layer="imperative-shell"},\n'
        '{glob="src/*/domains/**/*_service.py",layer="imperative-shell"},\n'
        '{glob="src/*/domains/**/boundary.py",layer="boundary"},\n'
        '{glob="src/*/domains/**/persistence/**/*.py",layer="adapter"},\n'
        '{glob="src/*/domains/**/adapters/**/*.py",layer="adapter"},\n'
        '{glob="**/test_*.py",layer="test-shell"}]\n'
    )
    for filename, source in sources.items():
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)


def findings(tmp_path: Path, filename: str = SERVICE) -> list[Finding]:
    return check_paths([tmp_path / filename], [ServiceBoundaryDependencyRule()])


@pytest.mark.parametrize(
    "statement",
    [
        "import pydantic as validation",
        "from pydantic import BaseModel as Payload",
        "from pydantic.v1 import BaseModel",
        "import pydantic_settings",
        "from pydantic_settings import BaseSettings as Settings",
    ],
)
def test_rejects_direct_validation_framework_imports(tmp_path: Path, statement: str) -> None:
    project(tmp_path, {SERVICE: statement})

    result = findings(tmp_path)

    assert len(result) == 1
    assert result[0].code == "PAL024"
    assert result[0].line == 1
    assert "pydantic" in result[0].message


@pytest.mark.parametrize(
    "statement",
    [
        "from example.domains.orders.boundary import Request as Input",
        "import example.domains.orders.boundary as schemas",
        "from example.domains.orders import boundary as schemas",
        "from .boundary import Request",
        "from . import boundary",
    ],
)
def test_rejects_boundary_modules_even_for_plain_values(tmp_path: Path, statement: str) -> None:
    project(
        tmp_path,
        {
            SERVICE: statement,
            "src/example/domains/orders/boundary.py": "class Request: pass",
        },
    )

    result = findings(tmp_path)

    assert len(result) == 1
    assert "example.domains.orders.boundary" in result[0].message


@pytest.mark.parametrize(
    "exports,statement",
    [
        (
            "from example.domains.orders.boundary import Request as PublicRequest",
            "from example.shared.contracts import PublicRequest as Input",
        ),
        (
            "from pydantic import BaseModel as Payload",
            "from example.shared.contracts import Payload as Input",
        ),
        (
            "import pydantic_settings as settings",
            "from example.shared.contracts import settings",
        ),
    ],
)
def test_follows_explicit_reexports(tmp_path: Path, exports: str, statement: str) -> None:
    project(
        tmp_path,
        {
            SERVICE: statement,
            "src/example/shared/contracts.py": exports,
            "src/example/domains/orders/boundary.py": "class Request: pass",
        },
    )

    assert len(findings(tmp_path)) == 1


def test_follows_relative_framework_reexport_chain(tmp_path: Path) -> None:
    project(
        tmp_path,
        {
            SERVICE: "from example.shared.contracts import Payload",
            "src/example/shared/contracts.py": "from .validation import Payload",
            "src/example/shared/validation.py": "from pydantic import BaseModel as Payload",
        },
    )

    assert "pydantic" in findings(tmp_path)[0].message


def test_reexport_cycle_terminates(tmp_path: Path) -> None:
    project(
        tmp_path,
        {
            SERVICE: "from example.shared.contracts import Payload",
            "src/example/shared/contracts.py": "from .validation import Payload",
            "src/example/shared/validation.py": "from .contracts import Payload",
        },
    )

    assert findings(tmp_path) == []


def test_module_reexport_matches_the_requested_alias(tmp_path: Path) -> None:
    project(
        tmp_path,
        {
            SERVICE: "from example.shared.contracts import plain",
            "src/example/shared/contracts.py": "import json as plain, pydantic as validation",
        },
    )

    assert findings(tmp_path) == []

    (tmp_path / SERVICE).write_text("from example.shared.contracts import validation")
    assert "pydantic" in findings(tmp_path)[0].message


def test_follows_initializer_execution_but_not_deferred_functions(
    tmp_path: Path,
) -> None:
    project(
        tmp_path,
        {
            SERVICE: "from .model import Order",
            "src/example/domains/orders/model.py": "class Order: pass",
            "src/example/domains/orders/boundary.py": "class Request: pass",
            "src/example/domains/orders/__init__.py": (
                "def initialize():\n    from .boundary import Request\n"
            ),
        },
    )
    assert findings(tmp_path) == []

    (tmp_path / "src/example/domains/orders/__init__.py").write_text(
        "from .boundary import Request"
    )
    result = findings(tmp_path)
    assert len(result) == 1
    assert result[0].line == 1
    assert "example.domains.orders.boundary" in result[0].message


def test_wire_contract_profile_is_a_boundary(tmp_path: Path) -> None:
    project(
        tmp_path,
        {
            SERVICE: "from contracts.orders import Request",
            "packages/contracts/src/contracts/orders.py": "class Request: pass",
        },
    )
    (tmp_path / "packages/contracts/pyproject.toml").write_text(
        '[project]\nname="contracts"\nversion="1"\n'
    )
    with (tmp_path / "lint-it.toml").open("a") as manifest:
        manifest.write('\n[[packages]]\npath="packages/contracts"\nprofile="contracts"\n')

    assert "contracts.orders" in findings(tmp_path)[0].message


def test_reports_one_finding_per_statement_not_symbol(tmp_path: Path) -> None:
    project(
        tmp_path,
        {
            SERVICE: (
                "from .boundary import Request, Response\n"
                "import pydantic, pydantic_settings\n"
                "from .boundary import Request as Other\n"
            ),
            "src/example/domains/orders/boundary.py": "",
        },
    )

    result = findings(tmp_path)

    assert [item.line for item in result] == [1, 2, 3]
    assert result[1].message.endswith("pydantic, pydantic_settings")


@pytest.mark.parametrize("service_name", ["service.py", "notification_service.py"])
def test_checks_deferred_and_type_checking_imports_in_services(
    tmp_path: Path, service_name: str
) -> None:
    filename = f"src/example/domains/orders/{service_name}"
    project(
        tmp_path,
        {
            filename: (
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n    from pydantic import BaseModel\n"
                "async def run():\n    from pydantic import Field\n"
            )
        },
    )

    assert [item.line for item in findings(tmp_path, filename)] == [3, 5]


@pytest.mark.parametrize(
    "filename",
    [
        "src/example/domains/orders/core.py",
        "src/example/domains/orders/boundary.py",
        "src/example/domains/orders/persistence/service.py",
        "src/example/domains/orders/adapters/service.py",
        "src/example/domains/orders/test_service.py",
        "src/example/app/service.py",
        "src/example/integrations/unit_of_work/service.py",
        "src/example/shared/service.py",
    ],
)
def test_only_targets_domain_orchestration(tmp_path: Path, filename: str) -> None:
    project(tmp_path, {filename: "from pydantic import BaseModel"})

    assert findings(tmp_path, filename) == []


def test_allows_async_orchestration_of_ports_and_plain_values(tmp_path: Path) -> None:
    project(
        tmp_path,
        {
            SERVICE: (
                "from .model import Order\n"
                "from .ports import Store\n"
                "from .core import decide\n"
                "async def run(store: Store, order: Order):\n"
                "    return await store.save(decide(order))\n"
            ),
            "src/example/domains/orders/model.py": "class Order: pass",
            "src/example/domains/orders/ports.py": "class Store: pass",
            "src/example/domains/orders/core.py": "def decide(order): return order",
        },
    )

    assert findings(tmp_path) == []


def test_uses_immutable_source_snapshot(tmp_path: Path) -> None:
    project(
        tmp_path,
        {
            SERVICE: "from .boundary import Request",
            "src/example/domains/orders/boundary.py": "class Request: pass",
        },
    )
    architecture = workspace_architecture(tmp_path)
    source = next(item for item in architecture.sources if item.path.name == "service.py")
    before = ast.dump(source.tree)
    (tmp_path / SERVICE).write_text("")

    result = list(
        ServiceBoundaryDependencyRule().check(source.tree, str(source.path), architecture)
    )

    assert len(result) == 1
    assert ast.dump(source.tree) == before


def test_cli_and_flake8_enforce_service_rule(tmp_path: Path) -> None:
    project(tmp_path, {SERVICE: "from pydantic import BaseModel"})
    architecture = workspace_architecture(tmp_path)
    result = check_paths([tmp_path], ALL_RULES, architecture)
    assert [item.code for item in result] == ["PAL024"]
    errors = list(
        LintItChecker(ast.parse((tmp_path / SERVICE).read_text()), str(tmp_path / SERVICE)).run()
    )
    assert [(line, column, message) for line, column, message, _ in errors] == [
        (item.line, item.column, f"{item.code} {item.message}") for item in result
    ]
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "lint_it.cli",
            "--workspace",
            str(tmp_path),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 1
    payload = json.loads(process.stdout)
    assert [item["code"] for item in payload] == ["PAL024"]
