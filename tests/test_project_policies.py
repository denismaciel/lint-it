from pathlib import Path

import pytest

from lint_it.architecture import Layer, load_manifest
from lint_it.filesystem import check_paths, workspace_architecture
from lint_it.package_boundaries import load_policy
from lint_it.rules.registry import ALL_RULES


def test_project_profile_preserves_roles_and_does_not_disable_rules(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="orders"\nversion="1"\n')
    (tmp_path / "lint-it.toml").write_text("""
[workspace]
default_profile = "orders-layout"
[profiles.orders-layout]
role = "application"
layers = [{glob="src/*/decisions.py", layer="functional-core"}]
""")
    source = tmp_path / "src/orders/decisions.py"
    source.parent.mkdir(parents=True)
    source.write_text('import os\ndef decide(): return os.getenv("SECRET")\n')
    architecture = workspace_architecture(tmp_path)
    classification = architecture.classify(source)
    assert classification is not None and classification.layer == Layer.FUNCTIONAL_CORE
    assert "PAL004" in {item.code for item in check_paths([source], ALL_RULES, architecture)}
    assert architecture.classify(source.with_name("unknown.py")) is None


@pytest.mark.parametrize(
    "profile",
    [
        {"role": "application", "layers": []},
        {"role": "application", "layers": [{"glob": "../core.py", "layer": "functional-core"}]},
        {"role": "application", "layers": [{"glob": "src/**/*.py", "layer": "ignored"}]},
        {
            "role": "application",
            "layers": [{"glob": "src/**/*.py", "layer": "boundary"}],
            "disable": ["PAL004"],
        },
    ],
)
def test_invalid_project_profiles_fail_closed(tmp_path: Path, profile: dict) -> None:
    with pytest.raises(ValueError):
        load_manifest(tmp_path, {"profiles": {"custom": profile}}, frozenset({tmp_path}))


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"packages": {"example": {"root": "../src", "distribution": "example"}}},
        {
            "packages": {
                "example": {
                    "root": "src/example",
                    "distribution": "example",
                    "allowed": ["unknown"],
                }
            }
        },
        {
            "packages": {
                "example": {
                    "root": "src/example",
                    "distribution": "example",
                    "forbidden": ["vendor.*"],
                }
            }
        },
    ],
)
def test_invalid_runtime_policy_fails_closed(raw: dict) -> None:
    with pytest.raises(ValueError):
        load_policy(raw)


def test_contract_import_policy_uses_discovered_application_names(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="new-server"\nversion="1"\n')
    server = tmp_path / "src/new_server/app/config.py"
    server.parent.mkdir(parents=True)
    server.write_text("VALUE = 1")
    sdk = tmp_path / "packages/client"
    sdk.mkdir(parents=True)
    (sdk / "pyproject.toml").write_text('[project]\nname="client"\nversion="1"\n')
    source = sdk / "src/client/__init__.py"
    source.parent.mkdir(parents=True)
    source.write_text("from new_server.app.config import VALUE")
    (tmp_path / "lint-it.toml").write_text('[[packages]]\npath="packages/client"\nprofile="sdk"\n')
    architecture = workspace_architecture(tmp_path)
    assert "PAL008" in {item.code for item in check_paths([source], ALL_RULES, architecture)}
