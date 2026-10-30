from __future__ import annotations

import json

import pytest
from conftest import Project

from lint_it import baseline
from lint_it.cli import main
from lint_it.loader import ManifestError

CORE = "src/example/domains/orders/core.py"
SERVICE = "src/example/domains/orders/service.py"
REPOSITORY = "src/example/domains/orders/persistence/repository.py"
TEST = "tests/test_orders.py"
BASELINE = '[workspace]\nbaseline = "lint-it-baseline.json"\n'


def run(project: Project, *args: str) -> int:
    return main([*args, "--root", str(project.root)])


def recorded(project: Project) -> dict[str, object]:
    return json.loads((project.root / "lint-it-baseline.json").read_text(encoding="utf-8"))


def test_ignore_by_layer_drops_only_that_rule(project: Project) -> None:
    project.manifest(
        """
        [[ignore]]
        rules = ["mocking"]
        layers = ["test"]
        reason = "Tests move off unittest.mock separately"
        """
    )
    project.write({TEST: "from unittest import mock\n", CORE: "import httpx\n"})
    result = project.findings()

    assert [item.code for item in result] == ["LIT102"]


def test_ignore_by_path_glob(project: Project) -> None:
    project.manifest(
        """
        [[ignore]]
        rules = ["LIT102"]
        paths = ["src/example/domains/legacy/**"]
        reason = "Legacy domain is being rewritten"
        """
    )
    project.write({"src/example/domains/legacy/core.py": "import httpx\n", CORE: "import httpx\n"})

    assert [item.filename for item in project.findings()] == [CORE]


def test_unused_and_invalid_ignores_are_manifest_findings(project: Project) -> None:
    project.manifest(
        """
        [[ignore]]
        rules = ["LIT102"]
        paths = ["src/example/gone/**"]
        reason = "Nothing left here"

        [[ignore]]
        rules = ["no-such-rule", "LIT003"]
        reason = "Typos"
        """
    )
    project.write({CORE: ""})

    assert [item.message for item in project.findings()] == [
        "LIT003 cannot be ignored",
        "ignore names unknown rule no-such-rule",
        "ignore suppresses nothing: LIT102 in src/example/gone/**",
    ]


def test_unused_ignores_are_not_reported_for_a_path_selection(project: Project) -> None:
    project.manifest('[[ignore]]\nrules = ["LIT102"]\nreason = "Later"\n')
    project.write({CORE: ""})

    assert project.findings(CORE) == []


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        ('[[ignore]]\nrules = []\nreason = "x"', "ignore.rules must name at least one rule"),
        ('[[ignore]]\nrules = ["LIT102"]', "ignore.reason must be a non-empty string"),
        (
            '[[ignore]]\nrules = ["LIT102"]\nlayers = ["web"]\nreason = "x"',
            "ignore.layers must be one of",
        ),
        ('[[ignore]]\nrules = ["LIT102"]\nwhy = "x"', "unknown ignore field: why"),
    ],
)
def test_invalid_ignores_name_the_problem(project: Project, manifest: str, message: str) -> None:
    project.manifest(manifest)
    with pytest.raises(ManifestError, match=message):
        project.load()


