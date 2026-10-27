from __future__ import annotations

from pathlib import PurePosixPath

from lint_it.architecture import Architecture, Layer, has_layer
from lint_it.core import normalized_filename

CORE_MODULES = frozenset({"core.py", "model.py", "policy.py", "ports.py"})

DECISION_MODULES = frozenset({"core.py", "policy.py"})


def _is_domain_module(
    filename: str, architecture: Architecture | None, names: frozenset[str]
) -> bool:
    governed_layers = (
        (Layer.FUNCTIONAL_CORE,)
        if names == DECISION_MODULES
        else (Layer.FUNCTIONAL_CORE, Layer.PORT)
    )
    classified = has_layer(filename, architecture, *governed_layers)
    if classified is not None:
        return classified
    normalized = normalized_filename(filename)
    path = PurePosixPath(normalized)
    return "domains" in path.parts and path.name in names


def _root_module(module: str) -> str:
    return module.split(".", maxsplit=1)[0]
