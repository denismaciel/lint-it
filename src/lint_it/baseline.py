"""The baseline file: known findings keyed by file, rule and message, never by line,
so unrelated edits do not invalidate it."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

VERSION = 1

# (filename, code, message)
Key = tuple[str, str, str]


@dataclass(frozen=True)
class Baseline:
    counts: Mapping[Key, int] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def size(self) -> int:
        return sum(self.counts.values())


EMPTY = Baseline()


def parse(text: str) -> Baseline:
    """Raises ValueError for anything but a baseline this version wrote."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"baseline is not valid JSON: {error}") from None
    if not isinstance(data, dict) or data.get("version") != VERSION:
        raise ValueError(f"baseline must be an object with version {VERSION}")
    files = data.get("findings")
    if not isinstance(files, dict):
        raise ValueError("baseline findings must be an object keyed by file")
    counts: dict[Key, int] = {}
    for filename, entries in files.items():
        if not isinstance(entries, list):
            raise ValueError(f"baseline entries for {filename} must be an array")
        for entry in entries:
            if not (
                isinstance(entry, dict)
                and isinstance(entry.get("code"), str)
                and isinstance(entry.get("message"), str)
                and isinstance(entry.get("count", 1), int)
                and entry.get("count", 1) > 0
            ):
                raise ValueError(f"baseline entry for {filename} needs code, message and count")
            key = (filename, entry["code"], entry["message"])
            counts[key] = counts.get(key, 0) + entry.get("count", 1)
    return Baseline(MappingProxyType(counts))


def render(counts: Mapping[Key, int]) -> str:
    files: dict[str, list[dict[str, object]]] = {}
    for (filename, code, message), count in sorted(counts.items()):
        if count > 0:
            files.setdefault(filename, []).append(
                {"code": code, "message": message, "count": count}
            )
    return json.dumps({"version": VERSION, "findings": files}, indent=2) + "\n"
