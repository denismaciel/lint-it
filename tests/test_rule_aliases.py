import ast

import pytest

from lint_it.core import check_tree
from lint_it.rules.registry import ALL_RULES


def lint_codes(source: str, filename: str) -> list[str]:
    return [item.code for item in check_tree(ast.parse(source), filename, ALL_RULES)]


CANONICAL_RUNTIME_SETTINGS = """\
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='EXAMPLE_')

def load_settings() -> Settings:
    return Settings()
"""


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
def test_environment_rule_resolves_aliases(source: str) -> None:
    assert "PAL004" in lint_codes(source, "src/example/domains/orders/service.py")


def test_environment_rule_respects_parameter_shadowing() -> None:
    source = "import os\ndef read(os):\n    return os.getenv('VALUE')"
    assert "PAL004" not in lint_codes(source, "src/example/domains/orders/service.py")


@pytest.mark.parametrize("directory", ["router", "routers"])
def test_application_router_aliases_cannot_construct_clients(directory: str) -> None:
    source = "from httpx import AsyncClient as ClientAlias\nclient = ClientAlias()"
    assert "PAL006" in lint_codes(source, f"src/example/app/{directory}/orders.py")


CUSTOM_RUNTIME_SETTINGS = """\
from pydantic import BaseModel
ENV_PREFIX = 'EXAMPLE_'
class Settings(BaseModel):
    database_url: str

def load_settings() -> Settings:
    return Settings(database_url='example')
"""


def test_runtime_settings_covers_custom_pydantic_loaders() -> None:
    assert lint_codes(CUSTOM_RUNTIME_SETTINGS, "src/example/app/config.py") == []
    legacy = (
        CUSTOM_RUNTIME_SETTINGS.replace("Settings", "Config")
        .replace("load_settings", "load_config")
        .replace("ENV_PREFIX = 'EXAMPLE_'\n", "")
    )
    assert lint_codes(legacy, "src/example/shared/config.py") == ["PAL018"] * 4


def test_plain_pydantic_value_is_not_runtime_settings() -> None:
    assert "PAL018" not in lint_codes(
        "from pydantic import BaseModel\nclass Config(BaseModel): pass",
        "src/example/shared/config.py",
    )


def test_runtime_settings_detects_aliased_base_settings() -> None:
    source = CANONICAL_RUNTIME_SETTINGS.replace(
        "import BaseSettings,", "import BaseSettings as RuntimeBase,"
    ).replace("Settings(BaseSettings)", "Settings(RuntimeBase)")
    assert lint_codes(source, "src/example/shared/config.py") == ["PAL018"]
