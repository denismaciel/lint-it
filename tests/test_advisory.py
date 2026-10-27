import ast
import tomllib
from pathlib import Path

import pytest

from lint_it.advisory import Checker, load_policy


def lint_codes(source: str, filename: str) -> list[str]:
    tree = ast.parse(source)
    policy = load_policy(
        tomllib.loads((Path(__file__).parent / "fixtures/lint-advisory.toml").read_text())
    )
    errors = Checker(
        tree=tree, filename=f"/virtual-workspace/{filename}", policy=policy
    ).diagnostics()
    return [message.split()[0] for _, _, message in errors]


def test_internal_function_default_fails() -> None:
    source = "\ndef list_items(active: bool = True) -> list[str]:\n    return []\n"
    assert lint_codes(source, "src/example/domains/listing/service.py") == ["PLC001"]


def test_internal_async_function_default_fails() -> None:
    source = "\nasync def list_items(active: bool = True) -> list[str]:\n    return []\n"
    assert lint_codes(source, "src/example/domains/listing/repository.py") == ["PLC001"]


def test_required_keyword_only_argument_passes() -> None:
    source = "\ndef list_items(*, active: bool) -> list[str]:\n    return []\n"
    assert lint_codes(source, "src/example/domains/listing/service.py") == []


def test_keyword_only_default_fails() -> None:
    source = "\ndef list_items(*, active: bool = True) -> list[str]:\n    return []\n"
    assert lint_codes(source, "src/example/domains/listing/service.py") == ["PLC001"]


def test_protocol_method_default_passes() -> None:
    source = """
from typing import Protocol


class ListingRepo(Protocol):
    def list_items(self, active: bool | None = None) -> list[str]: ...
"""
    assert lint_codes(source, "src/example/domains/listing/repository.py") == []


def test_nested_protocol_method_default_passes() -> None:
    source = """
import typing


class ListingRepo(typing.Protocol):
    async def list_items(self, active: bool | None = None) -> list[str]: ...
"""
    assert lint_codes(source, "src/example/domains/listing/repository.py") == []


def test_exception_constructor_default_passes() -> None:
    source = """
class ListingError(Exception):
    def __init__(self, message: str = 'failed') -> None:
        super().__init__(message)
"""
    assert lint_codes(source, "src/example/domains/listing/model.py") == []


def test_error_named_constructor_default_passes() -> None:
    source = """
class ListingError:
    def __init__(self, message: str = 'failed') -> None:
        self.message = message
"""
    assert lint_codes(source, "src/example/domains/listing/model.py") == []


def test_exception_non_constructor_default_still_fails() -> None:
    source = """
class ListingError(Exception):
    def with_context(self, source: str = 'listing') -> object:
        return self
"""
    assert lint_codes(source, "src/example/domains/listing/model.py") == ["PLC001"]


def test_router_default_passes() -> None:
    source = """
from fastapi import Query


def list_items(active: bool = Query(True)) -> list[str]:
    return []
"""
    assert lint_codes(source, "src/example/domains/listing/router.py") == []


def test_fastapi_route_default_passes_outside_router_file() -> None:
    source = """
def create_app():
    @app.get('/items')
    async def list_items(active: bool | None = None) -> list[str]:
        return []
"""
    assert lint_codes(source, "src/example/runner/internal_app.py") == []


def test_fastapi_dependency_default_passes_outside_router_file() -> None:
    source = """
from fastapi import Header


async def require_secret(x_secret: str | None = Header(default=None)) -> None:
    return None
"""
    assert lint_codes(source, "src/example/runner/internal_app.py") == []


def test_admin_router_default_passes() -> None:
    source = "\ndef list_items(active: bool = True) -> list[str]:\n    return []\n"
    assert lint_codes(source, "src/example/domains/listing/admin_router.py") == []


def test_dependency_default_passes() -> None:
    source = "\ndef current_user(required: bool = True) -> object:\n    return object()\n"
    assert lint_codes(source, "src/example/domains/auth/dependency.py") == []


