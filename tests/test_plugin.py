import ast

from lint_it.plugin import LintItChecker


def lint_codes(source: str, filename: str) -> list[str]:
    tree = ast.parse(source)
    errors = LintItChecker(tree=tree, filename=filename).run()

    return [message.split()[0] for _, _, message, _ in errors]


def test_internal_function_immutable_default_passes() -> None:
    source = """
def list_items(active: bool = True) -> list[str]:
    return []
"""

    assert lint_codes(source, "src/finance_api/domains/listing/service.py") == []


def test_internal_async_function_immutable_default_passes() -> None:
    source = """
async def list_items(active: bool = True) -> list[str]:
    return []
"""

    assert lint_codes(source, "src/finance_api/domains/listing/repository.py") == []


def test_required_keyword_only_argument_passes() -> None:
    source = """
def list_items(*, active: bool) -> list[str]:
    return []
"""

    assert lint_codes(source, "src/finance_api/domains/listing/service.py") == []


def test_keyword_only_immutable_default_passes() -> None:
    source = """
def list_items(*, active: bool = True) -> list[str]:
    return []
"""

    assert lint_codes(source, "src/finance_api/domains/listing/service.py") == []


def test_protocol_method_default_passes() -> None:
    source = """
from typing import Protocol


class ListingRepo(Protocol):
    def list_items(self, active: bool | None = None) -> list[str]: ...
"""

    assert lint_codes(source, "src/finance_api/domains/listing/repository.py") == []


def test_nested_protocol_method_default_passes() -> None:
    source = """
import typing


class ListingRepo(typing.Protocol):
    async def list_items(self, active: bool | None = None) -> list[str]: ...
"""

    assert lint_codes(source, "src/finance_api/domains/listing/repository.py") == []


def test_exception_constructor_default_passes() -> None:
    source = """
class ListingError(Exception):
    def __init__(self, message: str = 'failed') -> None:
        super().__init__(message)
"""

    assert lint_codes(source, "src/finance_api/domains/listing/model.py") == []


def test_error_named_constructor_default_passes() -> None:
    source = """
class ListingError:
    def __init__(self, message: str = 'failed') -> None:
        self.message = message
"""

    assert lint_codes(source, "src/finance_api/domains/listing/model.py") == []


def test_exception_non_constructor_immutable_default_passes() -> None:
    source = """
class ListingError(Exception):
    def with_context(self, source: str = 'listing') -> object:
        return self
"""

    assert lint_codes(source, "src/finance_api/domains/listing/model.py") == []


def test_router_default_passes() -> None:
    source = """
from fastapi import Query


def list_items(active: bool = Query(True)) -> list[str]:
    return []
"""

    assert lint_codes(source, "src/finance_api/app/routers/listing.py") == []


def test_fastapi_route_default_passes_outside_router_file() -> None:
    source = """
def create_app():
    @app.get('/items')
    async def list_items(active: bool | None = None) -> list[str]:
        return []
"""

    assert lint_codes(source, "src/finance_api/runner/internal_app.py") == []


def test_fastapi_dependency_default_passes_outside_router_file() -> None:
    source = """
from fastapi import Header


async def require_secret(x_secret: str | None = Header(default=None)) -> None:
    return None
"""

    assert lint_codes(source, "src/finance_api/runner/internal_app.py") == []


def test_admin_router_default_passes() -> None:
    source = """
def list_items(active: bool = True) -> list[str]:
    return []
"""

    assert lint_codes(source, "src/finance_api/domains/listing/admin_router.py") == []


def test_dependency_default_passes() -> None:
    source = """
def current_user(required: bool = True) -> object:
    return object()
"""

    assert lint_codes(source, "src/finance_api/domains/auth/dependency.py") == []


def test_cli_default_passes() -> None:
    source = """
def main(verbose: bool = False) -> int:
    return 0
"""

    assert lint_codes(source, "src/finance_api/scraping/cli.py") == []


def test_config_default_passes() -> None:
    source = "def load_config(path=None):\n    return path\n"

    assert lint_codes(source, "src/ariadne/config.py") == []


def test_script_default_passes() -> None:
    source = """
def main(limit: int = 100) -> int:
    return limit
"""

    assert lint_codes(source, "src/finance_api/scripts/backfill.py") == []


def test_migration_default_passes() -> None:
    source = """
def upgrade(batch_size: int = 1000) -> None:
    return None
"""

    assert lint_codes(source, "src/finance_api/migrations/versions/abc.py") == []


def test_test_default_passes() -> None:
    source = """
def build_user(active: bool = True) -> object:
    return object()
"""

    assert lint_codes(source, "src/tests/user/test_user_service.py") == []


def test_in_tree_test_module_default_passes() -> None:
    source = """
def make_run(status: str = 'pending') -> object:
    return object()
"""

    assert lint_codes(source, "src/finance_api/runner/store_test.py") == []
