from __future__ import annotations

import ast

import pytest
from conftest import Project

from lint_it import engine
from lint_it.rules.capabilities import EffectfulCapabilityRule

CORE = "src/example/domains/orders/core.py"
MODEL = "src/example/domains/orders/model.py"
PORTS = "src/example/domains/orders/ports.py"
SERVICE = "src/example/domains/orders/service.py"


@pytest.mark.parametrize(
    "source",
    [
        "from uuid import uuid4 as make_id\ndef calculate():\n    return make_id()",
        "import datetime as dt\ndef calculate():\n    return dt.datetime.now(dt.UTC)",
        "import random\nvalue = random.choice(('a', 'b'))",
        "import secrets\ntoken = secrets.token_hex()",
        "import time\nstart = time.monotonic()",
        "import os\nseed = os.urandom(8)",
        """\
        import uuid
        from dataclasses import dataclass, field
        @dataclass(frozen=True)
        class Value:
            id: uuid.UUID = field(default_factory=uuid.uuid4)
        """,
        """\
        from datetime import datetime
        from dataclasses import dataclass, field
        @dataclass(frozen=True)
        class Created:
            at: datetime = field(default_factory=datetime.now)
        """,
    ],
)
def test_lit201_rejects_nondeterminism_in_core(project: Project, source: str) -> None:
    [finding] = project.write({CORE: source}).findings(CORE)
    assert finding.code == "LIT201"
    assert "pass the observed" in finding.message


def test_lit201_allows_deterministic_ids(project: Project) -> None:
    source = "import uuid\ndef calculate(namespace, key):\n    return uuid.uuid5(namespace, key)"
    assert project.lint(CORE, source) == []


@pytest.mark.parametrize(
    "source",
    [
        "from datetime import datetime as D\nnow = D.now()",
        "import datetime as dt\nnow = dt.datetime.utcnow()",
        "from datetime import date\nnow = date.today()",
        "import time as t\nnow = t.time_ns()",
        "from time import time as read\nnow = read()",
        "from datetime import datetime\nread = datetime.now",
    ],
)
@pytest.mark.parametrize("path", [SERVICE, "src/example/app/main.py", "scripts/report.py"])
def test_lit201_requires_the_clock_outside_core(project: Project, path: str, source: str) -> None:
    [finding] = project.write({path: source}).findings(path)
    assert finding.code == "LIT201"
    assert "workspace.clock_modules" in finding.message


@pytest.mark.parametrize(
    "source",
    [
        "import time\nstart = time.monotonic()",
        "import time\nstart = time.perf_counter_ns()",
        "import uuid\nvalue = uuid.uuid4()",
        "class Clock:\n    def now(self): ...\nnow = Clock().now()",
    ],
)
def test_lit201_allows_other_sources_outside_core(project: Project, source: str) -> None:
    assert project.lint(SERVICE, source) == []


def test_lit201_exempts_clock_modules_and_tests_but_not_core(project: Project) -> None:
    project.manifest(
        '[workspace]\nclock_modules = ["example.integrations.clock", "example.domains.orders.core"]'
    )
    read = "from datetime import datetime\nnow = datetime.now()\n"
    assert project.lint("src/example/integrations/clock.py", read) == []
    assert project.lint("src/example/integrations/other.py", read) == ["LIT201"]
    assert project.lint("tests/test_clock.py", read) == []
    assert project.lint(CORE, read) == ["LIT201"]


@pytest.mark.parametrize(
    "source",
    [
        "from pathlib import Path\ndef read(path: Path):\n    return path.read_text()",
        'from pathlib import Path as P\ndef read():\n    return P("x").exists()',
        'import pathlib as p\ndef read():\n    return p.Path("x").read_bytes()',
        'import logging as log\ndef decide():\n    log.warning("x")',
        'import logging\ndef decide():\n    logging.getLogger(__name__).info("x")',
        'from builtins import open as read\ndef decide():\n    return read("x")',
        'import sys\ndef decide():\n    sys.stderr.write("x")',
        'from pathlib import Path\nREADER = Path("x").read_text',
        "print('x')",
        "import shutil\nshutil.rmtree('x')",
    ],
)
@pytest.mark.parametrize("path", [CORE, PORTS])
def test_lit202_rejects_io_in_core(project: Project, path: str, source: str) -> None:
    assert "LIT202" in project.lint(path, source)


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
        """\
        import logging
        def calculate(flag, other):
            if flag:
                target = logging
            else:
                target = other
            return target.info(1)
        """,
        "import logging\ndef calculate():\n    return logging.info(1)\nlogging = object()",
        """\
        import logging
        def calculate(value):
            match value:
                case logging:
                    return logging.info(1)
        """,
        """\
        import logging
        def calculate():
            try:
                work()
            except ValueError as logging:
                return logging.info(1)
        """,
    ],
)
def test_lit202_does_not_invent_effects_for_shadowed_names(project: Project, source: str) -> None:
    assert "LIT202" not in project.lint(CORE, source)


