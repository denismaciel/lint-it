"""Built-in file layouts. Within a layout the last matching glob wins. A conventional
module such as ``core.py`` may grow into a package of the same name, whose files
take its layer. Every layout
follows its own globs with the conventional patterns and ends with the package
markers; a custom layout's globs come after the conventions, so they can
reclassify tests, scripts or migrations, but never package markers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from lint_it.policy import Layer


@dataclass(frozen=True)
class LayerPattern:
    glob: str
    layer: str


def _patterns(*entries: tuple[str, Layer]) -> tuple[LayerPattern, ...]:
    return tuple(LayerPattern(glob, layer) for glob, layer in entries)


CONVENTIONS = _patterns(
    ("conftest.py", Layer.TEST),
    ("tests/**/*.py", Layer.TEST),
    ("scripts/**/*.py", Layer.BOUNDARY),
    ("examples/**/*.py", Layer.BOUNDARY),
    ("migrations/**/*.py", Layer.TRANSACTION),
)
MARKERS = _patterns(("src/**/__init__.py", Layer.MARKER))

_DOMAIN_SLICES = _patterns(
    ("src/*/domains/**/boundary.py", Layer.BOUNDARY),
    ("src/*/domains/**/model.py", Layer.CORE),
    ("src/*/domains/**/core.py", Layer.CORE),
    ("src/*/domains/**/policy.py", Layer.CORE),
    ("src/*/domains/**/event.py", Layer.CORE),
    ("src/*/domains/**/ports.py", Layer.PORT),
    ("src/*/domains/**/service.py", Layer.SHELL),
    ("src/*/domains/*/**/boundary/**/*.py", Layer.BOUNDARY),
    ("src/*/domains/*/**/model/**/*.py", Layer.CORE),
    ("src/*/domains/*/**/core/**/*.py", Layer.CORE),
    ("src/*/domains/*/**/policy/**/*.py", Layer.CORE),
    ("src/*/domains/*/**/event/**/*.py", Layer.CORE),
    ("src/*/domains/*/**/ports/**/*.py", Layer.PORT),
    ("src/*/domains/*/**/service/**/*.py", Layer.SHELL),
    ("src/*/domains/**/persistence/**/*.py", Layer.ADAPTER),
    ("src/*/projections/**/model.py", Layer.CORE),
    ("src/*/projections/**/ports.py", Layer.PORT),
    ("src/*/projections/**/service.py", Layer.SHELL),
    ("src/*/projections/*/**/model/**/*.py", Layer.CORE),
    ("src/*/projections/*/**/ports/**/*.py", Layer.PORT),
    ("src/*/projections/*/**/service/**/*.py", Layer.SHELL),
    ("src/*/projections/**/persistence/**/*.py", Layer.ADAPTER),
    ("src/*/shared/model.py", Layer.CORE),
    ("src/*/shared/core.py", Layer.CORE),
    ("src/*/shared/policy.py", Layer.CORE),
    ("src/*/shared/ports.py", Layer.PORT),
    ("src/*/shared/model/**/*.py", Layer.CORE),
    ("src/*/shared/core/**/*.py", Layer.CORE),
    ("src/*/shared/policy/**/*.py", Layer.CORE),
    ("src/*/shared/ports/**/*.py", Layer.PORT),
    ("src/*/shared/persistence/**/*.py", Layer.ADAPTER),
)

DOMAINS = (
    *_DOMAIN_SLICES,
    *_patterns(
        ("src/*/__main__.py", Layer.BOUNDARY),
        ("src/*/app/**/*.py", Layer.BOUNDARY),
        ("src/*/app/**/router.py", Layer.ROUTER),
        ("src/*/app/**/*_router.py", Layer.ROUTER),
        ("src/*/app/router/**/*.py", Layer.ROUTER),
        ("src/*/app/routers/**/*.py", Layer.ROUTER),
        ("src/*/app/dependencies.py", Layer.TRANSACTION),
        ("src/*/db/**/*.py", Layer.ADAPTER),
        ("src/*/db/unit_of_work.py", Layer.TRANSACTION),
        ("src/*/db/unit_of_work/**/*.py", Layer.TRANSACTION),
        ("src/*/integrations/**/*.py", Layer.ADAPTER),
        ("src/*/integrations/unit_of_work/**/*.py", Layer.TRANSACTION),
    ),
)

HEXAGONAL = _patterns(
    ("src/*/*.py", Layer.CORE),
    ("src/*/domain/**/*.py", Layer.CORE),
    ("src/*/domain/**/ports.py", Layer.PORT),
    ("src/*/application/**/*.py", Layer.SHELL),
    ("src/*/application/**/ports.py", Layer.PORT),
    ("src/*/application/**/errors.py", Layer.CORE),
    ("src/*/application/**/*_errors.py", Layer.CORE),
    ("src/*/adapters/**/*.py", Layer.ADAPTER),
    ("src/*/adapters/**/database.py", Layer.TRANSACTION),
    ("src/*/web/**/*.py", Layer.BOUNDARY),
    ("src/*/app/**/*.py", Layer.BOUNDARY),
    ("src/*/config.py", Layer.BOUNDARY),
    ("src/*/development.py", Layer.BOUNDARY),
    ("src/*/main.py", Layer.BOUNDARY),
    ("src/*/__main__.py", Layer.BOUNDARY),
    ("src/*/worker.py", Layer.BOUNDARY),
)

FLAT = _patterns(
    ("src/**/*.py", Layer.SHELL),
    ("src/*/model.py", Layer.CORE),
    ("src/*/core.py", Layer.CORE),
    ("src/*/policy.py", Layer.CORE),
    ("src/*/ports.py", Layer.PORT),
    ("src/*/model/**/*.py", Layer.CORE),
    ("src/*/core/**/*.py", Layer.CORE),
    ("src/*/policy/**/*.py", Layer.CORE),
    ("src/*/ports/**/*.py", Layer.PORT),
    ("src/*/adapters/**/*.py", Layer.ADAPTER),
    ("src/*/cli.py", Layer.BOUNDARY),
    ("src/*/cli/**/*.py", Layer.BOUNDARY),
    ("src/*/__main__.py", Layer.BOUNDARY),
    ("src/*/development.py", Layer.BOUNDARY),
)

BUILT_IN: Mapping[str, tuple[LayerPattern, ...]] = MappingProxyType(
    {
        "domains": DOMAINS,
        "hexagonal": HEXAGONAL,
        "flat": FLAT,
        "boundary": _patterns(("src/**/*.py", Layer.BOUNDARY)),
        "test-support": _patterns(("src/**/*.py", Layer.TEST)),
    }
)
