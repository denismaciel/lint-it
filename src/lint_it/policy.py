"""Built-in architecture policy. A manifest replaces any entry it names."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
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
LAYER_DEPENDENCIES: Mapping[str, frozenset[str]] = MappingProxyType(
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
FORBIDDEN_IMPORTS: Mapping[str, frozenset[str]] = MappingProxyType(
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
# Bases a class may extend (LIT403). A trailing ".*" allows every name in a module.
ALLOWED_BASES = frozenset(
    {
        "builtins.*",
        "typing.Generic",
        "typing.NamedTuple",
        "typing.Protocol",
        "typing.TypedDict",
        "typing_extensions.Generic",
        "typing_extensions.NamedTuple",
        "typing_extensions.Protocol",
        "typing_extensions.TypedDict",
        "enum.Enum",
        "enum.Flag",
        "enum.IntEnum",
        "enum.IntFlag",
        "enum.StrEnum",
        "pydantic.BaseModel",
        "pydantic.RootModel",
        "pydantic_settings.BaseSettings",
        "sqlalchemy.TypeDecorator",
        "sqlalchemy.types.TypeDecorator",
        "sqlalchemy.ext.declarative.declarative_base",
        "sqlalchemy.orm.DeclarativeBase",
        "sqlalchemy.orm.DeclarativeBaseNoMeta",
        "sqlalchemy.orm.MappedAsDataclass",
        "sqlalchemy.orm.declarative_base",
    }
)


@dataclass(frozen=True)
class CustomLayer:
    """A named layer that follows a built-in layer's rules, with its own policy."""

    name: str
    base: Layer
    deterministic: bool = False


@dataclass(frozen=True)
class AllowedDependency:
    """Workspace modules that importers in ``layers`` (every layer when empty) may use."""

    modules: tuple[str, ...]
    layers: frozenset[str]
    reason: str


def matches_name(name: str, patterns: Iterable[str]) -> bool:
    """Whether ``name`` is a pattern, or lies under a ``module.*`` pattern."""
    return any(
        name == pattern or (pattern.endswith(".*") and name.startswith(pattern.removesuffix("*")))
        for pattern in patterns
    )


@dataclass(frozen=True)
class Policy:
    """Per-layer tables are keyed by layer name, built-in or custom."""

    layer_dependencies: Mapping[str, frozenset[str]] = LAYER_DEPENDENCIES
    forbidden_imports: Mapping[str, frozenset[str]] = FORBIDDEN_IMPORTS
    forbidden_calls: Mapping[str, frozenset[str]] = MappingProxyType({})
    custom_layers: Mapping[str, CustomLayer] = MappingProxyType({})
    allowed_dependencies: tuple[AllowedDependency, ...] = ()
    predicate_prefixes: tuple[str, ...] = PREDICATE_PREFIXES
    outcome_suffixes: tuple[str, ...] = OUTCOME_SUFFIXES
    allowed_bases: frozenset[str] = ALLOWED_BASES
    effectful_types: frozenset[str] = frozenset()
    clock_modules: frozenset[str] = frozenset()

    def base(self, layer: str) -> Layer:
        custom = self.custom_layers.get(layer)
        return Layer(layer) if custom is None else custom.base

    def is_a(self, layer: str, targets: frozenset[str]) -> bool:
        """Whether ``layer`` is one of ``targets``, directly or through its base layer."""
        return layer in targets or self.base(layer) in targets

    def allows_dependency(self, importer: str, module: str) -> bool:
        return any(
            (not item.layers or self.is_a(importer, item.layers))
            and matches_name(module, item.modules)
            for item in self.allowed_dependencies
        )
