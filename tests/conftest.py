from __future__ import annotations

import textwrap
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from lint_it import engine
from lint_it.core import Finding
from lint_it.loader import load_workspace
from lint_it.rules.registry import ALL_RULES
from lint_it.workspace import Workspace


@dataclass(frozen=True)
class Project:
    """A throwaway workspace: one root package named ``example`` unless told otherwise."""

    root: Path

    def write(self, files: Mapping[str, str]) -> Project:
        for relative, source in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(source), encoding="utf-8")
        return self

    def manifest(self, text: str) -> Project:
        return self.write({"lint-it.toml": text})

    def package(self, path: str, name: str) -> Project:
        return self.write({f"{path}/pyproject.toml": f'[project]\nname = "{name}"\n'})

    def load(self) -> Workspace:
        return load_workspace(self.root)

    def findings(self, *paths: str) -> list[Finding]:
        return engine.check(self.load(), ALL_RULES, tuple(self.root / path for path in paths))

    def codes(self, path: str) -> list[str]:
        return [item.code for item in self.findings(path) if item.filename == path]

    def lint(self, path: str, source: str) -> list[str]:
        """Codes reported for ``path`` after writing ``source`` to it."""
        return self.write({path: source}).codes(path)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return Project(tmp_path).write({"pyproject.toml": '[project]\nname = "example"\n'})
