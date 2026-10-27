from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from lint_it.architecture import Architecture, Layer, has_layer
from lint_it.core import Finding, finding
from lint_it.rules.shared.effects import is_nondeterministic
from lint_it.rules.shared.functional_core import CORE_MODULES, _is_domain_module
from lint_it.rules.shared.symbols import resolved_symbols

WALL_CLOCK_APIS = frozenset(
    {
        "datetime.datetime.now",
        "datetime.datetime.today",
        "datetime.datetime.utcnow",
        "datetime.date.today",
        "time.time",
        "time.time_ns",
    }
)


class HiddenNondeterminismRule:
    code = "PAL011"

    def check(
        self, tree: ast.Module, filename: str, architecture: Architecture | None = None
    ) -> Iterable[Finding]:
        core = _is_domain_module(filename, architecture, CORE_MODULES)
        if not core:
            if has_layer(filename, architecture, Layer.TEST_SHELL):
                return []
            if architecture is None and (
                "tests" in Path(filename).parts or filename.endswith("_test.py")
            ):
                return []
            if architecture is not None:
                path = Path(filename)
                path = path if path.is_absolute() else architecture.root / path
                package = architecture.package_for(path)
                if package is not None and path.is_relative_to(package.root / "src"):
                    parts = path.relative_to(package.root / "src").with_suffix("").parts
                    module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
                    if module in architecture.clock_modules:
                        return []
        return [
            finding(
                self,
                filename,
                node,
                (
                    f"{', '.join(sorted(names))} hides nondeterminism; "
                    "pass the observed time, ID, or random value into the core"
                    if core
                    else f"{', '.join(sorted(names))} reads wall time directly; "
                    "use the shared Clock interface in the shell"
                ),
            )
            for node, names in resolved_symbols(tree).items()
            if isinstance(node, (ast.Name, ast.Attribute))
            and isinstance(node.ctx, ast.Load)
            and names
            and all(
                is_nondeterministic(name) if core else name in WALL_CLOCK_APIS for name in names
            )
        ]