def test_lit202_allows_io_in_the_shell(project: Project) -> None:
    assert project.lint(SERVICE, "print('x')\nopen('x')\n") == []


@pytest.mark.parametrize(
    "source",
    [
        "STATE = []\ndef calculate():\n    return len(STATE)",
        "count = 0\ndef calculate():\n    global count\n    count += 1",
        """\
        import contextvars
        request = contextvars.ContextVar("request")
        def calculate():
            return request.get()
        """,
        "from decimal import getcontext\ndef calculate():\n    return getcontext().prec",
        "import os\ndef calculate():\n    return os.getcwd()",
    ],
)
def test_lit203_rejects_ambient_state(project: Project, source: str) -> None:
    assert "LIT203" in project.lint(CORE, source)


@pytest.mark.parametrize(
    "source",
    [
        "STATE = []\ndef calculate(STATE):\n    return len(STATE)",
        """\
        STATE = []
        def calculate():
            STATE = (1, 2)
            def count():
                return len(STATE)
            return count()
        """,
    ],
)
def test_lit203_respects_shadowing(project: Project, source: str) -> None:
    assert project.lint(CORE, source) == []


def test_lit203_leaves_environment_to_lit301(project: Project) -> None:
    assert project.lint(CORE, "import os\nvalue = os.getenv('X')\n") == ["LIT301"]


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
        'def calculate(items: list[object]):\n    copied = list(items)\n    copied[0].status = "x"',
        'def calculate(items: list[object]):\n    for item in items:\n        item.status = "x"',
        'def calculate(items: list[object]):\n    copied = items[:]\n    copied[0].status = "x"',
    ],
)
def test_lit204_rejects_borrowed_mutation(project: Project, source: str) -> None:
    assert "LIT204" in project.lint(CORE, source)


@pytest.mark.parametrize(
    "source",
    [
        """\
        def calculate(items: tuple[int, ...]):
            result = []
            for item in items:
                result.append(item)
            return tuple(result)
        """,
        "def calculate(items: list[int]):\n    copied = list(items)\n    copied.sort()",
        "def calculate(items: list[int]):\n    alias = items\n    alias = []\n    alias.append(1)",
        "def calculate(number: int):\n    number += 1\n    return number",
        "def calculate(items: list[int]):\n    def nested(items):\n        items.clear()",
        "def calculate(items: list[int]):\n    return [items.clear() for items in [[], []]]",
    ],
)
def test_lit204_allows_local_mutation(project: Project, source: str) -> None:
    assert "LIT204" not in project.lint(CORE, source)


@pytest.mark.parametrize(
    "source",
    [
        "from dataclasses import dataclass\n@dataclass\nclass Order:\n    id: str",
        "from dataclasses import dataclass as dc\n@dc(frozen=True)\nclass Order:\n    i: list[str]",
        """\
        from dataclasses import dataclass
        @dataclass(frozen=True)
        class Order:
            ids: tuple[dict[str, int], ...]
        """,
    ],
)
@pytest.mark.parametrize("path", [MODEL, PORTS])
def test_lit205_rejects_mutable_records(project: Project, path: str, source: str) -> None:
    assert project.lint(path, source) == ["LIT205"]


def test_lit205_allows_frozen_records(project: Project) -> None:
    source = """\
        from dataclasses import dataclass
        from typing import ClassVar
        @dataclass(frozen=True)
        class Order:
            ids: tuple[str, ...]
            registry: ClassVar[dict[str, int]] = {}
    """
    assert project.lint(MODEL, source) == []


