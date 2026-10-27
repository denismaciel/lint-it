"""Validators shared by the TOML manifests; each raises ValueError naming the field."""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath


def relative_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must be a relative path inside the workspace")
    return path.as_posix()


def non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def enum_value[E: StrEnum](kind: type[E], value: object, field: str) -> E:
    text = non_empty_string(value, field)
    try:
        return kind(text)
    except ValueError:
        choices = ", ".join(item.value for item in kind)
        raise ValueError(f"{field} must be one of: {choices}; got {text!r}") from None


def non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{field} must be an array of non-empty strings")
    return value


def reject_unknown_keys(value: dict[str, object], allowed: frozenset[str], field: str) -> None:
    unknown = sorted(value.keys() - allowed)
    if unknown:
        raise ValueError(f"unknown {field} field: {', '.join(unknown)}")
