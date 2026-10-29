from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import Project

from lint_it import engine, parallel, reporting
from lint_it.cli import main
from lint_it.rules.registry import ALL_RULES

REPOSITORY = Path(__file__).resolve().parents[1]
CORE = "src/example/domains/orders/core.py"


def run(project: Project, *args: str) -> int:
    return main([*args, "--root", str(project.root)])


def test_clean_workspace_exits_zero(project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    project.write({CORE: "VALUE = 1\n"})

    assert run(project, "check") == 0
    assert capsys.readouterr().out == "No findings (1 file in 1 package checked)\n"


def test_findings_exit_one_with_relative_paths(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.write({CORE: "import httpx\n", "src/example/orders.py": ""})

    assert run(project, "check") == 1
    assert capsys.readouterr().out.splitlines() == [
        "src/example/domains/orders/core.py:1:1: LIT102 core modules cannot import httpx",
        "src/example/orders.py:1:1: LIT002 file matches no layer in its package layout "
        "(domains); move it, extend the layout, or add an override",
        "2 findings in 2 files (2 files in 1 package checked)",
    ]


def test_paths_limit_reported_findings(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.write({CORE: "import httpx\n", "src/example/orders.py": ""})

    assert run(project, "check", str(project.root / "src/example/domains")) == 1
    assert "orders.py" not in capsys.readouterr().out


def test_json_output_is_findings_and_summary(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.write({CORE: "import httpx\n"})

    assert run(project, "check", "--format", "json") == 1
    assert json.loads(capsys.readouterr().out) == {
        "findings": [
            {
                "filename": CORE,
                "line": 1,
                "column": 0,
                "code": "LIT102",
                "message": "core modules cannot import httpx",
                "target": "httpx",
            }
        ],
        "summary": {"findings": 1, "packages": 1, "files": 1},
    }


def test_github_output_escapes_annotations(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.write({CORE: "import httpx, redis\n"})

    assert run(project, "check", "--format", "github") == 1
    assert capsys.readouterr().out == (
        f"::error file={CORE},line=1,col=1,title=LIT102::core modules cannot import httpx, redis\n"
    )
    assert reporting._escape("a:b,c%\n", field="property") == "a%3Ab%2Cc%25%0A"


def test_syntax_errors_are_findings(project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    project.write({CORE: "def broken(:\n", "src/example/domains/orders/model.py": "VALUE = 1\n"})

    assert run(project, "check") == 1
    assert (
        capsys.readouterr()
        .out.splitlines()[0]
        .startswith(f"{CORE}:1:12: LIT001 file cannot be parsed:")
    )


@pytest.mark.parametrize("output", ["text", "json"])
def test_invalid_manifest_exits_two(
    project: Project, capsys: pytest.CaptureFixture[str], output: str
) -> None:
    project.manifest('[workspace]\nlayout = "web"\n')

    assert run(project, "check", "--format", output) == 2
    captured = capsys.readouterr()
    if output == "json":
        [problem] = json.loads(captured.out)["findings"]
        assert (problem["filename"], problem["code"]) == ("lint-it.toml", "LIT003")
    else:
        assert captured.err.startswith("lint-it.toml:1:1: LIT003 workspace.layout must be one of")


def test_stale_manifest_entries_are_findings(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.manifest(
        '[[overrides]]\nglob = "src/example/gone.py"\nlayer = "shell"\nreason = "x"\nissue = "y"\n'
    )

    assert run(project, "check") == 1
    assert "lint-it.toml:1:1: LIT003 stale layout override" in capsys.readouterr().out


def test_paths_outside_the_workspace_are_usage_errors(
    project: Project, tmp_path_factory: pytest.TempPathFactory
) -> None:
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    assert run(project, "check", str(elsewhere)) == 2
    assert run(project, "check", str(project.root / "missing")) == 2


def test_classify_explains_layers(project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    project.package("packages/sdk", "sdk").manifest(
        "[workspace]\noverride_budget = 1\n"
        '[[overrides]]\nglob = "src/example/legacy.py"\nlayer = "shell"\n'
        'reason = "Old"\nissue = "EX-1"\n'
    )
    project.write(
        {
            CORE: "",
            "src/example/legacy.py": "",
            "src/example/orders.py": "",
            "packages/sdk/src/sdk/client.py": "",
            "tools/run.py": "",
        }
    )

    assert run(project, "classify", str(project.root / "src"), str(project.root / "tools")) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"{CORE}: core (domains layout, src/*/domains/**/core.py)",
        "src/example/legacy.py: shell (override, src/example/legacy.py)",
        "src/example/orders.py: unclassified (domains layout)",
        "tools/run.py: unclassified (domains layout)",
    ]


def test_classify_reports_files_outside_packages(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.package("packages/sdk", "sdk").write({"loose/run.py": ""})
    (project.root / "pyproject.toml").unlink()

    assert run(project, "classify", str(project.root / "loose/run.py")) == 0
    assert capsys.readouterr().out == "loose/run.py: outside every package\n"


def test_init_writes_a_starter_manifest(project: Project) -> None:
    assert run(project, "init", "--layout", "flat", "--kind", "library") == 0
    manifest = (project.root / "lint-it.toml").read_text()

    assert 'kind = "library"\nlayout = "flat"\n' in manifest
    assert project.findings() == []
    assert run(project, "init") == 2


def test_explain_accepts_codes_and_names(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", "lit101"]) == 0
    assert capsys.readouterr().out.startswith("LIT101 layer-dependency\n\nA module imports")
    assert main(["explain", "mocking"]) == 0
    assert main(["explain", "LIT999"]) == 2


def test_every_rule_is_documented() -> None:
    codes = [rule.code for rule in ALL_RULES]

    assert codes == sorted(codes)
    assert len(set(codes)) == len(codes)
    assert all(rule.name and type(rule).__doc__ for rule in ALL_RULES)


def test_rule_reference_is_up_to_date() -> None:
    reference = (REPOSITORY / "docs/rules.md").read_text()
    assert reference == reporting.rule_reference(ALL_RULES), (
        "regenerate with: uv run lint-it rules --format markdown > docs/rules.md"
    )


def test_module_entry_point_runs_the_cli(project: Project) -> None:
    project.write({CORE: "import httpx\n"})
    process = subprocess.run(
        [sys.executable, "-m", "lint_it", "check", "--format", "json"],
        cwd=project.root / "src",
        capture_output=True,
        text=True,
        check=False,
    )

    assert process.returncode == 1, process.stderr
    assert [item["code"] for item in json.loads(process.stdout)["findings"]] == ["LIT102"]


def test_lint_it_passes_its_own_rules() -> None:
    assert main(["check", "--root", str(REPOSITORY)]) == 0


def test_parallel_workers_report_the_serial_findings(project: Project) -> None:
    project.write(
        {f"src/example/domains/orders{index}/core.py": "import httpx\n" for index in range(8)}
    )
    workspace = project.load()

    serial = engine.check(workspace, ALL_RULES)
    forked = engine.check(workspace, ALL_RULES, checker=parallel.checker(3, files_per_job=1))

    assert forked == serial
    assert len(serial) == 8


def test_jobs_option_checks_in_process(project: Project) -> None:
    project.write({CORE: "import httpx\n"})

    assert run(project, "check", "--jobs", "1") == 1