def test_cli_default_passes() -> None:
    source = "\ndef main(verbose: bool = False) -> int:\n    return 0\n"
    assert lint_codes(source, "src/example/scraping/cli.py") == []


def test_script_default_passes() -> None:
    source = "\ndef main(limit: int = 100) -> int:\n    return limit\n"
    assert lint_codes(source, "src/example/scripts/backfill.py") == []


def test_migration_default_passes() -> None:
    source = "\ndef upgrade(batch_size: int = 1000) -> None:\n    return None\n"
    assert lint_codes(source, "src/example/migrations/versions/abc.py") == []


def test_test_default_passes() -> None:
    source = "\ndef build_user(active: bool = True) -> object:\n    return object()\n"
    assert lint_codes(source, "src/tests/user/test_user_service.py") == []


def test_in_tree_test_module_default_passes() -> None:
    source = "\ndef make_run(status: str = 'pending') -> object:\n    return object()\n"
    assert lint_codes(source, "src/example/runner/store_test.py") == []


def test_sqlalchemy_import_in_nested_domain_persistence_passes() -> None:
    source = "from sqlalchemy import select\n"
    assert (
        lint_codes(source, "src/example/domains/listing/price_prediction/persistence/repository.py")
        == []
    )


def test_flake8_allows_nested_domain_persistence_imports() -> None:
    source = "from example.domains.listing.persistence.models import Listing\n"
    assert (
        lint_codes(source, "src/example/domains/listing/price_prediction/persistence/repository.py")
        == []
    )


def test_sqlalchemy_import_in_scraping_fails() -> None:
    source = "from sqlalchemy.ext.asyncio import AsyncSession\n"
    assert lint_codes(source, "src/example/scraping/new_source/job.py") == ["PLC002"]


def test_aliased_sqlalchemy_import_in_scraping_fails() -> None:
    source = "import sqlalchemy as sa\n"
    assert lint_codes(source, "src/example/scraping/new_source/job.py") == ["PLC002"]


def test_nested_sqlalchemy_import_in_router_still_fails() -> None:
    source = "\ndef handler() -> None:\n    from sqlalchemy import select\n"
    assert lint_codes(source, "src/example/scraping/admin_router.py") == ["PLC002"]


def test_type_checking_sqlalchemy_import_still_fails() -> None:
    source = """
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.engine import Result
"""
    assert lint_codes(source, "src/example/scraping/new_source/service.py") == ["PLC002"]


def test_sqlalchemy_adapter_import_passes() -> None:
    source = "from sqlalchemy import select\n"
    assert (
        lint_codes(source, "src/example/scraping/integrations/persistence/sqlalchemy/listings.py")
        == []
    )


@pytest.mark.parametrize(
    ("source", "filename", "code"),
    [
        ("import sqlalchemy\n", "persistence/sqlalchemy/listings.py", "PLC002"),
        ("import sqlite3\n", "persistence/sqlite/connection.py", "PLC003"),
        ("from example.shared.db import session_factory\n", "composition.py", "PLC004"),
        ("from example.shared.db import session_factory\n", "app/other.py", "PLC004"),
    ],
)
def test_storage_permissions_follow_only_canonical_paths(
    source: str, filename: str, code: str
) -> None:
    assert lint_codes(source, f"src/example/scraping/{filename}") == [code]


def test_sqlite_import_in_scraping_fails() -> None:
    source = "import sqlite3\n"
    assert lint_codes(source, "src/example/scraping/new_source/state.py") == ["PLC003"]


def test_sqlite_adapter_import_passes() -> None:
    source = "import sqlite3\n"
    assert (
        lint_codes(source, "src/example/scraping/integrations/persistence/sqlite/connection.py")
        == []
    )


def test_shared_db_import_in_scraping_fails() -> None:
    source = "from example.shared.db import session_factory\n"
    assert lint_codes(source, "src/example/scraping/new_source/job.py") == ["PLC004"]


