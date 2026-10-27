from __future__ import annotations

import pytest
from conftest import Project

CORE = "src/example/domains/transfers/core.py"
POLICY = "src/example/domains/transfers/policy.py"
SERVICE = "src/example/domains/transfers/service.py"


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
