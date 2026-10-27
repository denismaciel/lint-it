from pathlib import Path

import pytest

from lint_it.filesystem import check_paths, workspace_architecture
from lint_it.rules.pal009 import DomainSqlAlchemyImportRule
from lint_it.rules.pal010 import DomainPersistenceImportRule
from lint_it.rules.pal017 import LayerDependencyRule


def _project(tmp_path: Path, manifest: str = "") -> tuple[Path, Path, Path]:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\nversion = "1"\n')
    (tmp_path / "lint-it.toml").write_text(manifest)
    core = tmp_path / "src/example/domains/orders/core.py"
    boundary = tmp_path / "src/example/app/api.py"
    model = tmp_path / "src/example/domains/orders/model.py"
    for path in (core, boundary, model):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    return core, boundary, model


def test_pal017_rejects_outward_dependency_from_functional_core(tmp_path: Path) -> None:
    core, _, _ = _project(tmp_path)
    core.write_text("from example.app.api import create_app\n")

    findings = check_paths([core], [LayerDependencyRule()])

    assert [finding.code for finding in findings] == ["PAL017"]
    assert "functional-core cannot import boundary" in findings[0].message


def test_pal017_allows_inward_dependency(tmp_path: Path) -> None:
    core, _, _ = _project(tmp_path)
    core.write_text("from example.domains.orders.model import Order\n")

    assert check_paths([core], [LayerDependencyRule()]) == []


def test_pal017_honors_audited_dependency_override(tmp_path: Path) -> None:
    manifest = """
[workspace]
dependency_override_budget = 1

[[dependency_overrides]]
package = "."
importer = "src/example/domains/orders/core.py"
imported = "src/example/app/api.py"
reason = "Move the contract into the domain"
issue = "PERSONAL-1"
""".strip()
    core, _, _ = _project(tmp_path, manifest)
    core.write_text("from example.app.api import create_app\n")

    assert check_paths([core], [LayerDependencyRule()]) == []


@pytest.mark.parametrize(
    "statement",
    [
        "import example.domains.orders.model",
        "from example.domains.orders.model import Order",
        "from example.domains.orders import model",
        "from example import Order",
    ],
)
@pytest.mark.parametrize(
    "initializer", ["src/example/__init__.py", "src/example/domains/__init__.py"]
)
def test_pal017_follows_parent_initializers(
    tmp_path: Path, statement: str, initializer: str
) -> None:
    core, _, _ = _project(tmp_path)
    core.write_text(statement)
    (tmp_path / "src/example/__init__.py").write_text(
        "from example.domains.orders.model import Order\n"
    )
    with (tmp_path / initializer).open("a") as file:
        file.write("from example.app.api import create_app\n")
    findings = check_paths([core], [LayerDependencyRule()])
    assert len(findings) == 1
    assert "app/api.py" in findings[0].message
    assert findings[0].line == 1


def test_pal017_follows_initializer_helpers_and_cycles(tmp_path: Path) -> None:
    core, _, model = _project(tmp_path)
    core.write_text("from example.domains.orders.model import Order")
    (tmp_path / "src/example/__init__.py").write_text("from example.domains.orders import model")
    model.write_text("import example\nfrom example.app.api import create_app")
    findings = check_paths([core], [LayerDependencyRule()])
    assert len(findings) == 1
    assert "app/api.py" in findings[0].message


def test_pal017_does_not_execute_initializer_function_bodies(tmp_path: Path) -> None:
    core, _, _ = _project(tmp_path)
    core.write_text("from example.domains.orders.model import Order")
    (tmp_path / "src/example/__init__.py").write_text(
        "def start():\n    from example.app.api import create_app\n"
    )
    assert check_paths([core], [LayerDependencyRule()]) == []


def test_workspace_snapshots_keep_their_own_parsed_sources(tmp_path: Path) -> None:
    core, _, _ = _project(tmp_path)
    core.write_text("from example.app.api import create_app\n")
    original = workspace_architecture(tmp_path)
    core.write_text("from example.domains.orders.model import Order\n")
    refreshed = workspace_architecture(tmp_path)

    assert [item.code for item in check_paths([core], [LayerDependencyRule()], original)] == [
        "PAL017"
    ]
    assert check_paths([core], [LayerDependencyRule()], refreshed) == []


def test_persistence_imports_are_allowed_in_test_helpers_but_not_domain_code(
    tmp_path: Path,
) -> None:
    core, _, _ = _project(tmp_path)
    helper = tmp_path / "tests/domains/orders/fixtures.py"
    helper.parent.mkdir(parents=True)
    source = "import sqlalchemy\nfrom example.domains.orders.persistence import repository\n"
    core.write_text(source)
    helper.write_text(source)
    rules = [DomainSqlAlchemyImportRule(), DomainPersistenceImportRule()]

    assert check_paths([helper], rules) == []
    assert [item.code for item in check_paths([core], rules)] == ["PAL009", "PAL010"]