def test_shared_db_import_in_composition_passes() -> None:
    source = "from example.shared.db import create_session_factory\n"
    assert lint_codes(source, "src/example/scraping/app/scraping_dependencies.py") == []


def test_shared_db_import_in_sqlalchemy_infrastructure_passes() -> None:
    source = "from example.shared.db import create_session_factory\n"
    assert (
        lint_codes(source, "src/example/scraping/integrations/persistence/sqlalchemy/experiment.py")
        == []
    )


def test_storage_imports_have_no_legacy_allowance() -> None:
    source = """
import sqlite3
from sqlalchemy import select
from example.shared.db import session_factory
"""
    assert lint_codes(source, "src/example/scraping/sources/imovirtual/unseen.py") == [
        "PLC003",
        "PLC002",
        "PLC004",
    ]


def test_sqlalchemy_adapter_import_in_portable_scraping_fails() -> None:
    source = (
        "from example.scraping.integrations.persistence.sqlalchemy.listings "
        "import SQLAlchemyListingWriter\n"
    )
    assert lint_codes(source, "src/example/scraping/sources/example/job.py") == ["PLC005"]


def test_sqlalchemy_adapter_import_in_composition_passes() -> None:
    source = (
        "from example.scraping.integrations.persistence.sqlalchemy.listings "
        "import SQLAlchemyListingWriter\n"
    )
    assert lint_codes(source, "src/example/scraping/app/scraping_dependencies.py") == []


@pytest.mark.parametrize(
    "filename",
    [
        "src/example/scraping/integrations/persistence/sqlalchemy/listings.py",
        "src/example/scraping/integrations/unit_of_work/sqlalchemy/idealista.py",
        "packages/example-scraping/src/example_scraping/integrations/unit_of_work/sqlalchemy/idealista.py",
    ],
)
def test_sqlalchemy_storage_boundaries_allow_sql_and_shared_db_imports(filename: str) -> None:
    source = """
from sqlalchemy import select
from example.shared.db import session_factory
from example.domains.listing.persistence.models import Listing
"""
    assert lint_codes(source, filename) == []


@pytest.mark.parametrize(
    "filename",
    [
        "src/example/scraping/integrations/persistence/sqlite/connection.py",
        "src/example/scraping/integrations/unit_of_work/sqlite.py",
        "packages/example-scraping/src/example_scraping/integrations/unit_of_work/sqlite.py",
    ],
)
def test_sqlite_storage_boundaries_allow_sqlite_import(filename: str) -> None:
    assert lint_codes("import sqlite3\n", filename) == []


@pytest.mark.parametrize(
    "filename",
    [
        "src/example/scraping/integrations/unit_of_work/foo.py",
        "src/example/scraping/integrations/unit_of_work/sqlite_helpers.py",
    ],
)
def test_non_sqlite_uow_modules_reject_sqlite_import(filename: str) -> None:
    assert lint_codes("import sqlite3\n", filename) == ["PLC003"]


@pytest.mark.parametrize(
    "filename",
    [
        "src/example/scraping/integrations/unit_of_work/foo.py",
        "src/example/scraping/integrations/unit_of_work/sqlite_helpers.py",
    ],
)
def test_non_sqlalchemy_uow_modules_reject_sqlalchemy_import(filename: str) -> None:
    assert lint_codes("from sqlalchemy import select\n", filename) == ["PLC002"]


def test_sqlalchemy_uow_rejects_sqlite_import() -> None:
    assert lint_codes(
        "import sqlite3\n", "src/example/scraping/integrations/unit_of_work/sqlalchemy/idealista.py"
    ) == ["PLC003"]


def test_sqlite_uow_rejects_sqlalchemy_import() -> None:
    assert lint_codes(
        "from sqlalchemy import select\n",
        "src/example/scraping/integrations/unit_of_work/sqlite.py",
    ) == ["PLC002"]


