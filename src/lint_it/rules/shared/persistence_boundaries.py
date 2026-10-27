from __future__ import annotations

from pathlib import PurePosixPath

from lint_it.core import normalized_filename


def _domain_module_parts(filename: str) -> tuple[str, ...] | None:
    parts = PurePosixPath(normalized_filename(filename)).parts
    try:
        domains_index = parts.index("domains")
    except ValueError:
        return None
    if len(parts) <= domains_index + 2:
        return None
    return parts[domains_index + 2 :]


def _is_persistence_module(filename: str) -> bool:
    module_parts = _domain_module_parts(filename)
    return module_parts is not None and "persistence" in module_parts[:-1]
