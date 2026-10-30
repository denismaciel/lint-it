"""The Python entry point forwards execution to the packaged native binary."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lint_it import _native


def test_binary_location(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_native, "__file__", "/package with spaces/lint_it/_native.py")
    for platform, executable in [("posix", "lint-it-rust"), ("nt", "lint-it-rust.exe")]:
        monkeypatch.setattr(_native, "os", SimpleNamespace(name=platform))
        assert _native._binary_path() == Path("/package with spaces/lint_it/_bin") / executable


@pytest.fixture
def binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "package with spaces" / "_bin" / "lint-it-rust"
    path.parent.mkdir(parents=True)
    path.touch()
    monkeypatch.setattr(_native, "_binary_path", lambda: path)
    return path


@pytest.mark.parametrize("status", [0, 1, 2, 17, -15])
def test_explicit_arguments_preserve_status_and_streams(
    binary: Path, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    run = Mock(return_value=subprocess.CompletedProcess([], status))
    monkeypatch.setattr(_native.subprocess, "run", run)
    arguments = ["check", "--root", "project with spaces", "--format", "json"]
    assert _native.main(arguments) == status
    run.assert_called_once_with([str(binary), *arguments], check=False)


def test_posix_console_replaces_process(binary: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class ReplacedProcess(Exception):
        pass

    execute = Mock(side_effect=ReplacedProcess)
    run = Mock()
    monkeypatch.setattr(_native, "os", SimpleNamespace(name="posix", execv=execute))
    monkeypatch.setattr(_native.sys, "argv", ["lint-it", "check", "path with spaces"])
    monkeypatch.setattr(_native.subprocess, "run", run)
    with pytest.raises(ReplacedProcess):
        _native.main()
    execute.assert_called_once_with(str(binary), [str(binary), "check", "path with spaces"])
    run.assert_not_called()


def test_windows_console_uses_subprocess(binary: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock(return_value=subprocess.CompletedProcess([], 7))
    monkeypatch.setattr(_native, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(_native.sys, "argv", ["lint-it", "rules"])
    monkeypatch.setattr(_native.subprocess, "run", run)
    assert _native.main() == 7
    run.assert_called_once_with([str(binary), "rules"], check=False)


def test_missing_binary_is_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing"
    monkeypatch.setattr(_native, "_binary_path", lambda: missing)
    run = Mock()
    monkeypatch.setattr(_native.subprocess, "run", run)
    assert _native.main([]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "bundled executable missing" in output.err
    assert str(missing) in output.err
    assert "Reinstall lint-it" in output.err
    run.assert_not_called()


def test_launch_failure(
    binary: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(_native.subprocess, "run", Mock(side_effect=PermissionError("denied")))
    assert _native.main([]) == 2
    assert "cannot launch bundled executable" in capsys.readouterr().err
