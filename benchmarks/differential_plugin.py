"""Run the existing behavioral fixtures against the native executable too.

uv run python -m pytest -p benchmarks.differential_plugin
LINT_IT_RUST_BINARY can select another build.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from lint_it import cli, engine
from lint_it.rules.registry import ALL_RULES

COMPARISONS = 0

BINARY = Path(os.environ.get("LINT_IT_RUST_BINARY", "rust/target/release/lint-it-rust")).resolve()


@pytest.fixture(autouse=True)
def native_equivalence(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    from lint_it.loader import ManifestError

    project_type = sys.modules["conftest"].Project
    original_load = project_type.load

    def compare_load(project):
        try:
            return original_load(project)
        except ManifestError as error:
            actual = subprocess.run(
                [str(BINARY), "check", "--root", str(project.root), "--format", "json"],
                capture_output=True,
                text=True,
                check=False,
            )
            assert actual.returncode == 2, actual.stderr
            assert json.loads(actual.stdout)["findings"][0]["message"] == str(error)
            raise

    monkeypatch.setattr(project_type, "load", compare_load)
    original = engine.run

    def compare(workspace, rules, selected=(), checker=None):
        global COMPARISONS
        rules = tuple(rules)
        result = original(workspace, rules, selected, checker)
        # In-memory snapshots and individual rule unit tests aren't CLI inputs.
        if (
            rules != ALL_RULES
            or any(not s.path.exists() for s in workspace.sources)
            or any(not (p.root / "pyproject.toml").exists() for p in workspace.packages)
        ):
            return result
        args = [
            str(BINARY),
            "check",
            "--root",
            str(workspace.root),
            "--format",
            "json",
            "--jobs",
            "1",
        ]
        if workspace.baseline_path is None:
            args.append("--no-baseline")
        args.extend(map(str, selected))
        process = subprocess.run(args, capture_output=True, text=True, check=False)
        expected = {
            "findings": [asdict(f) for f in result.findings],
            "summary": {
                "findings": len(result.findings),
                "packages": len(workspace.packages),
                "files": len(workspace.sources) + len(workspace.parse_failures),
                "baselined": len(result.baselined),
                "ignored": len(result.ignored),
            },
        }
        assert process.returncode == bool(result.findings), process.stderr + process.stdout
        assert json.loads(process.stdout) == expected
        COMPARISONS += 1
        return result

    monkeypatch.setattr(engine, "run", compare)
    original_main = cli.main

    def compare_cli(argv=None):
        if not argv or argv[0] in ("init", "baseline"):
            return original_main(argv)
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = original_main(argv)
        actual = subprocess.run([str(BINARY), *argv], capture_output=True, text=True, check=False)
        assert actual.returncode == exit_code, actual.stderr
        if "json" in argv:
            assert json.loads(actual.stdout) == json.loads(stdout.getvalue())
        else:
            assert actual.stdout == stdout.getvalue()
        assert actual.stderr == stderr.getvalue()
        sys.stdout.write(stdout.getvalue())
        sys.stderr.write(stderr.getvalue())
        return exit_code

    if getattr(request.module, "main", None) is original_main:
        monkeypatch.setattr(request.module, "main", compare_cli)
    yield


def pytest_terminal_summary(terminalreporter):
    terminalreporter.write_line(f"Native differential comparisons: {COMPARISONS}")
