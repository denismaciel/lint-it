"""Launch the Rust executable bundled in the installed Python package."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


def _binary_path() -> Path:
    name = "lint-it-rust.exe" if os.name == "nt" else "lint-it-rust"
    return Path(__file__).parent / "_bin" / name


def main(argv: Sequence[str] | None = None) -> int:
    """Forward CLI arguments and standard streams to the bundled executable."""
    binary = _binary_path()
    if not binary.is_file():
        print(
            f"lint-it: bundled executable missing: {binary}. "
            "Reinstall lint-it from the same pinned Git tag with your Python package manager.",
            file=sys.stderr,
        )
        return 2

    command = [str(binary), *(sys.argv[1:] if argv is None else argv)]
    try:
        if argv is None and os.name != "nt":
            os.execv(str(binary), command)
        return subprocess.run(command, check=False).returncode
    except OSError as error:
        print(f"lint-it: cannot launch bundled executable {binary}: {error}", file=sys.stderr)
        return 2