def test_baseline_records_findings_without_lines(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.manifest(BASELINE).write({CORE: "import httpx\nimport httpx as client\n"})

    assert run(project, "baseline") == 0
    assert recorded(project) == {
        "version": 1,
        "findings": {
            CORE: [{"code": "LIT102", "message": "core modules cannot import httpx", "count": 2}]
        },
    }
    assert capsys.readouterr().out == "wrote lint-it-baseline.json: 2 findings in 1 files (was 0)\n"


def test_check_reports_only_findings_beyond_the_baseline(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.manifest(BASELINE).write({CORE: "import httpx\n"})
    run(project, "baseline")
    project.write({CORE: "\n\nimport httpx\n", SERVICE: "import fastapi\n"})
    capsys.readouterr()

    assert run(project, "check") == 1
    assert capsys.readouterr().out.splitlines() == [
        f"{SERVICE}:1:1: LIT102 shell modules cannot import fastapi",
        "1 finding in 1 file (2 files in 1 package checked; 1 baselined)",
    ]
    assert run(project, "check", "--no-baseline") == 1
    assert "2 findings" in capsys.readouterr().out


def test_fixed_findings_make_the_baseline_stale_until_pruned(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.manifest(BASELINE).write({CORE: "import httpx\n", SERVICE: "import fastapi\n"})
    run(project, "baseline")
    project.write({CORE: "", "src/example/domains/orders/model.py": "import redis\n"})
    capsys.readouterr()

    assert run(project, "check") == 1
    assert capsys.readouterr().out.splitlines()[:2] == [
        "lint-it-baseline.json:1:1: LIT003 1 baseline entry no longer matches a finding; "
        "run `lint-it baseline --prune` to shrink the baseline",
        "src/example/domains/orders/model.py:1:1: LIT102 core modules cannot import redis",
    ]
    assert run(project, "baseline", "--prune") == 0
    assert list(baseline.parse((project.root / "lint-it-baseline.json").read_text()).counts) == [
        (SERVICE, "LIT102", "shell modules cannot import fastapi")
    ]


def test_baseline_needs_a_configured_path(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.write({CORE: ""})

    assert run(project, "baseline") == 2
    assert "set workspace.baseline" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[]", "baseline must be an object with version 1"),
        ('{"version": 1, "findings": []}', "keyed by file"),
        ('{"version": 1, "findings": {"a.py": [{"code": "LIT1"}]}}', "needs code, message"),
        ("{", "baseline is not valid JSON"),
    ],
)
def test_corrupt_baselines_are_manifest_errors(project: Project, text: str, message: str) -> None:
    project.manifest(BASELINE).write({"lint-it-baseline.json": text})
    with pytest.raises(ManifestError, match=message):
        project.load()


def test_report_ranks_rules_edges_targets_and_areas(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.manifest(BASELINE).write(
        {
            REPOSITORY: "VALUE = 1\n",
            SERVICE: "from example.domains.orders.persistence.repository import VALUE\n",
            CORE: "import httpx\n",
        }
    )
    run(project, "baseline")
    project.write(
        {
            "src/example/projections/summary/service.py": (
                "from example.domains.orders.persistence.repository import VALUE\n"
            )
        }
    )
    capsys.readouterr()

    assert run(project, "report", "--depth", "4", "--format", "json") == 0
    stats = json.loads(capsys.readouterr().out)

    assert (stats["findings"], stats["new"], stats["baselined"]) == (3, 1, 2)
    assert stats["rules"][0] == {
        "code": "LIT101",
        "name": "layer-dependency",
        "findings": 2,
        "new": 1,
        "files": 2,
    }
    assert stats["edges"] == [{"label": "shell -> adapter", "findings": 2}]
    assert stats["targets"][0] == {
        "label": "LIT101 example.domains.orders.persistence.repository",
        "findings": 2,
    }
    assert {"label": "src/example/domains/orders", "findings": 2} in stats["areas"]


def test_report_text_lists_each_section(
    project: Project, capsys: pytest.CaptureFixture[str]
) -> None:
    project.write({CORE: "import httpx\n"})

    assert run(project, "report") == 0
    output = capsys.readouterr().out
    assert output.startswith("1 finding: 1 new, 0 baselined (0 ignored)\n\nBy rule\n  LIT102")
    assert "Top targets\n       1  LIT102 httpx" in output
    assert "Top areas\n       1  src/example/domains" in output


def test_report_can_focus_on_one_rule(project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    project.write(
        {
            CORE: "import httpx\n",
            "src/example/domains/orders/model.py": "class Base(dict): ...\nclass Mid(Base): ...\n"
            "class Leaf(Mid): ...\n",
        }
    )

    assert run(project, "report", "--rule", "restricted-subclassing", "--format", "json") == 0
    stats = json.loads(capsys.readouterr().out)
    assert [item["code"] for item in stats["rules"]] == ["LIT403"]
    assert stats["targets"] == [{"label": "LIT403 example.domains.orders.model.Mid", "findings": 1}]
    assert run(project, "report", "--rule", "LIT999") == 2


def test_rendered_baseline_round_trips_one_entry_per_line() -> None:
    counts = {
        ("src/b.py", "LIT102", 'core modules cannot import "x"'): 2,
        ("src/a.py", "LIT101", "café"): 1,
        ("src/a.py", "LIT201", "gone"): 0,
    }
    text = baseline.render(counts)

    assert baseline.parse(text).counts == {key: count for key, count in counts.items() if count}
    assert text.splitlines()[4] == '      {"code": "LIT101", "message": "café", "count": 1}'
    assert baseline.parse(baseline.render({})).counts == {}
