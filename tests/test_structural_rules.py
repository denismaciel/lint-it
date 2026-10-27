import ast

import pytest

from lint_it.plugin import LintItChecker


def lint_codes(source: str, filename: str) -> list[str]:
    errors = LintItChecker(tree=ast.parse(source), filename=filename).run()
    return [message.split()[0] for _, _, message, _ in errors]


@pytest.mark.parametrize(
    ("source", "filename"),
    [
        ("from unittest.mock import Mock", "src/finance_api/foo_test.py"),
        (
            'def test_x(monkeypatch):\n    monkeypatch.setenv("X", "1")',
            "src/finance_api/foo_test.py",
        ),
    ],
)
def test_pal002_rejects_test_mocks(source: str, filename: str) -> None:
    assert lint_codes(source, filename) == ["PAL002"]


@pytest.mark.parametrize(
    ("source", "filename"),
    [
        (
            "from finance_api.domains.foo.model import Foo",
            "src/finance_api/app/routers/foo.py",
        ),
        (
            "from finance_api.domains.foo.service import FooService",
            "src/finance_api/domains/foo/persistence/repository.py",
        ),
        (
            "from finance_api.domains.foo.service import FooService",
            "src/finance_api/domains/foo/model.py",
        ),
        (
            "from ..service import FooService",
            "src/finance_api/domains/foo/persistence/repository.py",
        ),
    ],
)
def test_pal003_enforces_domain_direction(source: str, filename: str) -> None:
    assert lint_codes(source, filename) == ["PAL003"]


def test_pal003_allows_service_to_import_port() -> None:
    source = "from finance_api.domains.foo.ports import FooRepository"
    assert lint_codes(source, "src/finance_api/domains/foo/service.py") == []


@pytest.mark.parametrize(
    "source",
    [
        'import os\nvalue = os.environ["TOKEN"]',
        'from os import getenv\nvalue = getenv("TOKEN")',
    ],
)
def test_pal004_rejects_environment_access(source: str) -> None:
    assert lint_codes(source, "src/finance_api/domains/foo/service.py") == ["PAL004"]


def test_pal004_allows_config_environment_access() -> None:
    source = 'import os\nvalue = os.getenv("TOKEN")'
    assert lint_codes(source, "src/finance_api/app/config.py") == []


@pytest.mark.parametrize("method", ["commit", "rollback"])
def test_pal005_rejects_transaction_control_in_repositories(method: str) -> None:
    source = f"async def save(session):\n    await session.{method}()"
    assert lint_codes(source, "src/finance_api/domains/foo/repository.py") == ["PAL005"]


def test_pal005_allows_transaction_dependency() -> None:
    source = "async def finish(session):\n    await session.commit()"
    assert lint_codes(source, "src/finance_api/app/dependencies.py") == []


@pytest.mark.parametrize(
    "expression",
    [
        "FooRepository(session)",
        "httpx.AsyncClient()",
        "create_async_engine(url)",
    ],
)
def test_pal006_rejects_router_infrastructure_construction(expression: str) -> None:
    source = f"def endpoint():\n    return {expression}"
    assert lint_codes(source, "src/finance_api/app/routers/foo.py") == ["PAL006"]


def test_pal007_rejects_fastapi_in_domains() -> None:
    source = "from fastapi import APIRouter"
    assert lint_codes(source, "src/finance_api/domains/foo/api.py") == ["PAL007"]


@pytest.mark.parametrize(
    ("source", "filename"),
    [
        (
            "from finance_api.app.config import Settings",
            "packages/finance-contracts/src/finance_contracts/foo.py",
        ),
        (
            "from ariadne.service import Ariadne",
            "packages/ariadne-sdk/src/ariadne_sdk/foo.py",
        ),
    ],
)
def test_pal008_rejects_server_imports(source: str, filename: str) -> None:
    assert lint_codes(source, filename) == ["PAL008"]


def test_pal008_allows_contracts_in_sdk() -> None:
    source = "from finance_contracts import OrganizationRead"
    assert lint_codes(source, "packages/finance-sdk/src/finance_sdk/foo.py") == []


@pytest.mark.parametrize(
    "source",
    [
        "import sqlalchemy",
        "import sqlalchemy.orm",
        "from sqlalchemy import select",
        "from sqlalchemy.ext.asyncio import AsyncSession",
    ],
)
def test_pal009_rejects_sqlalchemy_outside_domain_persistence(source: str) -> None:
    assert lint_codes(source, "src/finance_api/domains/foo/service.py") == ["PAL009"]


@pytest.mark.parametrize(
    "filename",
    [
        "src/finance_api/domains/foo/persistence/records.py",
        "src/finance_api/domains/foo/persistence/queries/listing.py",
    ],
)
def test_pal009_allows_sqlalchemy_in_named_persistence_package(
    filename: str,
) -> None:
    assert lint_codes("from sqlalchemy import select", filename) == []


def test_pal009_does_not_constrain_application_infrastructure() -> None:
    source = "from sqlalchemy.ext.asyncio import AsyncSession"
    assert lint_codes(source, "src/finance_api/app/dependencies.py") == []


def test_pal009_rejects_sqlalchemy_in_router() -> None:
    source = "from sqlalchemy.exc import IntegrityError"
    assert lint_codes(source, "src/finance_api/app/routers/foo.py") == ["PAL009"]


