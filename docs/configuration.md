# Configuration

lint-it reads `lint-it.toml` at the workspace root. Without one it uses the
defaults: every package is a `server` with the `domains` layout. Every section
is optional, and unknown keys are errors.

A manifest that cannot be loaded is reported as `LIT003` at `lint-it.toml:1`
and `lint-it check` exits with status 2. Entries that load but no longer match
the workspace (stale or overlapping overrides, exceeded budgets, unused ignores,
allowances that match no module, stale baseline entries) are ordinary `LIT003`
findings.

## Workspace and packages

```toml
[workspace]
kind = "server"            # default kind for every package
layout = "domains"         # default layout for every package
override_budget = 0        # files that may use [[overrides]]
dependency_override_budget = 0
effectful_types = ["example.clock.Clock"]          # extends LIT207's catalog
clock_modules = ["example.integrations.clock"]     # may read wall time (LIT201)
baseline = "lint-it-baseline.json"                 # known findings; see Adoption

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

In `domains` and `flat`, a conventional module can grow into a package of the
same name without a manifest change: `domains/orders/core/pricing.py` is core
like `domains/orders/core.py`, and `ports/`, `service/`, `model/`, `policy/`,
`event/`, `boundary/` and, in `flat`, `cli/` follow their module's layer. A file
takes its package's layer whatever its own name, so `core/ports.py` is core;
only `persistence/` reclassifies files below it. In `domains` and `projections`
the package must sit inside a domain, so a domain named `policy` or `event` is
not affected.

Every layout includes these conventional patterns, after the built-in layout's
own globs:

| Glob | Layer |
| --- | --- |
| `conftest.py`, `tests/**/*.py` | `test` |
| `scripts/**/*.py`, `examples/**/*.py` | `boundary` |
| `migrations/**/*.py` | `transaction` |

and ends with `src/**/__init__.py` as `marker`, which no layout glob can
change (use an override).

Define your own layout, optionally on top of a built-in one. Its globs come
after the base layout's and the conventional patterns, so they win, and can
reclassify tests, scripts or migrations:

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

Without `extends`, only the conventional patterns and the listed globs apply.
Built-in layouts cannot be redefined.

## Custom layers

A custom layer follows a built-in layer's rules but has its own name, so it can
have its own dependency, import and call policy. Layouts, overrides and every
per-layer table accept it:

```toml
# Temporal workflow code: dispatches activities like a router, replays deterministically.
[layers.workflow]
base = "router"
deterministic = true       # LIT201 bans every nondeterministic source, as in core

[layouts.app]
extends = "domains"
layers = [{ glob = "src/*/workflows/**/workflow.py", layer = "workflow" }]
```

Until the manifest names it, a custom layer takes its base layer's entry in
`[layer_dependencies]`, `[forbidden_imports]` and `[forbidden_calls]`, and
`[extend_forbidden_imports]` applies to it as to any layer. When imported, it
counts as its base layer: a layer that may import routers may import
workflows. `lint-it classify` shows it as `workflow (a router)`.

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

# Packages added to the lists above (or to the defaults) instead of replacing
# them. "*" adds to every layer.
[extend_forbidden_imports]
"*" = ["legacy_app"]

# Functions each layer may not call (LIT306), by resolved name; a trailing ".*"
# bans a whole module. Empty by default.
[forbidden_calls]
workflow = ["time.sleep", "builtins.open"]

# Naming conventions for LIT401 and LIT402, and the bases classes may extend
# (LIT403). allowed_bases replaces the default list; extend_allowed_bases adds
# to it. A trailing ".*" allows every name in a module.
[conventions]
predicate_prefixes = ["is_", "has_", "can_"]
outcome_suffixes = ["NotFound", "Denied"]
extend_allowed_bases = ["ast.NodeVisitor", "fastapi.HTTPException"]
```

The defaults are in [`src/lint_it/policy.py`](../src/lint_it/policy.py).

Workspace modules that a layer may always import, whatever their own layer,
are declared with a reason. Omit `layers` to allow every importer; a trailing
`.*` covers a module tree. An entry matching no workspace module is a `LIT003`
finding:

```toml
[[allowed_dependencies]]
layers = ["shell", "router"]
modules = ["example.database.repositories", "example.database.errors"]
reason = "The repository facade is the persistence port until domains own ports"
```

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

## Adoption

Two tools let an existing codebase adopt lint-it before it is clean.

`[[ignore]]` switches rules off where you have decided not to apply them yet.
Each entry names rules by code or name, optionally limited to path globs
(relative to the workspace root) and layers, and needs a reason. `LIT001` and
`LIT003` cannot be ignored, and an entry that suppresses nothing in a full
check is a `LIT003` finding:

```toml
[[ignore]]
rules = ["mocking"]
layers = ["test"]
reason = "The suite moves from unittest.mock to fakes separately"

[[ignore]]
rules = ["LIT201"]
paths = ["src/example/legacy/**"]
reason = "Legacy billing is replaced in EX-200"
```

A baseline records the findings you already have. Set `workspace.baseline`,
then run `lint-it baseline` to write it: a JSON file keyed by file, rule and
message (not line), one entry per line, safe to commit. `lint-it check` then
reports only findings beyond it, and a `LIT003` finding when entries no longer
match, until `lint-it baseline --prune` drops them. `--prune` never adds
entries, so the baseline only shrinks; `lint-it check --no-baseline` shows
everything. `lint-it report` ranks the findings, new and baselined, by rule,
layer edge, target and directory; `--rule LIT101` focuses it on one rule.
