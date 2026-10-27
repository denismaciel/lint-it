from __future__ import annotations

import pytest

from lint_it.globs import matches_glob


@pytest.mark.parametrize(
    ("path", "glob"),
    [
        ("src/example/core.py", "src/*/core.py"),
        ("src/example/core.py", "src/**/*.py"),
        ("src/example/a/b/core.py", "src/**/*.py"),
        ("src/example/domains/orders/core.py", "src/*/domains/**/core.py"),
        ("src/example/domains/core.py", "src/*/domains/**/core.py"),
        ("tests/test_x.py", "tests/**"),
        ("tests/a/b.py", "tests/**"),
        ("conftest.py", "conftest.py"),
        ("src/example/v2.py", "src/example/v[0-9].py"),
        ("src/example/a.py", "src/example/?.py"),
    ],
)
def test_matches(path: str, glob: str) -> None:
    assert matches_glob(path, glob)


@pytest.mark.parametrize(
    ("path", "glob"),
    [
        ("src/example/a/core.py", "src/*/core.py"),
        ("tests/conftest.py", "conftest.py"),
        ("src/core.py", "src/*/domains/**/core.py"),
        ("src/example/core.pyi", "src/**/*.py"),
        ("src/example/ab.py", "src/example/?.py"),
        ("src/example.py", "src/**/x.py"),
    ],
)
def test_does_not_match(path: str, glob: str) -> None:
    assert not matches_glob(path, glob)
