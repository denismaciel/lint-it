from __future__ import annotations

import pytest
from conftest import Project

from lint_it.loader import ManifestError

CORE = "src/example/domains/transfers/core.py"
POLICY = "src/example/domains/transfers/policy.py"
SERVICE = "src/example/domains/transfers/service.py"
ADAPTER = "src/example/domains/transfers/persistence/tables.py"


@pytest.mark.parametrize(
    "source",
    [
        "def plan(amount: int, *, urgent: bool) -> object: ...",
        "def plan(amount: int, urgent: bool | None) -> object: ...",
        "from typing import Optional\ndef plan(urgent: Optional[bool]) -> object: ...",
        "def decide(amount: int) -> bool: ...",
        "class Policy:\n    def decide(self, amount: int) -> bool: ...",
    ],
)
def test_lit401_rejects_boolean_policy_types(project: Project, source: str) -> None:
    assert project.lint(POLICY, source) == ["LIT401"]


@pytest.mark.parametrize(
    "source",
    [
        "def is_allowed(amount: int) -> bool: ...",
        "def has_funds(amount: int) -> bool: ...",
        "def _helper(flag: bool) -> bool: ...",
        "def plan(self, cls) -> object: ...",
    ],
)
def test_lit401_allows_predicates_and_private_helpers(project: Project, source: str) -> None:
    assert project.lint(POLICY, source) == []


def test_lit401_only_applies_to_core(project: Project) -> None:
    source = "def decide(urgent: bool) -> bool: ...\n"
    assert project.lint(SERVICE, source) == []
    assert project.lint("src/example/domains/transfers/ports.py", source) == []


def test_lit401_prefixes_are_configurable(project: Project) -> None:
    project.manifest('[conventions]\npredicate_prefixes = ["permits_"]\n')
    assert project.lint(POLICY, "def permits_transfer(a: int) -> bool: ...\n") == []
    assert project.lint(POLICY, "def is_allowed(a: int) -> bool: ...\n") == ["LIT401"]


@pytest.mark.parametrize(
    "source",
    [
        "def decide():\n    raise TransferRejected()",
        "def decide():\n    raise errors.TransferNotFound",
        """\
        def decide():
            try:
                transfer()
            except TransferConflict:
                return None
        """,
        """\
        def decide():
            try:
                transfer()
            except (ValueError, Expired):
                return None
        """,
    ],
)
def test_lit402_rejects_exceptions_as_outcomes(project: Project, source: str) -> None:
    assert project.lint(CORE, source) == ["LIT402"]


def test_lit402_allows_invariant_errors(project: Project) -> None:
    source = "def amount(value: int):\n    if value < 0:\n        raise ValueError('negative')\n"
    assert project.lint(CORE, source) == []


def test_lit402_only_applies_to_core(project: Project) -> None:
    assert project.lint(SERVICE, "def run():\n    raise TransferRejected()\n") == []


def test_lit402_suffixes_are_configurable(project: Project) -> None:
    project.manifest('[conventions]\noutcome_suffixes = ["Missing"]\n')
    assert project.lint(CORE, "def f():\n    raise AccountMissing()\n") == ["LIT402"]
    assert project.lint(CORE, "def f():\n    raise TransferRejected()\n") == []


@pytest.mark.parametrize(
    "source",
    [
        "class Missing(LookupError): ...",
        "class Count(int): ...",
        "class Plain: ...",
        "class Explicit(object): ...",
        "from enum import StrEnum\nclass Status(StrEnum): ...",
        "from typing import Protocol\nclass Clock(Protocol): ...",
        "import typing\nclass Point(typing.NamedTuple):\n    x: int",
        "from pydantic import BaseModel as B\nclass Body(B): ...",
        "from sqlalchemy.orm import DeclarativeBase\nclass Base(DeclarativeBase): ...",
        "from typing import Generic, TypeVar\nT = TypeVar('T')\nclass Box(Generic[T]): ...",
        """\
        from sqlalchemy.orm import DeclarativeBase
        class Base(DeclarativeBase): ...
        class Order(Base): ...
        """,
        """\
        from sqlalchemy.orm import declarative_base
        Base = declarative_base()
        class Order(Base): ...
        """,
        """\
        class DomainError(Exception): ...
        class TransferDenied(DomainError): ...
        """,
        """\
        class DomainError(Exception): ...
        class TransferError(DomainError): ...
        class TransferDenied(TransferError): ...
        """,
        """\
        from sqlalchemy.orm import DeclarativeBase
        class Base(DeclarativeBase): ...
        class Owned: ...
        class Order(Owned, Base): ...
        """,
    ],
)
def test_lit403_allows_listed_bases_and_one_workspace_level(project: Project, source: str) -> None:
    assert project.lint(ADAPTER, source) == []