@pytest.mark.parametrize(
    "source",
    [
        "async def calculate(repo):\n    return await repo.load()",
        "import asyncio\ndef calculate():\n    asyncio.create_task(work())",
        "async def calculate(stream):\n    async for value in stream:\n        pass",
        "async def calculate(lock):\n    async with lock:\n        pass",
        "import threading\nworker = threading.Thread(target=int)",
    ],
)
def test_lit206_keeps_async_out_of_core(project: Project, source: str) -> None:
    assert project.lint(CORE, source) == ["LIT206"]
    assert "LIT206" not in project.lint(SERVICE, source)
    assert "LIT206" not in project.lint(PORTS, source)


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
def test_lit207_resolves_wrapped_and_forward_annotations(project: Project, annotation: str) -> None:
    project.write(
        {
            CORE: "from sqlalchemy.orm import Session as S\n"
            "from typing import Annotated, Optional\n"
            f"def decide(session: {annotation}): ...\n"
        }
    )
    [finding] = [item for item in project.findings(CORE) if item.code == "LIT207"]
    assert "sqlalchemy.orm.Session" in finding.message


@pytest.mark.parametrize(
    "signature",
    [
        "def decide(session: S, /): ...",
        "def decide(*, session: S): ...",
        "def decide(*session: S): ...",
        "def decide(**session: S): ...",
        "class Decision:\n    def __init__(self, session: S): ...",
        "async def decide(session: S): ...",
    ],
)
def test_lit207_checks_every_parameter_position(project: Project, signature: str) -> None:
    source = "from httpx import Client as S\n" + signature
    assert project.write({CORE: source}).codes(CORE).count("LIT207") == 1


@pytest.mark.parametrize(
    "type_name",
    [
        "httpx.AsyncClient",
        "requests.Session",
        "aiohttp.ClientSession",
        "io.TextIOBase",
        "typing.BinaryIO",
        "fsspec.AbstractFileSystem",
        "sqlite3.Connection",
    ],
)
def test_lit207_knows_library_capabilities(project: Project, type_name: str) -> None:
    module, _, name = type_name.rpartition(".")
    source = f"from {module} import {name}\ndef decide(value: {name}): ...\n"
    assert "LIT207" in project.lint(CORE, source)


@pytest.mark.parametrize(
    "source",
    [
        "from pathlib import Path\ndef decide(path: Path): ...",
        "class Repository: ...\ndef decide(repository: Repository): ...",
        "from unknown import Session\ndef decide(session: Session): ...",
        "from typing import Callable\ndef decide(fn: Callable[[int], int]): ...",
        "from typing import Any\ndef decide(session: Any): ...",
        "def decide(session): ...",
        "from sqlalchemy.orm import Session\nclass Session: ...\ndef decide(s: Session): ...",
        "from typing import Literal\nfrom io import IOBase\ndef f(x: Literal['IOBase']): ...",
        "from typing import Annotated as A\nfrom io import IOBase\ndef f(x: A[int, IOBase]): ...",
    ],
)
def test_lit207_does_not_guess(project: Project, source: str) -> None:
    assert "LIT207" not in project.lint(CORE, source)


@pytest.mark.parametrize("path", [SERVICE, PORTS])
def test_lit207_allows_capabilities_outside_core(project: Project, path: str) -> None:
    assert "LIT207" not in project.lint(path, "from io import IOBase\ndef run(f: IOBase): ...\n")


def test_lit207_registry_resolves_relative_imports(project: Project) -> None:
    project.manifest('[workspace]\neffectful_types = ["example.domains.orders.ports.Clock"]\n')
    project.write(
        {PORTS: "class Clock: ...\n", CORE: "from .ports import Clock as C\ndef f(c: C): ...\n"}
    )
    [finding] = project.findings(CORE)
    assert "example.domains.orders.ports.Clock" in finding.message


def test_lit207_follows_assignment_aliases(project: Project) -> None:
    source = "from io import IOBase\nStream = IOBase\ndef decide(stream: Stream): ...\n"
    assert project.lint(MODEL, source) == ["LIT207"]


def test_lit207_does_not_mutate_the_snapshot(project: Project) -> None:
    project.write({CORE: 'from io import IOBase\ndef decide(stream: "IOBase | None"): ...\n'})
    workspace = project.load()
    before = ast.dump(workspace.sources[0].tree)

    assert engine.check(workspace, [EffectfulCapabilityRule()])
    assert ast.dump(workspace.sources[0].tree) == before


def test_strings_that_cannot_be_annotations_do_not_break_resolution(project: Project) -> None:
    source = 'SURROGATE = "\\ud800"\nOCTAL = "1_a"\nPROSE = """line\nline"""\n'

    assert project.lint("src/example/domains/orders/core.py", source) == []
