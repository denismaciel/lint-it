# lint-it

Strict architecture rules for Python applications: functional cores, imperative
shells, explicit dependencies, and enforced package boundaries. Requires Python
3.14 or later; no runtime dependencies.

The standalone CLI is the authoritative gate. The Flake8 adapter is for editor
feedback; installing this package also registers its `PAL` extension with Flake8.

## Installation

Install the tagged release directly from GitHub:

```bash
uv tool install 'git+https://github.com/denismaciel/lint-it.git@v0.9.1'
```

Or add it to a project's development dependencies:

```bash
uv add --dev 'lint-it @ git+https://github.com/denismaciel/lint-it.git@v0.9.1'
uv run lint-it --workspace .
```

Commit the project's lockfile. For an immutable source pin, use the release's full
commit SHA instead of its tag. GitHub Releases also provides wheel and source
archives. This release is distributed on GitHub, not PyPI.

## Quick start

At your Python project root, create `lint-it.toml`:

```toml
[workspace]
default_profile = "application"
override_budget = 0
dependency_override_budget = 0
```

Place domain decisions in `src/<package>/domains/<domain>/core.py`, immutable
values in `model.py`, capabilities in `ports.py`, and orchestration in `service.py`.
Then run `lint-it --workspace .`. Findings produce exit status 1; a successful
check returns 0. Every discovered Python file must have a classified location.

For incremental adoption, give the new package its own manifest and invoke
`lint-it --workspace path/to/new-package`. That checks only that workspace.
Dependencies outside it are not included in the workspace import graph; enforce
any old/new import restriction separately. Keep legacy lint commands scoped away
from the new package, and restrict their Flake8 rule selection if sharing an
environment with this plugin.

## Rules

- `PAL001`: core defaults are immutable literals; boundary defaults remain supported
- `PAL002`: no `unittest.mock` or pytest `monkeypatch` in tests
- `PAL003`: domain imports follow router -> service -> ports/model
- `PAL004`: environment access only at configured system boundaries
- `PAL005`: commit and rollback only at transaction boundaries
- `PAL006`: routers do not construct repositories, clients, or engines
- `PAL007`: domain modules do not import FastAPI
- `PAL008`: contracts and SDK packages do not import server packages
- `PAL009`: domain SQLAlchemy imports live only under `persistence/`
- `PAL010`: business modules and routers cannot import persistence adapters
- `PAL011`: domain cores receive observed time, IDs, and random values explicitly
- `PAL012`: boundary validation frameworks stay outside domain cores
- `PAL013`: policy inputs and outcomes use explicit types instead of booleans
- `PAL014`: filesystem, network, logging, and other known I/O stays in the shell
- `PAL015`: expected domain outcomes use result types instead of exceptions
- `PAL016`: every Python file follows a canonical layout or has an audited override
- `PAL017`: functional cores and ports do not import outward layers, including workspace packages, explicit re-exports, and package initializer imports
- `PAL018`: runtime `BaseSettings` follow the canonical app boundary, name, prefix, and loader
- `PAL019`: no writes to caller-owned arguments, direct aliases, or borrowed elements
- `PAL020`: no mutable module-state reads, global/nonlocal writes, or known ambient context access
- `PAL021`: domain dataclasses are frozen and collection fields expose read-only interfaces
- `PAL022`: awaited operations and task/thread scheduling stay outside the decision core
- `PAL023`: core parameters cannot receive known effectful capability types
- `PAL024`: domain services cannot import boundary schemas or validation frameworks

```bash
lint-it src packages
lint-it src packages --json
lint-it --workspace .
```

`--workspace` reads `lint-it.toml`, discovers every `pyproject.toml`, and
fails if a project or Python file is unclassified. Rule selection and
suppressions are intentionally unsupported: every applicable rule runs on every
check.

The manifest applies the standard conventions by default:

```toml
[workspace]
default_profile = "application"
override_budget = 0

[[packages]]
path = "packages/core"
profile = "infrastructure"
```

The linter discovers packages automatically. A package entry is needed only to
select a non-default profile: `application`, `contracts`, `domain-library`,
`hexagonal-application`, `infrastructure`, `sdk`, `test-support`, or `tooling`.
Applications use
`src/<package>/app`, `domains/<domain>`, `integrations`, and `shared`; tests use
`tests/`, migrations use `migrations/`, and operational scripts use `scripts/`.
Runnable examples under `examples/` are boundaries. Infrastructure and hexagonal
applications may expose a boundary entrypoint at `src/<package>/development.py`.
Canonical domain filenames include `boundary.py`, `model.py`, `core.py`,
`policy.py`, `event.py`, `ports.py`, and `service.py`, with persistence adapters
under `persistence/`. Domains may contain nested feature slices using the same
filenames. Read models use `projections/<projection>/` with `model.py`,
`ports.py`, `service.py`, and persistence adapters.

Runtime settings use `src/<package>/app/config.py`, a `Settings(BaseSettings)`
class with a non-empty application prefix, and a module-level `load_settings()`.
The process composition root calls the loader once and injects settings into
application construction. Domain-specific configuration models that do not
read process settings remain with their owning domain.

