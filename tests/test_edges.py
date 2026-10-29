from __future__ import annotations

import pytest
from conftest import Project

CORE = "src/example/domains/orders/core.py"
SERVICE = "src/example/domains/orders/service.py"
REPOSITORY = "src/example/domains/orders/persistence/repository.py"
ROUTER = "src/example/app/routers/orders.py"


@pytest.mark.parametrize(
    "source",
    [
        "import os as process\nvalue = process.getenv('VALUE')",
        "import os as process\nvalue = process.environ['VALUE']",
        "from os import getenv as read\nvalue = read('VALUE')",
        "from os import environ as values\nvalue = values.get('VALUE')",
        "import os\nread = os.getenv\nvalue = read('VALUE')",
        "import os\nvalue = os.getenvb(b'VALUE')",
    ],
)
@pytest.mark.parametrize("path", [CORE, SERVICE, REPOSITORY, ROUTER])
def test_lit301_rejects_environment_access(project: Project, path: str, source: str) -> None:
    assert set(project.lint(path, source)) == {"LIT301"}


@pytest.mark.parametrize(
    "path",
    [
        "src/example/app/config.py",
        "src/example/app/dependencies.py",
        "scripts/backfill.py",
        "migrations/env.py",
        "tests/test_config.py",
    ],
)
def test_lit301_allows_environment_at_edges(project: Project, path: str) -> None:
    assert project.lint(path, "import os\nvalue = os.environ['VALUE']\n") == []


def test_lit301_respects_shadowing(project: Project) -> None:
    assert project.lint(SERVICE, "import os\ndef read(os):\n    return os.getenv('V')\n") == []


@pytest.mark.parametrize("method", ["commit", "rollback"])
@pytest.mark.parametrize("path", [SERVICE, REPOSITORY, ROUTER, "src/example/app/main.py"])
def test_lit302_rejects_transaction_control(project: Project, path: str, method: str) -> None:
    source = f"async def save(session):\n    await session.{method}()\n"
    assert project.lint(path, source) == ["LIT302"]


@pytest.mark.parametrize(
    "path",
    [
        "src/example/app/dependencies.py",
        "src/example/integrations/unit_of_work/sql.py",
        "migrations/versions/0001.py",
        "tests/test_repository.py",
    ],
)
def test_lit302_allows_transaction_boundaries(project: Project, path: str) -> None:
    assert project.lint(path, "async def finish(session):\n    await session.commit()\n") == []


@pytest.mark.parametrize(
    "expression",
    [
        "OrderRepository(session)",
        "httpx.AsyncClient()",
        "create_async_engine(url)",
        "load_settings()",
    ],
)
@pytest.mark.parametrize("path", [ROUTER, "src/example/app/router/orders.py"])
def test_lit303_rejects_router_construction(project: Project, path: str, expression: str) -> None:
    source = f"import httpx\ndef endpoint():\n    return {expression}\n"
    assert project.lint(path, source) == ["LIT303"]


def test_lit303_resolves_aliases(project: Project) -> None:
    source = "from httpx import AsyncClient as Http\nclient = Http()\n"
    assert project.lint(ROUTER, source) == ["LIT303"]


def test_lit303_follows_custom_router_layers(project: Project) -> None:
    project.manifest(
        """
        [workspace]
        layout = "web"

        [layouts.web]
        extends = "domains"
        layers = [{ glob = "src/*/http/*.py", layer = "router" }]
        """
    )
    source = "from sqlalchemy import select\ndef endpoint():\n    return OrderRepository()\n"
    assert project.lint("src/example/http/orders.py", source) == ["LIT102", "LIT303"]


@pytest.mark.parametrize(
    "source",
    [
        "from unittest.mock import Mock",
        "from unittest import mock",
        "import unittest.mock",
        "def test_x(monkeypatch):\n    monkeypatch.setenv('X', '1')",
        "def test_x(mocker):\n    mocker.patch('example.clock')",
    ],
)
@pytest.mark.parametrize("path", ["tests/test_orders.py", "conftest.py", "tests/conftest.py"])
def test_lit304_rejects_patching_in_tests(project: Project, path: str, source: str) -> None:
    assert project.lint(path, source) == ["LIT304"]


def test_lit304_applies_to_test_support_packages(project: Project) -> None:
    project.package("packages/testing", "testing").manifest(
        '[[packages]]\npath = "packages/testing"\nlayout = "test-support"\n'
    )
    path = "packages/testing/src/testing/fakes.py"
    assert project.lint(path, "from unittest.mock import Mock\n") == ["LIT304"]


@pytest.mark.parametrize(
    "source",
    [
        "def calculate(items=[]):\n    return items",
        "def calculate(items={}):\n    return items",
        "def calculate(*, items=set()):\n    return items",
        "def calculate(settings=Settings()):\n    return settings",
        "def calculate(now=datetime.now()):\n    return now",
        "def calculate(clock=lambda: 0):\n    return clock",
        "def calculate(limit=default_limit):\n    return limit",
        "DEFAULTS = []\ndef calculate(items=DEFAULTS):\n    return items",
        "def calculate(items=frozenset(load())):\n    return items",
    ],
)
@pytest.mark.parametrize("path", [CORE, SERVICE, REPOSITORY])
def test_lit305_rejects_constructed_defaults(project: Project, path: str, source: str) -> None:
    assert project.lint(path, source) == ["LIT305"]


@pytest.mark.parametrize(
    "source",
    [
        "def calculate(limit=10, name='x', ratio=-1.5, flags=(1, 2), missing=None): ...",
        "LIMIT = 10\ndef calculate(limit=LIMIT, status=Status.OPEN, order=(Status.OPEN,)): ...",
        "from example.config import MAX_ITEMS\ndef calculate(limit=MAX_ITEMS): ...",
        "def calculate(seen=frozenset(), cost=Decimal('0'), ttl=timedelta(days=TTL_DAYS)): ...",
        "def calculate(kinds=frozenset({Kind.A, Kind.B})): ...",
        "from typing import Protocol\nclass Store(Protocol):\n    def load(self, keys=[]): ...",
        "class OrderError(Exception):\n    def __init__(self, details={}): ...",
    ],
)
def test_lit305_allows_literals_and_exemptions(project: Project, source: str) -> None:
    assert project.lint(CORE, source) == []


@pytest.mark.parametrize("path", [ROUTER, "src/example/app/main.py", "tests/test_orders.py"])
def test_lit305_skips_edge_layers(project: Project, path: str) -> None:
    source = "from fastapi import Depends\ndef endpoint(store=Depends(get_store)): ...\n"
    assert project.lint(path, source) == []
