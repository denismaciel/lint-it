"""Built-in architecture policy. A manifest replaces any entry it names."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class Layer(StrEnum):
    CORE = "core"
    PORT = "port"
    SHELL = "shell"
    ADAPTER = "adapter"
    ROUTER = "router"
    BOUNDARY = "boundary"
    TRANSACTION = "transaction"
    TEST = "test"
    MARKER = "marker"


INNER_LAYERS = frozenset({Layer.CORE, Layer.PORT})
EDGE_LAYERS = frozenset({Layer.BOUNDARY, Layer.ROUTER, Layer.TRANSACTION, Layer.TEST})

# Allowed import targets per layer; a missing layer may import anything.
# Package markers are never targets: their imports are followed instead.
LAYER_DEPENDENCIES: Mapping[Layer, frozenset[Layer]] = MappingProxyType(
    {
        Layer.CORE: frozenset({Layer.CORE, Layer.PORT}),
        Layer.PORT: frozenset({Layer.CORE, Layer.PORT}),
        Layer.SHELL: frozenset({Layer.CORE, Layer.PORT, Layer.SHELL}),
        Layer.ADAPTER: frozenset({Layer.CORE, Layer.PORT, Layer.ADAPTER}),
        Layer.ROUTER: frozenset({Layer.SHELL, Layer.BOUNDARY, Layer.ROUTER, Layer.TRANSACTION}),
    }
)

IO_PACKAGES = frozenset(
    {
        "aiohttp",
        "aiosqlite",
        "asyncpg",
        "boto3",
        "botocore",
        "httpx",
        "playwright",
        "psycopg",
        "psycopg2",
        "redis",
        "requests",
        "socket",
        "sqlite3",
        "subprocess",
    }
)
FRAMEWORK_PACKAGES = frozenset(
    {"fastapi", "starlette", "sqlalchemy", "pydantic", "pydantic_settings"}
)

# Top-level packages each layer may not import, directly or through re-exports.
FORBIDDEN_IMPORTS: Mapping[Layer, frozenset[str]] = MappingProxyType(
    {
        Layer.CORE: IO_PACKAGES | FRAMEWORK_PACKAGES,
        Layer.PORT: IO_PACKAGES | FRAMEWORK_PACKAGES,
        Layer.SHELL: FRAMEWORK_PACKAGES,
        Layer.ROUTER: frozenset({"sqlalchemy"}),
    }
)

PREDICATE_PREFIXES = (
    "allows_",
    "can_",
    "contains_",
    "has_",
    "is_",
    "matches_",
    "should_",
)
OUTCOME_SUFFIXES = (
    "AlreadyExists",
    "Conflict",
    "Denied",
    "Expired",
    "Forbidden",
    "NotFound",
    "Rejected",
    "Unauthorized",
    "Unavailable",
)


@dataclass(frozen=True)
class Policy:
    layer_dependencies: Mapping[Layer, frozenset[Layer]] = LAYER_DEPENDENCIES
    forbidden_imports: Mapping[Layer, frozenset[str]] = FORBIDDEN_IMPORTS
    predicate_prefixes: tuple[str, ...] = PREDICATE_PREFIXES
    outcome_suffixes: tuple[str, ...] = OUTCOME_SUFFIXES
    effectful_types: frozenset[str] = frozenset()
    clock_modules: frozenset[str] = frozenset()