The `hexagonal-application` profile preserves a coherent existing
`domain`/`application`/`adapters`/`web` package without file-by-file overrides.
It enforces the same inward dependency direction and boundary policies.

An unavoidable legacy path can receive a narrow classification override:

```toml
[[overrides]]
package = "packages/example"
glob = "src/example/legacy.py"
layer = "imperative-shell"
reason = "Pending domain layout migration"
issue = "PERSONAL-123"
```

Overrides require a reason and issue, cannot cover an entire source tree, fail
when stale or overlapping, and never disable rules. The manifest defaults the
workspace override budget to zero; accepting legacy exceptions requires an
explicit file budget. CLI output reports how many files used defaults or
overrides.

An existing inward dependency violation must be recorded as an exact,
auditable edge while it is being removed:

```toml
[workspace]
dependency_override_budget = 1

[[dependency_overrides]]
package = "packages/example"
importer = "src/example/domains/orders/core.py"
imported = "src/example/app/contracts.py"
reason = "Move the application-owned type into the orders domain"
issue = "PERSONAL-124"
```

Dependency overrides require existing exact Python paths and have an independent
ratcheting budget. They apply only within one package. PAL017 also checks cross-package dependencies
inside the workspace; third-party implementations remain outside its import graph.
Importing a submodule also checks every available parent `__init__.py`, including
unrelated imports and transitive helper imports executed during initialization.
Cycles terminate and repeated targets produce one finding per importer. Initializer
function bodies are deferred; module/class control-flow imports are conservatively
included regardless of branch conditions. Dynamic imports and effects hidden in
function calls are not resolved.

PAL011 through PAL015 use the resolved layers. Predicates may still return
`bool`, invariant failures may still raise built-in exceptions, and
infrastructure remains valid in the imperative shell.

Each rule has its own implementation file, named after its stable code:

```text
src/lint_it/
├── core.py                     # Rule protocol, findings, shared check runner
├── architecture.py             # Pure workspace classification and policy
├── filesystem.py               # File/config discovery and snapshot construction
├── imports.py                  # Shared import analysis
├── cli.py                      # Authoritative workspace gate
├── plugin.py                   # Thin Flake8 adapter
└── rules/
    ├── registry.py             # Ordered ALL_RULES and RULES_BY_CODE
    ├── pal001.py               # One implementation per rule
    ├── …
    ├── pal022.py
    └── shared/                 # Reused domain-core and persistence helpers
```

Rule-specific constants and helpers live with their rule. Only analysis reused
by multiple rules lives in the shared helper modules. Rule modules do not import
one another, and `rules/__init__.py` performs no registration.

To add a rule, create `rules/palNNN.py`, register its instance in
`rules/registry.py`, and add positive and negative cases under `tests/`.
Keep existing codes, messages, and finding order stable. Both the CLI and
Flake8 adapter consume the same registry.


## Purity contract and limits

Core calculations consume values and return decisions. Shells read clocks and
repositories, generate IDs, execute decisions, and emit logs. Injecting an
I/O-capable object into a calculation does not make its methods pure.

The CLI loads configuration, project inventory, and parsed source into an
explicit `Architecture` snapshot. Rule execution and classification use that
snapshot without filesystem discovery or global caches. The editor adapter
constructs its snapshot at the boundary too. Pure consumers should use
`core.check_tree`; filesystem consumers use `filesystem.check_paths`.
Each snapshot builds read-only indexes for source files, package ownership,
layers, and module identities. Rules reuse those indexes; replacing or reloading
a snapshot rebuilds them from its own sources and configuration.

PAL011 and PAL014 resolve imported aliases, typed parameters, simple assignment
aliases, and common instance factories. Known effects are rejected when used in
calls, callbacks, decorators, defaults, and module/class initialization. Names
shadowed by parameters or local assignments are not treated as library calls.
Branch joins with an unknown target do not invent a definite violation.

PAL019 tracks direct argument aliases, item/attribute writes, known built-in
container mutators, loop elements, and shallow container copies. Local lists and
dictionaries, local rebinding, and immutable scalar increments are allowed.
A shallow copy owns its container but still borrows its elements. Receiver
ownership (`self`), arbitrary custom methods, interprocedural aliasing, and
mutation through unknown callbacks are not proven by this analysis.

PAL021 checks dataclass declarations and annotated mutable collection types.
`Mapping` and `Sequence` expose read-only APIs; they do not deep-freeze objects or
prevent another owner from changing the underlying data. Callers must provide
stable inputs. This gate is not a proof of recursive immutability or general
Python purity. PAL013 remains a separate domain-policy convention, not a purity
claim.

The rules do not ban loops, local accumulation, ordinary exceptions for invalid
values, or pure strategy callables. Unknown third-party methods and dynamic
Python behavior remain unproven rather than being blanket-rejected.


### Effectful capability signatures

PAL023 checks function and method parameters (including constructors and variadic
parameters) in the functional core. Its exact-type catalog includes SQL sessions
and connections, HTTP clients, open-file interfaces, and filesystem clients.
Project capabilities are registered explicitly in `lint-it.toml`:

