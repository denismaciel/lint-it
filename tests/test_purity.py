import ast
from pathlib import Path

import pytest

from lint_it.core import check_tree
from lint_it.filesystem import check_paths, workspace_architecture
from lint_it.rules.registry import ALL_RULES

CORE = "src/example/domains/orders/core.py"


def codes(source: str, filename: str = CORE) -> set[str]:
    return {item.code for item in check_tree(ast.parse(source), filename, ALL_RULES)}


@pytest.mark.parametrize(
    "source",
    [
        "from pathlib import Path\ndef read(path: Path):\n    return path.read_text()",
        'from pathlib import Path as P\ndef read():\n    p = P("x")\n    return p.exists()',
        'import pathlib as p\ndef read():\n    return p.Path("x").read_bytes()',
        'import logging as log\ndef decide():\n    log.warning("x")',
        (
            "import logging\ndef decide():\n    logger = logging.getLo"
            'gger(__name__)\n    logger.info("x")'
        ),
        'from builtins import open as read\ndef decide():\n    return read("x")',
        'import sys\ndef decide():\n    sys.stderr.write("x")',
        'from pathlib import Path\nREADER = Path("x").read_text',
    ],
)
def test_known_io_is_rejected(source: str) -> None:
    assert "PAL014" in codes(source)


@pytest.mark.parametrize(
    "source",
    [
        "def calculate(open):\n    return open(1)",
        "import logging\ndef calculate(logging):\n    return logging.warning(1)",
        'from pathlib import PurePosixPath\ndef calculate():\n    return PurePosixPath("x").name',
        "def calculate(value):\n    return value.read_text()",
        "def other():\n    import logging\ndef calculate(logging):\n    return logging.info(1)",
        "import logging\ndef calculate():\n    logging = object()\n    return logging.info(1)",
        "import logging\nvalues = [logging.info(1) for logging in ()]",
        (
            "import logging\ndef calculate(flag, other):\n    if flag:"
            "\n        target = logging\n    else:\n        target = ot"
            "her\n    return target.info(1)"
        ),
    ],
)
def test_unresolved_or_shadowed_names_are_not_invented_effects(source: str) -> None:
    assert "PAL014" not in codes(source)


@pytest.mark.parametrize(
    "source",
    [
        "from uuid import uuid4 as make_id\ndef calculate():\n    return make_id()",
        "import datetime as dt\ndef calculate():\n    return dt.datetime.now(dt.UTC)",
        (
            "import uuid\nfrom dataclasses import dataclass, field\n@d"
            "ataclass(frozen=True)\nclass Value:\n    id: uuid.UUID = "
            "field(default_factory=uuid.uuid4)"
        ),
    ],
)
def test_nondeterminism_in_calls_and_factories_is_rejected(source: str) -> None:
    assert "PAL011" in codes(source)


def test_explicit_deterministic_id_is_allowed() -> None:
    assert "PAL011" not in codes(
        "import uuid\ndef calculate(namespace, key):\n    return uuid.uuid5(namespace, key)"
    )


@pytest.mark.parametrize(
    "source",
    [
        "def calculate(items: list[int]):\n    items.append(1)",
        "def calculate(items: list[int]):\n    alias = items\n    alias.clear()",
        'def calculate(items: dict[str, int]):\n    items["a"] = 1',
        'def calculate(order):\n    order.status = "sent"',
        "def calculate(order):\n    del order.status",
        'def calculate(order):\n    setattr(order, "status", "sent")',
        "def calculate(items: list[int]):\n    items += [1]",
        (
            "def calculate(items: list[object]):\n    copied = list(i"
            'tems)\n    copied[0].status = "sent"'
        ),
        'def calculate(items: list[object]):\n    for item in items:\n        item.status = "sent"',
        (
            "def calculate(items: list[object]):\n    copied = items["
            ':] \n    copied[0].status = "sent"'
        ),
    ],
)
def test_borrowed_mutation_is_rejected(source: str) -> None:
    assert "PAL019" in codes(source)


@pytest.mark.parametrize(
    "source",
    [
        (
            "def calculate(items: tuple[int, ...]):\n    result = []\n"
            "    for item in items:\n        result.append(item)\n    "
            "return tuple(result)"
        ),
        (
            "def calculate(items: list[int]):\n    copied = list(item"
            "s)\n    copied.sort()\n    return tuple(copied)"
        ),
        "def calculate(items: list[int]):\n    alias = items\n    alias = []\n    alias.append(1)",
        "def calculate(number: int):\n    number += 1\n    return number",
        "def calculate(items: list[int]):\n    def nested(items):\n        items.clear()",
    ],
)
def test_local_mutation_and_rebinding_are_allowed(source: str) -> None:
    assert "PAL019" not in codes(source)


@pytest.mark.parametrize(
    "source",
    [
        "STATE = []\ndef calculate():\n    return len(STATE)",
        "count = 0\ndef calculate():\n    global count\n    count += 1",
        (
            'import contextvars\nrequest = contextvars.ContextVar("re'
            'quest")\ndef calculate():\n    return request.get()'
        ),
        "from decimal import getcontext\ndef calculate():\n    return getcontext().prec",
    ],
)
def test_ambient_state_is_rejected(source: str) -> None:
    assert "PAL020" in codes(source)


