"""Stateful CLI parity checks when a native release binary has been built."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BINARY = Path(
    os.environ.get(
        "LINT_IT_RUST_BINARY",
        str(Path(__file__).resolve().parents[1] / "rust/target/release/lint-it-rust"),
    )
).resolve()
pytestmark = pytest.mark.skipif(not BINARY.is_file(), reason="build the native executable first")


@pytest.mark.parametrize("output", ["text", "json", "github"])
def test_native_stateful_cli_matches_python(tmp_path: Path, output: str) -> None:
    roots = [tmp_path / "python", tmp_path / "rust"]
    for root in roots:
        root.mkdir()
        (root / "pyproject.toml").write_text('[project]\nname = "example"\n')
        source = root / "src/example/core.py"
        source.parent.mkdir(parents=True)
        source.write_text("import httpx\nVALUE = []\n")

    def compare(*args: str) -> None:
        processes = [
            subprocess.run(command + list(args), cwd=root, text=True, capture_output=True)
            for root, command in zip(
                roots, [[sys.executable, "-m", "lint_it"], [str(BINARY)]], strict=True
            )
        ]
        left, right = processes
        assert left.returncode == right.returncode, right.stderr
        if "json" in args:
            assert json.loads(left.stdout) == json.loads(right.stdout)
        else:
            assert left.stdout == right.stdout
        assert left.stderr == right.stderr

    compare("rules")
    compare("rules", "--format", "markdown")
    compare("init", "--layout", "flat", "--kind", "library")
    compare("init", "--layout", "flat")
    for root in roots:
        with (root / "lint-it.toml").open("a") as manifest:
            manifest.write('baseline = "baseline.json"\n')
    compare("check", "--format", output, "--jobs", "1")
    compare("baseline", "--jobs", "1")
    assert (roots[0] / "baseline.json").read_bytes() == (roots[1] / "baseline.json").read_bytes()
    compare("check", "--format", output, "--jobs", "1")
    compare("check", "--format", output, "--no-baseline", "--jobs", "1")
    for root in roots:
        (root / "src/example/core.py").write_text("VALUE = 1\n")
    compare("check", "--format", output, "--jobs", "1")
    compare("baseline", "--prune", "--jobs", "1")
    assert (roots[0] / "baseline.json").read_bytes() == (roots[1] / "baseline.json").read_bytes()
    compare("check", "--format", output, "--jobs", "1")