```toml
[workspace]
effectful_types = [
    "example.domains.orders.ports.OrderRepository",
    "example.clock.Clock",
]
```

These entries extend the built-in catalog. They are qualified import identities,
not patterns or name suffixes. Register public re-export identities separately.
Import aliases, direct assignment aliases, relative imports within a workspace,
forward parameter annotations, unions, and nested annotations are checked.
`Annotated` metadata and `Literal` values are excluded.

Pass a customer snapshot instead of a repository, or an observed `datetime`
instead of a clock. Return decisions for the shell to persist or execute. Shell
and port signatures remain unrestricted by PAL023; pure callback protocols and
`pathlib.Path` values remain valid. PAL014 checks actual filesystem operations.

This is a declared-dependency check: missing annotations, `Any`, unknown types,
unregistered subclasses/re-exports, and capabilities concealed in arbitrary
objects are not proven safe. Generic type-alias expansion and whole-program
inference are outside this rule. It does not import application modules or mutate
the source snapshot while analyzing annotations.


### Wall-clock policy

PAL011 forbids native wall-clock reads in production shells as well as cores,
including imported aliases and callable references. Shells use a project-owned clock interface. Composition code can supply a clock
method to services accepting a datetime-producing callback. Core functions receive
observed datetime values. Register project clock types as effectful capabilities
for PAL023.

Only explicitly registered implementation modules may call `datetime.now`,
`datetime.today`, `datetime.utcnow`, `date.today`, `time.time`, or `time.time_ns`:

```toml
[workspace]
clock_modules = ["example.integrations.clock"]
```

Registration never exempts a functional-core module. Tests may read native time
for fixtures and clock contract tests. Monotonic and performance timers remain
allowed in shells; core nondeterminism checks still reject them.

Clock implementations belong to the consuming project; this package provides no
clock implementation. Prefer aware instants and an injectable fixed clock for
tests. The rule does not enforce one read per operation or prove arbitrary
datetime values timezone-aware. Calendar-date and timezone policy remain explicit
domain choices.

## Project-owned conventions (0.9)

`lint-it` is the strict gate: every applicable rule runs, with no baseline,
rule exclusions, or suppressions. PAL024 additionally rejects domain service
imports of boundary schemas and validation frameworks, following aliases,
re-exports and package initializer execution.

Projects with established layouts may define a named profile in their manifest:

```toml
[workspace]
default_profile = "orders-layout"

[profiles.orders-layout]
role = "application"
layers = [
  { glob = "src/*/domains/**/core.py", layer = "functional-core" },
  { glob = "src/*/domains/**/service.py", layer = "imperative-shell" },
  { glob = "src/*/domains/**/ports.py", layer = "port" },
]
```

The role retains package semantics (including SDK/server isolation). The ordered
layer list replaces the built-in role layout; last match wins, followed by common
conventions for tests, scripts, migrations and package markers. Unmatched files
fail PAL016. Profiles are reviewed architecture policy, not rule exceptions;
keep narrow conventions and existing override budgets. Built-in profiles cannot
be redefined. Clock/capability registrations and profiles remain in the app repo.

### Runtime dependency isolation

`lint-it-packages --workspace . --config runtime-packages.toml` checks
package import direction (PKG001), production imports of test helpers (PKG002),
and installed distributions against each package's uv.lock runtime dependency
closure, including extras but excluding dev dependencies (PKG003). Install all
workspace packages before running it. The CLI requires a lockfile.

```toml
retired = ["old_api"]
[packages.orders]
root = "src/orders"
distribution = "orders"
allowed = ["orders"]
forbidden = ["playwright"]
```

All source roots, allowed edges and forbidden/retired modules are project data.
Static, relative, deferred, type-only and literal dynamic imports participate in
package boundaries. Type-only imports are excluded only from installed runtime
dependency checks.

### Advisory migration policies

`lint-it-advisory --config lint-advisory.toml src packages` preserves the
older strict-default and SQLAlchemy/SQLite storage isolation audit (PLC001–006).
Its explicit policy contains boundary filenames, storage scopes, composition
paths, model identities and module/path aliases; see `tests/fixtures/lint-advisory.toml`
for the complete schema. It is separate from the mandatory PAL gate because
strict defaults reject immutable defaults that PAL001 permits. It exits nonzero
on findings and cannot add a baseline. Projects decide where to run this audit.

The shared package owns implementations and regression tests; applications own
manifests and their gate commands.


## Development

```bash
uv sync --locked
uv run pytest
uv run ruff check .
uv run ty check src
uv run lint-it --workspace .
uv build
```

Add regression tests with each rule change. Keep codes and finding order stable.
The standalone CLI applies every applicable rule without baselines or suppression.
Rule additions or stricter detection can affect consumers even in a minor release;
review upgrades explicitly and keep consumers pinned.

## Releasing

Update the version and changelog, run the checks above, and build both distributions.
Tag the tested commit as `v<version>` and publish a GitHub Release containing the
wheel, source archive, and SHA256 checksums. The tag version must match
`project.version`. Never move a published tag or replace a published artifact.

## License

MIT. See [LICENSE](LICENSE).
