"""Whole-path glob matching: ``*``, ``?`` and ``[...]`` stay within one segment, ``**``
spans zero or more segments."""

from __future__ import annotations

import re
from functools import lru_cache


def _segment(part: str) -> str:
    pattern: list[str] = []
    index = 0
    while index < len(part):
        character = part[index]
        if character == "*":
            pattern.append("[^/]*")
        elif character == "?":
            pattern.append("[^/]")
        elif character == "[" and (end := part.find("]", index + 2)) != -1:
            body = part[index + 1 : end]
            negated = body.startswith("!")
            body = re.escape(body[1:] if negated else body).replace(r"\-", "-")
            pattern.append(f"[{'^' if negated else ''}{body}]")
            index = end
        else:
            pattern.append(re.escape(character))
        index += 1
    return "".join(pattern)


@lru_cache(maxsize=512)
def _compiled(glob: str) -> re.Pattern[str]:
    parts = glob.split("/")
    pattern: list[str] = []
    for position, part in enumerate(parts):
        last = position == len(parts) - 1
        if part == "**":
            pattern.append(r"(?:[^/]+/)*[^/]+" if last else r"(?:[^/]+/)*")
        else:
            pattern.append(_segment(part) + ("" if last else "/"))
    return re.compile("".join(pattern))


def matches_glob(path: str, glob: str) -> bool:
    """Whether the POSIX ``path`` matches ``glob`` in full."""
    return _compiled(glob).fullmatch(path) is not None
