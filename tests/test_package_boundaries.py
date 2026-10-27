import tomllib
from pathlib import Path

from lint_it.package_boundaries import (
    check,
    dependency_violation,
    load_policy,
    runtime_distributions,
    violations,
)

POLICY = load_policy(
    tomllib.loads((Path(__file__).parent / "fixtures/runtime-packages.toml").read_text())
)
PACKAGE_ROOTS = {name: package.root for name, package in POLICY.packages.items()}


def test_late_type_only_and_dynamic_imports_are_checked():
    source = """
from typing import TYPE_CHECKING
import importlib as loader
if TYPE_CHECKING:
    from playwright.async_api import Page
def request():
    from example_scraping.integrations import transport
    return loader.import_module('example_runner.app.catalog')
"""
    findings = violations(
        source, "example", "example.shared.registry", initializer=False, policy=POLICY
    )
    assert {line for line, _ in findings} == {5, 7, 8}


def test_allowed_dependency_direction_and_relative_imports():
    assert not violations(
        """from example.domains.listing import model
from example_scraping.integrations import transport""",
        "example_runner",
        "example_runner.job",
        initializer=False,
        policy=POLICY,
    )
    assert not violations(
        "from . import model", "example", "example.domains.listing", initializer=True, policy=POLICY
    )
    assert violations(
        "from example_runner import catalog",
        "example_scraping",
        "example_scraping.cli",
        initializer=False,
        policy=POLICY,
    )
    assert violations(
        "import numpy", "example", "example.shared.helper", initializer=False, policy=POLICY
    )
    assert violations(
        "from example.domains.listing import model",
        "sample_contracts",
        "sample_contracts.listings",
        initializer=False,
        policy=POLICY,
    )


def test_helpers_and_initializers_cannot_hide_transitive_imports(tmp_path: Path):
    for relative in PACKAGE_ROOTS.values():
        (tmp_path / relative).mkdir(parents=True)
    shared = tmp_path / PACKAGE_ROOTS["example"]
    (shared / "__init__.py").write_text("from example_runner import catalog")
    (shared / "helper.py").write_text("def f():\n    import xgboost")
    (shared / "helper_test.py").write_text("import xgboost")
    findings = check(tmp_path, policy=POLICY)
    assert any("__init__.py:1" in finding for finding in findings)
    assert any("helper.py:2" in finding for finding in findings)
    assert not any("helper_test.py" in finding for finding in findings)


def test_production_cannot_import_exempt_test_helpers():
    findings = violations(
        "from example_runner.internal_app_test import make_runner_app",
        "example_runner",
        "example_runner.app.internal_app",
        initializer=False,
        policy=POLICY,
    )
    assert any(("PKG002" in message for _, message in findings))


def test_new_worker_libraries_are_rejected_without_a_hardcoded_name():
    providers = {
        "future_browser": {"browser-tool"},
        "vendor.browser": {"browser-tool"},
        "vendor": {"vendor-core"},
    }
    assert dependency_violation("future_browser.Client", {"httpx"}, providers, policy=POLICY)
    assert (
        dependency_violation("future_browser.Client", {"browser-tool"}, providers, policy=POLICY)
        is None
    )
    assert dependency_violation("vendor.browser.Client", {"vendor-core"}, providers, policy=POLICY)
    assert dependency_violation("datetime.datetime", set(), providers, policy=POLICY) is None


def test_runtime_graph_includes_selected_extras_but_excludes_dev_dependencies():
    lock = {
        "package": [
            {
                "name": "api",
                "dependencies": [{"name": "transport", "extra": ["crypto"]}],
                "dev-dependencies": {"dev": [{"name": "browser-tool"}]},
            },
            {
                "name": "transport",
                "dependencies": [{"name": "core"}],
                "optional-dependencies": {
                    "crypto": [{"name": "crypto-core"}],
                    "browser": [{"name": "browser-tool"}],
                },
            },
        ]
    }
    assert runtime_distributions(lock, "api") == {"api", "transport", "core", "crypto-core"}


def test_retired_public_api_cannot_be_reintroduced():
    for owner in PACKAGE_ROOTS:
        findings = violations(
            "from example_api.app.wiring import create_app",
            owner,
            f"{owner}.helper",
            initializer=False,
            policy=POLICY,
        )
        assert any(("PKG001" in message for _, message in findings))
