from pathlib import Path

from lint_it.filesystem import check_paths
from lint_it.rules.registry import ALL_RULES


def test_rules_can_be_selected_by_code(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text("import os\n\ndef value(enabled: bool = True):\n    return os.getenv('X')\n")
    selected = tuple(rule for rule in ALL_RULES if rule.code == "PAL004")

    findings = check_paths((source,), selected)

    assert [finding.code for finding in findings] == ["PAL004"]