@pytest.mark.parametrize(
    "source",
    [
        "class Base: ...\nclass Child(Base): ...",
        "class Base(object): ...\nclass Child(Base): ...",
        "import unittest\nclass Case(unittest.TestCase): ...",
        "from abc import ABC\nclass Repository(ABC): ...",
        "from collections import OrderedDict\nclass Cache(OrderedDict): ...",
        "def build():\n    return object\nclass Thing(build()): ...",
        "class Owned: ...\nclass Order(Owned): ...",
        """\
        from pydantic import BaseModel
        class Owned: ...
        class Body(Owned, BaseModel): ...
        """,
    ],
)
def test_lit403_rejects_other_bases(project: Project, source: str) -> None:
    assert project.lint(ADAPTER, source) == ["LIT403"]


def test_lit403_follows_workspace_imports_and_reexports(project: Project) -> None:
    project.write(
        {
            "src/example/db/base.py": (
                "from sqlalchemy.orm import DeclarativeBase\n"
                "class Base(DeclarativeBase): ...\n"
                "class Order(Base): ...\n"
            ),
            "src/example/db/__init__.py": "from .base import Base, Order\n",
            "src/example/models.py": (
                "from pydantic import BaseModel\nclass Model(BaseModel): ...\n"
            ),
            "src/example/legacy.py": (
                "from sqlalchemy.orm import declarative_base\nB = declarative_base()\n"
            ),
        }
    )
    assert project.lint(ADAPTER, "from example.db import Base\nclass Line(Base): ...\n") == []
    assert project.lint(ADAPTER, "import example.models as m\nclass Body(m.Model): ...\n") == []
    assert project.lint(ADAPTER, "from example.legacy import B\nclass Line(B): ...\n") == []
    assert project.lint(ADAPTER, "from example.db import Order\nclass Big(Order): ...\n") == [
        "LIT403"
    ]


def test_lit403_follows_imported_exceptions_and_mixins(project: Project) -> None:
    project.write(
        {
            "src/example/errors.py": (
                "class AppError(Exception): ...\nclass StorageError(AppError): ...\n"
            ),
            "src/example/db.py": (
                "from sqlalchemy.orm import DeclarativeBase\n"
                "class Base(DeclarativeBase): ...\n"
                "class Owned: ...\n"
                "class Audited(Owned): ...\n"
            ),
        }
    )
    assert (
        project.lint(ADAPTER, "from example.errors import StorageError as E\nclass X(E): ...\n")
        == []
    )
    assert (
        project.lint(ADAPTER, "from example.db import Base, Owned\nclass T(Owned, Base): ...\n")
        == []
    )
    assert project.lint(
        ADAPTER, "from example.db import Audited, Base\nclass T(Audited, Base): ...\n"
    ) == ["LIT403"]


def test_lit403_applies_to_every_layer(project: Project) -> None:
    source = "class Base: ...\nclass Child(Base): ...\n"
    assert project.lint(CORE, source) == ["LIT403"]
    assert project.lint("tests/test_orders.py", source) == ["LIT403"]


def test_lit403_bases_are_configurable(project: Project) -> None:
    source = "import ast\nclass Visitor(ast.NodeVisitor): ...\n"
    assert project.lint(ADAPTER, source) == ["LIT403"]
    project.manifest('[conventions]\nextend_allowed_bases = ["ast.*"]\n')
    assert project.lint(ADAPTER, source) == []
    assert project.lint(ADAPTER, "class Missing(LookupError): ...\n") == []
    project.manifest('[conventions]\nallowed_bases = ["ast.NodeVisitor"]\n')
    assert project.lint(ADAPTER, source) == []
    assert project.lint(ADAPTER, "class Missing(LookupError): ...\n") == ["LIT403"]


def test_lit403_rejects_invalid_base_names(project: Project) -> None:
    project.manifest('[conventions]\nallowed_bases = ["not a name"]\n')
    with pytest.raises(ManifestError, match=r"conventions\.allowed_bases"):
        project.load()