@pytest.mark.parametrize(
    "module",
    [
        "example.scraping.integrations.persistence",
        "example_scraping.integrations.persistence",
        "example.scraping.integrations.unit_of_work",
        "example_scraping.integrations.unit_of_work",
    ],
)
def test_portable_scraping_rejects_parent_sqlalchemy_import(module: str) -> None:
    source = f"from {module} import sqlalchemy as sql, sqlalchemy as other\n"
    assert lint_codes(source, "src/example/scraping/sources/example/job.py") == ["PLC005"]


def test_portable_scraping_reports_one_sqlalchemy_uow_diagnostic_per_import() -> None:
    source = "import os, example_scraping.integrations.unit_of_work.sqlalchemy.idealista as sink\n"
    assert lint_codes(source, "src/example/scraping/sources/example/job.py") == ["PLC005"]


def test_portable_scraping_reports_one_diagnostic_for_two_sql_storage_modules() -> None:
    source = (
        "import example.scraping.integrations.persistence.sqlalchemy as adapter, "
        "example.scraping.integrations.unit_of_work.sqlalchemy as uow\n"
    )
    assert lint_codes(source, "src/example/scraping/sources/example/job.py") == ["PLC005"]


@pytest.mark.parametrize(
    ("module", "filename"),
    [
        (
            "example.scraping.integrations.unit_of_work.sqlalchemy.idealista",
            "src/example/scraping/sources/example/job.py",
        ),
        (
            "example_scraping.integrations.unit_of_work.sqlalchemy.idealista",
            "src/example/scraping/sources/example/service.py",
        ),
        (
            "example.scraping.integrations.unit_of_work.sqlalchemy.idealista",
            "src/example/scraping/sources/example/router.py",
        ),
    ],
)
def test_portable_scraping_rejects_sqlalchemy_uow_imports(module: str, filename: str) -> None:
    if filename.endswith("router.py"):
        source = f"\ndef load_sink():\n    from {module} import PostgresExperimentSink\n"
    else:
        source = f"import {module} as sink\n"
    assert lint_codes(source, filename) == ["PLC005"]


@pytest.mark.parametrize("module_prefix", ["example.scraping", "example_scraping"])
def test_composition_allows_both_sqlalchemy_uow_spellings(module_prefix: str) -> None:
    source = (
        f"from {module_prefix}.integrations.unit_of_work.sqlalchemy.idealista "
        "import PostgresExperimentSink\n"
    )
    assert lint_codes(source, "src/example/scraping/app/scraping_dependencies.py") == []


@pytest.mark.parametrize(
    "filename",
    [
        "src/example/scraping/integrations/persistence/sqlalchemy/bridge.py",
        "src/example/scraping/integrations/unit_of_work/sqlalchemy/bridge.py",
    ],
)
@pytest.mark.parametrize("module_prefix", ["example.scraping", "example_scraping"])
def test_sql_storage_boundaries_allow_sqlalchemy_uow_callers(
    filename: str, module_prefix: str
) -> None:
    source = (
        f"from {module_prefix}.integrations.unit_of_work.sqlalchemy.idealista "
        "import PostgresExperimentSink\n"
    )
    assert lint_codes(source, filename) == []


@pytest.mark.parametrize(
    ("module", "name"),
    [
        ("example.domains.fetch.model", "FetchRun"),
        ("example.domains.fetch.persistence.models", "FetchRun"),
        ("example.domains.agency.persistence.models", "Agency"),
        ("example.domains.listing.persistence.models", "Listing"),
    ],
)
def test_orm_mapping_import_in_portable_scraping_fails(module: str, name: str) -> None:
    source = f"from {module} import {name}\n"
    assert lint_codes(source, "src/example/scraping/sources/example/policy.py") == ["PLC006"]


def test_portable_type_from_mixed_model_module_passes() -> None:
    source = "from example.domains.fetch.model import EraFetchData\n"
    assert lint_codes(source, "src/example/scraping/sources/era/transform.py") == []