def test_local_shadow_of_mutable_global_is_allowed() -> None:
    assert "PAL020" not in codes("STATE = []\ndef calculate(STATE):\n    return len(STATE)")


@pytest.mark.parametrize(
    "source",
    [
        "from dataclasses import dataclass\n@dataclass\nclass Order:\n    id: str",
        (
            "from dataclasses import dataclass as dc\n@dc(frozen=True"
            ")\nclass Order:\n    ids: list[str]"
        ),
        (
            "from dataclasses import dataclass\n@dataclass(frozen=Tru"
            "e)\nclass Order:\n    ids: tuple[dict[str, int], ...]"
        ),
    ],
)
def test_mutable_value_records_are_rejected(source: str) -> None:
    assert "PAL021" in codes(source)


def test_frozen_value_record_with_immutable_collections_is_allowed() -> None:
    assert "PAL021" not in codes(
        "from dataclasses import dataclass\n@dataclass(frozen=Tru"
        "e)\nclass Order:\n    ids: tuple[str, ...]"
    )


@pytest.mark.parametrize(
    "source",
    [
        "async def calculate(repo):\n    return await repo.load()",
        "import asyncio\ndef calculate():\n    asyncio.create_task(work())",
        "async def calculate(stream):\n    async for value in stream:\n        pass",
        "async def calculate(lock):\n    async with lock:\n        pass",
    ],
)
def test_async_execution_is_rejected_in_core(source: str) -> None:
    assert "PAL022" in codes(source)
    assert "PAL022" not in codes(source, "src/example/domains/orders/service.py")
    assert "PAL022" not in codes(source, "src/example/domains/orders/ports.py")


def test_snapshot_analysis_is_independent_of_live_files(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="example"\nversion="1"')
    (tmp_path / "lint-it.toml").write_text("")
    path = tmp_path / "src/example/domains/orders/core.py"
    path.parent.mkdir(parents=True)
    path.write_text('from pathlib import Path\nvalue = Path("x").read_text()')
    snapshot = workspace_architecture(tmp_path)
    before = check_tree(snapshot.sources[0].tree, str(path), ALL_RULES, snapshot)
    path.unlink()
    (tmp_path / "lint-it.toml").unlink()
    assert check_tree(snapshot.sources[0].tree, str(path), ALL_RULES, snapshot) == before
    assert any(item.code == "PAL014" for item in before)


@pytest.mark.parametrize(
    "statement", ["from support import fetch", "from support.model import Value"]
)
def test_cross_package_reexport_cannot_hide_adapter(tmp_path: Path, statement: str) -> None:
    (tmp_path / "lint-it.toml").write_text(
        '[[packages]]\npath="packages/support"\nprofile="infrastructure"'
    )
    paths = {
        "pyproject.toml": '[project]\nname="app"\nversion="1"',
        "packages/support/pyproject.toml": '[project]\nname="support"\nversion="1"',
        "src/app/domains/orders/core.py": statement,
        "packages/support/src/support/model.py": "class Value: pass",
        "packages/support/src/support/__init__.py": "from support.adapters.client import fetch\n",
        "packages/support/src/support/adapters/client.py": "def fetch():\n    return 1\n",
    }
    for relative, source in paths.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    result = check_paths([tmp_path / "src/app/domains/orders/core.py"], ALL_RULES)
    assert any(item.code == "PAL017" and "adapter" in item.message for item in result)


@pytest.mark.parametrize(
    "source",
    [
        "import logging\ndef calculate():\n    return logging.info(1)\nlogging = object()",
        "import logging\ndef calculate(value):\n    match value:\n"
        "        case logging:\n            return logging.info(1)",
        "import logging\ndef calculate():\n    try:\n        work()\n"
        "    except ValueError as logging:\n        return logging.info(1)",
    ],
)
def test_late_globals_and_pattern_bindings_do_not_invent_effects(source: str) -> None:
    assert "PAL014" not in codes(source)


@pytest.mark.parametrize(
    "source",
    [
        "def calculate(items=[]):\n    return items",
        "def calculate(items={}):\n    return items",
        "def calculate(items=set()):\n    return items",
    ],
)
def test_mutable_core_defaults_are_rejected(source: str) -> None:
    assert "PAL001" in codes(source)


def test_import_time_factories_cannot_hide_observed_time() -> None:
    assert "PAL011" in codes(
        "from datetime import datetime\nfrom dataclasses import dataclass, field\n"
        "@dataclass(frozen=True)\nclass Created:\n"
        "    created_at: datetime = field(default_factory=datetime.now)"
    )


def test_comprehension_target_shadows_borrowed_argument() -> None:
    assert "PAL019" not in codes(
        "def calculate(items: list[int]):\n    return [items.clear() for items in [[], []]]"
    )


def test_closure_over_local_value_is_not_a_read_of_same_named_module_state() -> None:
    assert "PAL020" not in codes(
        "STATE = []\ndef calculate():\n    STATE = (1, 2)\n"
        "    def count():\n        return len(STATE)\n    return count()"
    )
