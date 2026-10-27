import ast
from pathlib import Path

import pytest

from lint_it.architecture import Architecture, Layer, LayerPattern, Package, PackageRole
from lint_it.core import check_tree
from lint_it.rules.pal011 import HiddenNondeterminismRule


@pytest.mark.parametrize(
    "source",
    [
        "from datetime import datetime as D\nnow = D.now()",
        "import datetime as dt\nnow = dt.datetime.utcnow()",
        "from datetime import date\nnow = date.today()",
        "from datetime import datetime\nnow = datetime.today()",
        "import time as t\nnow = t.time_ns()",
        "from time import time as read\nnow = read()",
        "from datetime import datetime\nread = datetime.now",
    ],
)
def test_shell_requires_clock(source: str) -> None:
    result = check_tree(
        ast.parse(source), "src/example/app/service.py", (HiddenNondeterminismRule(),)
    )
    assert len(result) == 1
    assert "shared Clock" in result[0].message


@pytest.mark.parametrize(
    "source",
    [
        "import time\nstart = time.monotonic()",
        "import time\nstart = time.perf_counter_ns()",
        "from example.integrations.clock import SYSTEM_CLOCK\nnow = SYSTEM_CLOCK.now()",
        "class Clock:\n    def now(self): pass\nnow = Clock().now()",
    ],
)
def test_shell_allows_monotonic_and_clock_reads(source: str) -> None:
    assert (
        check_tree(ast.parse(source), "src/example/app/service.py", (HiddenNondeterminismRule(),))
        == []
    )


@pytest.mark.parametrize("layer, allowed", [(Layer.ADAPTER, True), (Layer.FUNCTIONAL_CORE, False)])
def test_clock_registration_does_not_exempt_core(layer: Layer, allowed: bool) -> None:
    root = Path("/workspace")
    architecture = Architecture(
        root=root,
        packages=(
            Package(root, PackageRole.INFRASTRUCTURE, (LayerPattern("src/**/*.py", layer),)),
        ),
        clock_modules=frozenset({"example.adapters.clock"}),
    )
    tree = ast.parse("from datetime import datetime\nnow = datetime.now()")
    result = check_tree(
        tree,
        str(root / "src/example/adapters/clock.py"),
        (HiddenNondeterminismRule(),),
        architecture,
    )
    assert (result == []) is allowed
    assert check_tree(
        tree,
        str(root / "src/example/adapters/other.py"),
        (HiddenNondeterminismRule(),),
        architecture,
    )


def test_clock_named_file_is_not_automatically_exempt() -> None:
    tree = ast.parse("from time import time\nnow = time()")
    assert check_tree(tree, "src/example/clock.py", (HiddenNondeterminismRule(),))


def test_test_fixtures_can_observe_real_time() -> None:
    assert (
        check_tree(
            ast.parse("from time import time\nnow = time()"),
            "tests/test_clock.py",
            (HiddenNondeterminismRule(),),
        )
        == []
    )
