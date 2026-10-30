"""Bundle a verified release executable when installing from Git or an sdist."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import urllib.request
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

PLATFORMS = {
    ("Linux", "x86_64"): ("x86_64-unknown-linux-musl", "linux_x86_64"),
    ("Linux", "aarch64"): ("aarch64-unknown-linux-musl", "linux_aarch64"),
    ("Darwin", "x86_64"): ("x86_64-apple-darwin", "macosx_10_13_x86_64"),
    ("Darwin", "arm64"): ("aarch64-apple-darwin", "macosx_11_0_arm64"),
    ("Windows", "AMD64"): ("x86_64-pc-windows-msvc", "win_amd64"),
}


def native_platform() -> tuple[str, str]:
    override = os.environ.get("LINT_IT_NATIVE_TARGET")
    if override:
        for target, tag in PLATFORMS.values():
            if target == override:
                return target, tag
        raise RuntimeError(f"Unsupported LINT_IT_NATIVE_TARGET: {override}")
    key = (platform.system(), platform.machine())
    if key not in PLATFORMS:
        raise RuntimeError(f"lint-it does not yet ship a native executable for {key}")
    return PLATFORMS[key]


def bundle_binary(root: Path, version: str, target: str) -> Path:
    suffix = ".exe" if target.endswith("windows-msvc") else ""
    destination = root / "src" / "lint_it" / "_bin" / f"lint-it-rust{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    override = os.environ.get("LINT_IT_NATIVE_BINARY")
    if override:
        # Explicit local/CI builds can supply an executable built from this checkout.
        shutil.copyfile(override, destination)
    else:
        manifest = json.loads((root / "native-artifacts.json").read_text())
        if manifest["version"] != version:
            raise RuntimeError("Native artifact manifest does not match the Python package version")
        asset = f"lint-it-rust-{target}{suffix}"
        expected = manifest["sha256"][asset]
        url = f"https://github.com/denismaciel/lint-it/releases/download/v{version}/{asset}"
        request = urllib.request.Request(url, headers={"User-Agent": "lint-it-python-build"})
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError(f"SHA-256 mismatch for {asset}; refusing to package it")
        destination.write_bytes(data)
    destination.chmod(0o755)
    return destination


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        target, tag = native_platform()
        binary = bundle_binary(Path(self.root), self.metadata.version, target)
        build_data["pure_python"] = False
        build_data["tag"] = f"py3-none-{tag}"
        build_data["force_include"][str(binary)] = f"lint_it/_bin/{binary.name}"
