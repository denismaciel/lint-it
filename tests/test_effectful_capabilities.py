import ast
from pathlib import Path

import pytest

from lint_it.core import check_tree
from lint_it.filesystem import check_paths, workspace_architecture
from lint_it.rules.pal023 import EffectfulCapabilityRule

CORE = "src/example/domains/orders/core.py"


def findings(source: str, filename: str = CORE):
    return check_tree(ast.parse(source), filename, (EffectfulCapabilityRule(),))


@pytest.mark.parametrize(
    "annotation",
    [
        "S",
        "S | None",
        '"S | None"',
        "Optional[S]",
        'Optional["S"]',
        "Annotated[S, 'database']",
        '"Annotated[S, metadata]"',
        "list[S]",
    ],
)
def test_resolves_wrapped_and_forward_annotations(annotation: str) -> None:
    source = (
        "from sqlalchemy.orm import Session as S\n"
        "from typing import Annotated, Optional\n"
        f"def decide(session: {annotation}): pass"
    )
    result = findings(source)
    assert len(result) == 1
    assert "sqlalchemy.orm.Session" in result[0].message


@pytest.mark.parametrize(
    "signature",
    [
        "def decide(session: S, /): pass",
        "def decide(*, session: S): pass",
        "def decide(*session: S): pass",
        "def decide(**session: S): pass",
        "class Decision:\n    def __init__(self, session: S): pass",
        "async def decide(session: S): pass",
    ],
)
def test_checks_all_parameter_positions(signature: str) -> None:
    assert len(findings("from sqlalchemy.orm import Session as S\n" + signature)) == 1


@pytest.mark.parametrize(
    "type_name",
    [
        "httpx.Client",
        "httpx.AsyncClient",
        "requests.Session",
        "aiohttp.ClientSession",
        "io.TextIOBase",
        "typing.BinaryIO",
        "fsspec.AbstractFileSystem",
        "sqlite3.Connection",
    ],
)
def test_known_library_capabilities(type_name: str) -> None:
    module, _, name = type_name.rpartition(".")
    assert findings(f"import {module}\ndef decide(value: {module}.{name}): pass")


@pytest.mark.parametrize(
    "source",
    [
        "from pathlib import Path\ndef decide(path: Path): pass",
        "class Repository: pass\ndef decide(repository: Repository): pass",
        "from unknown import Session\ndef decide(session: Session): pass",
        "from typing import Callable\ndef decide(fn: Callable[[int], int]): pass",
        "from typing import Any\ndef decide(session: Any): pass",
        "def decide(session): pass",
        "from sqlalchemy.orm import Session\nclass Session: pass\ndef decide(s: Session): pass",
        "from typing import Literal\nfrom httpx import Client\n"
        "def decide(x: Literal['Client']): pass",
        "from typing import Annotated\nfrom httpx import Client\n"
        "def decide(x: Annotated[int, Client]): pass",
    ],
)
def test_does_not_guess_or_treat_metadata_as_types(source: str) -> None:
    assert findings(source) == []


@pytest.mark.parametrize(
    "filename",
    [
        "src/example/domains/orders/service.py",
        "src/example/domains/orders/ports.py",
        "src/example/app/service.py",
    ],
)
def test_shell_and_port_signatures_are_allowed(filename: str) -> None:
    assert findings("from httpx import Client\ndef execute(client: Client): pass", filename) == []


def test_explicit_registry_and_relative_imports(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="example"\nversion="1"')
    (tmp_path / "lint-it.toml").write_text(
        '[workspace]\neffectful_types=["example.domains.orders.ports.Clock"]'
    )
    path = tmp_path / CORE
    path.parent.mkdir(parents=True)
    path.write_text("from .ports import Clock as C\ndef decide(clock: C): pass")
    result = check_paths([path], (EffectfulCapabilityRule(),))
    assert len(result) == 1
    assert "example.domains.orders.ports.Clock" in result[0].message


@pytest.mark.parametrize("value", ['"Clock"', '["Clock"]', '["x.*"]', "[1]"])
def test_registry_rejects_invalid_type_names(tmp_path: Path, value: str) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="example"\nversion="1"')
    (tmp_path / "lint-it.toml").write_text(f"[workspace]\neffectful_types={value}")
    with pytest.raises(ValueError, match="effectful_types"):
        workspace_architecture(tmp_path)


def test_analysis_does_not_mutate_snapshot() -> None:
    tree = ast.parse('from httpx import Client\ndef decide(client: "Client | None"): pass')
    before = ast.dump(tree)
    assert check_tree(tree, CORE, (EffectfulCapabilityRule(),))
    assert ast.dump(tree) == before


@pytest.mark.parametrize("filename", [CORE, "src/example/domains/orders/model.py"])
def test_direct_assignment_alias(filename: str) -> None:
    assert findings(
        "from httpx import Client\nHttp = Client\ndef decide(client: Http): pass", filename
    )