@pytest.mark.parametrize(
    "source",
    [
        "from finance_api.domains.foo.persistence.repository import SqlFooRepository",
        "from .persistence.repository import SqlFooRepository",
        "from . import persistence",
    ],
)
def test_pal010_rejects_domain_import_of_persistence(source: str) -> None:
    assert lint_codes(source, "src/finance_api/domains/foo/service.py") == ["PAL010"]


def test_pal010_rejects_router_import_of_persistence() -> None:
    source = "from finance_api.domains.foo.persistence.repository import SqlFooRepository"
    assert lint_codes(source, "src/finance_api/app/routers/foo.py") == ["PAL010"]


def test_pal010_allows_application_wiring_to_import_persistence() -> None:
    source = "from finance_api.domains.foo.persistence.repository import SqlFooRepository"
    assert lint_codes(source, "src/finance_api/app/dependencies.py") == []


@pytest.mark.parametrize(
    ("source", "expected_message"),
    [
        (
            "import datetime as dt\nnow = dt.datetime.now(dt.UTC)",
            "pass the observed",
        ),
        ("from uuid import uuid4\nvalue = uuid4()", "pass the observed"),
        ("import random\nvalue = random.choice(('a', 'b'))", "pass the observed"),
    ],
)
def test_pal011_rejects_hidden_domain_nondeterminism(
    source: str,
    expected_message: str,
) -> None:
    errors = list(
        LintItChecker(
            tree=ast.parse(source),
            filename="src/finance_api/domains/forecast/core.py",
        ).run()
    )

    assert [message.split()[0] for _, _, message, _ in errors] == ["PAL011"]
    assert expected_message in errors[0][2]


def test_pal011_allows_clock_use_in_imperative_shell() -> None:
    source = "from example.integrations.clock import SYSTEM_CLOCK\nnow = SYSTEM_CLOCK.now()"
    assert lint_codes(source, "src/finance_api/app/dependencies.py") == []


@pytest.mark.parametrize("module", ["pydantic", "pydantic_settings"])
def test_pal012_keeps_validation_frameworks_at_boundaries(module: str) -> None:
    source = f"from {module} import BaseModel"
    assert lint_codes(source, "src/finance_api/domains/forecast/model.py") == ["PAL012"]


def test_pal012_allows_validation_frameworks_in_boundary_module() -> None:
    source = "from pydantic import BaseModel"
    assert lint_codes(source, "src/finance_api/sources/cgd.py") == []


def test_pal013_rejects_boolean_policy_input() -> None:
    source = "def plan_transfer(amount: int, *, urgent: bool) -> object:\n    return object()"
    assert lint_codes(source, "src/finance_api/domains/transfers/core.py") == ["PAL013"]


def test_pal013_rejects_boolean_decision_result() -> None:
    source = "def decide_transfer(amount: int) -> bool:\n    return amount > 0"
    assert lint_codes(source, "src/finance_api/domains/transfers/policy.py") == ["PAL013"]


def test_pal013_allows_named_predicates() -> None:
    source = "def is_transfer_allowed(amount: int) -> bool:\n    return amount > 0"
    assert lint_codes(source, "src/finance_api/domains/transfers/policy.py") == []


@pytest.mark.parametrize("source", ["import httpx", "open('state.txt')", "print('x')"])
def test_pal014_keeps_infrastructure_and_io_in_shell(source: str) -> None:
    assert lint_codes(source, "src/finance_api/domains/transfers/core.py") == ["PAL014"]


def test_pal014_allows_infrastructure_in_adapter() -> None:
    source = "import httpx"
    assert (
        lint_codes(
            source,
            "src/finance_api/domains/transfers/persistence/http_repository.py",
        )
        == []
    )


@pytest.mark.parametrize(
    "source",
    [
        "def decide():\n    raise TransferRejected()",
        "def decide():\n"
        "    try:\n"
        "        transfer()\n"
        "    except TransferConflict:\n"
        "        return None",
    ],
)
def test_pal015_rejects_exceptions_as_expected_outcomes(source: str) -> None:
    assert lint_codes(source, "src/finance_api/domains/transfers/core.py") == ["PAL015"]


def test_pal015_allows_invariant_errors() -> None:
    source = "def amount(value: int):\n    if value < 0:\n        raise ValueError('negative')"
    assert lint_codes(source, "src/finance_api/domains/transfers/core.py") == []


CANONICAL_RUNTIME_SETTINGS = """\
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='EXAMPLE_')

def load_settings() -> Settings:
    return Settings()
"""


def test_pal018_accepts_canonical_runtime_settings() -> None:
    assert lint_codes(CANONICAL_RUNTIME_SETTINGS, "src/example/app/config.py") == []


def test_pal018_requires_the_app_config_boundary() -> None:
    assert lint_codes(CANONICAL_RUNTIME_SETTINGS, "src/example/shared/config.py") == ["PAL018"]


def test_pal018_requires_the_settings_name() -> None:
    source = CANONICAL_RUNTIME_SETTINGS.replace("class Settings(", "class Config(")
    assert lint_codes(source, "src/example/app/config.py") == ["PAL018"]


def test_pal018_requires_an_environment_prefix() -> None:
    source = CANONICAL_RUNTIME_SETTINGS.replace(
        "SettingsConfigDict(env_prefix='EXAMPLE_')", "SettingsConfigDict()"
    )
    assert lint_codes(source, "src/example/app/config.py") == ["PAL018"]


def test_pal018_requires_a_loader() -> None:
    source = CANONICAL_RUNTIME_SETTINGS.split("\ndef load_settings", maxsplit=1)[0]
    assert lint_codes(source, "src/example/app/config.py") == ["PAL018"]
