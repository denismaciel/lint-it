"""Verify native artifact selection and integrity without network access."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import hatch_build


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LINT_IT_NATIVE_TARGET", raising=False)
    monkeypatch.delenv("LINT_IT_NATIVE_BINARY", raising=False)


@pytest.mark.parametrize(
    ("system", "machine", "target", "tag"),
    [
        ("Linux", "x86_64", "x86_64-unknown-linux-musl", "linux_x86_64"),
        ("Linux", "aarch64", "aarch64-unknown-linux-musl", "linux_aarch64"),
        ("Darwin", "x86_64", "x86_64-apple-darwin", "macosx_10_13_x86_64"),
        ("Darwin", "arm64", "aarch64-apple-darwin", "macosx_11_0_arm64"),
        ("Windows", "AMD64", "x86_64-pc-windows-msvc", "win_amd64"),
    ],
)
def test_native_platform(
    monkeypatch: pytest.MonkeyPatch, system: str, machine: str, target: str, tag: str
) -> None:
    monkeypatch.setattr(hatch_build.platform, "system", lambda: system)
    monkeypatch.setattr(hatch_build.platform, "machine", lambda: machine)
    assert hatch_build.native_platform() == (target, tag)


def test_unsupported_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hatch_build.platform, "system", lambda: "Linux")
    monkeypatch.setattr(hatch_build.platform, "machine", lambda: "riscv64")
    with pytest.raises(RuntimeError, match=r"does not yet ship.*riscv64"):
        hatch_build.native_platform()


def test_explicit_target_overrides_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hatch_build.platform, "system", lambda: "Linux")
    monkeypatch.setattr(hatch_build.platform, "machine", lambda: "riscv64")
    monkeypatch.setenv("LINT_IT_NATIVE_TARGET", "aarch64-apple-darwin")
    assert hatch_build.native_platform() == ("aarch64-apple-darwin", "macosx_11_0_arm64")


def test_unsupported_explicit_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINT_IT_NATIVE_TARGET", "unknown-target")
    with pytest.raises(RuntimeError, match="Unsupported LINT_IT_NATIVE_TARGET: unknown-target"):
        hatch_build.native_platform()


@pytest.mark.parametrize(
    ("target", "filename"),
    [
        ("x86_64-unknown-linux-musl", "lint-it-rust"),
        ("x86_64-pc-windows-msvc", "lint-it-rust.exe"),
    ],
)
def test_local_binary_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str, filename: str
) -> None:
    source = tmp_path / "compiled binary"
    source.write_bytes(b"local executable")
    source.chmod(0o600)
    monkeypatch.setenv("LINT_IT_NATIVE_BINARY", str(source))
    network = Mock(side_effect=AssertionError("local builds must not download"))
    monkeypatch.setattr(hatch_build.urllib.request, "urlopen", network)
    result = hatch_build.bundle_binary(tmp_path, "1.2.3", target)
    assert result == tmp_path / "src" / "lint_it" / "_bin" / filename
    assert result.read_bytes() == source.read_bytes()
    assert result.stat().st_mode & 0o777 == 0o755
    network.assert_not_called()


def write_manifest(root: Path, data: bytes, version: str = "1.2.3") -> None:
    (root / "native-artifacts.json").write_text(
        json.dumps(
            {
                "version": version,
                "sha256": {
                    "lint-it-rust-x86_64-unknown-linux-musl": hashlib.sha256(data).hexdigest()
                },
            }
        )
    )


def test_release_download_verifies_checksum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"verified release executable"
    write_manifest(tmp_path, data)
    download = Mock(return_value=io.BytesIO(data))
    monkeypatch.setattr(hatch_build.urllib.request, "urlopen", download)
    result = hatch_build.bundle_binary(tmp_path, "1.2.3", "x86_64-unknown-linux-musl")
    assert result.read_bytes() == data
    assert result.stat().st_mode & 0o777 == 0o755
    download.assert_called_once()
    request = download.call_args.args[0]
    assert request.full_url == (
        "https://github.com/denismaciel/lint-it/releases/download/v1.2.3/"
        "lint-it-rust-x86_64-unknown-linux-musl"
    )
    assert download.call_args.kwargs == {"timeout": 120}


def test_bad_download_preserves_existing_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_manifest(tmp_path, b"expected binary")
    existing = tmp_path / "src" / "lint_it" / "_bin" / "lint-it-rust"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"previous binary")
    monkeypatch.setattr(
        hatch_build.urllib.request, "urlopen", Mock(return_value=io.BytesIO(b"wrong binary"))
    )
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        hatch_build.bundle_binary(tmp_path, "1.2.3", "x86_64-unknown-linux-musl")
    assert existing.read_bytes() == b"previous binary"


def test_manifest_version_must_match_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_manifest(tmp_path, b"binary", version="1.2.2")
    network = Mock(side_effect=AssertionError("reject stale manifest before downloading"))
    monkeypatch.setattr(hatch_build.urllib.request, "urlopen", network)
    with pytest.raises(RuntimeError, match="manifest does not match"):
        hatch_build.bundle_binary(tmp_path, "1.2.3", "x86_64-unknown-linux-musl")
    network.assert_not_called()
