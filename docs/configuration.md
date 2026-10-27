# Configuration

lint-it reads `lint-it.toml` at the workspace root. Without one it uses the
defaults: every package is a `server` with the `domains` layout. Every section
is optional, and unknown keys are errors.

A manifest that cannot be loaded is reported as `LIT003` at `lint-it.toml:1`
and `lint-it check` exits with status 2. Entries that load but no longer match
the workspace (stale or overlapping overrides, exceeded budgets) are ordinary
`LIT003` findings.

## Workspace and packages

```toml
[workspace]
kind = "server"            # default kind for every package
layout = "domains"         # default layout for every package
override_budget = 0        # files that may use [[overrides]]
dependency_override_budget = 0
effectful_types = ["example.clock.Clock"]          # extends LIT207's catalog
clock_modules = ["example.integrations.clock"]     # may read wall time (LIT201)

[[packages]]
path = "packages/sdk"      # a directory with a pyproject.toml
kind = "client"
layout = "boundary"
```

Every directory with a `pyproject.toml` is a package, found automatically;
`[[packages]]` only changes its kind or layout. A file belongs to the deepest
package that contains it. Module names come from the package's `src/`
directory.

Kinds:

- `server`: an application. Its top-level modules are server modules.
- `client`: code shipped to consumers, such as an SDK. May not import server
  modules (LIT103).
- `library`: anything else.

## Layouts

A layout is an ordered list of globs, each mapped to a layer. The last matching
glob wins. Globs are matched against the path relative to the package root:
`*` matches within one directory, `**` matches any number of directories, and
`?` and `[...]` work as usual.

Built-in layouts: `domains`, `hexagonal`, `flat`, `boundary` (every source file
is a boundary) and `test-support` (every source file is test code). Run
`lint-it classify` to see which glob matched each file.

Every layout, custom ones included, ends with these patterns:

| Glob | Layer |
| --- | --- |
| `conftest.py`, `tests/**/*.py` | `test` |
| `scripts/**/*.py`, `examples/**/*.py` | `boundary` |
| `migrations/**/*.py` | `transaction` |
| `src/**/__init__.py` | `marker` |

Define your own layout, optionally on top of a built-in one; its globs come
after the base layout's, so they win:

```toml
[workspace]
layout = "orders"

[layouts.orders]
extends = "hexagonal"
layers = [
  { glob = "src/*/clock.py", layer = "adapter" },
  { glob = "src/*/ops.py", layer = "boundary" },
]
```

Without `extends`, only the listed globs and the common patterns apply. Built-in
layouts cannot be redefined.

## Policy

Each of these sections replaces the built-in entry for every layer it names and
leaves the other layers alone.

```toml
# Layers each layer may import. "*" removes the restriction.
[layer_dependencies]
shell = ["core", "port", "shell", "adapter"]
router = "*"

# Top-level packages each layer may not import (LIT102).
[forbidden_imports]
core = ["httpx", "requests", "sqlalchemy", "pydantic"]
router = []

# Naming conventions for LIT401 and LIT402.
[conventions]
predicate_prefixes = ["is_", "has_", "can_"]
outcome_suffixes = ["NotFound", "Denied"]
```

The defaults are in [`src/lint_it/policy.py`](../src/lint_it/policy.py).

## Overrides

A file that cannot move yet can be given a layer explicitly. Overrides need a
reason and an issue, must be scoped below a package area (no `src/**/*.py`), and
count against `override_budget`:

```toml
[workspace]
override_budget = 1

[[overrides]]
package = "packages/api"   # default "."
glob = "src/api/legacy.py"
layer = "shell"
reason = "Split into domains/orders after the billing migration"
issue = "API-123"
```

A known layer violation can be recorded as one exact edge while it is removed.
Dependency overrides count against `dependency_override_budget`:

```toml
[workspace]
dependency_override_budget = 1

[[dependency_overrides]]
importer = "src/example/domains/orders/core.py"
imported = "src/example/app/contracts.py"
reason = "Move the application-owned type into the orders domain"
issue = "EX-124"
```
