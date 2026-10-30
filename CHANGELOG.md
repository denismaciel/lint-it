# Changelog

## 0.18.0

### Layouts

- **Fakes next to production code.** In `domains`, `fakes.py`, `fake.py` and
  `fakes/` anywhere under the package are `test`, so an in-memory repository
  can sit beside the port it implements.

### Rules

- **LIT101 keeps test code out of production.** Layers without a dependency
  table, such as boundary and transaction, may still import anything except
  test code; only test modules may import test modules. A composition root
  can no longer wire a fake into production.

### Upgrading

- Boundary or transaction modules that import a `test` or `test-support`
  package get `LIT101` findings. Record deliberate edges with
  `[[dependency_overrides]]` or `lint-it baseline`.

## 0.17.0

### Layouts

- **`domains` classifies a top-level `db/` package.** `src/<pkg>/db/**` is an
  adapter, so tables and repositories can live outside the domains, and
  `db/unit_of_work.py` or `db/unit_of_work/` is a transaction. Files there
  were previously unclassified.

## 0.16.0

### Rules

- **LIT104 `cross-domain-import`.** A module under `<package>/domains/<name>/`
  may import another domain only when `[domains]` declares the dependency,
  and then only that domain's core and shell modules; its ports,
  `persistence/` and boundaries stay private. Imports are followed through
  package initializers and re-exports, and `[[dependency_overrides]]` exempts
  one edge.

### Manifest

- **`[domains]`** maps each domain to the domains it may import. The graph is
  validated on load: every named domain needs its own entry, and
  self-dependencies and cycles are manifest errors that report the cycle. A
  declared domain without a `domains/<name>/` package is a `LIT003` finding.

### Upgrading

- Workspaces whose domains already import each other get `LIT104` findings
  until they declare `[domains]`, or record them with `lint-it baseline`.

## 0.15.0

### Layouts

- A conventional module can grow into a package of the same name. In
  `domains`, `projections` and `shared`, `core/`, `model/`, `policy/`,
  `event/`, `ports/`, `service/` and `boundary/` packages take the layer of
  the matching `.py` module, as do `model/`, `core/`, `policy/`, `ports/` and
  `cli/` in `flat`. Files inside such a package take its layer whatever their
  own name; `persistence/` still wins below it. Previously these files were
  unclassified (`LIT002`) in `domains`, and shell in `flat`.

## 0.14.0

### Rules

- **LIT305** accepts immutable references as parameter defaults: `UPPER_CASE`
  constants, enum members such as `Status.OPEN`, tuples of those, and
  `frozenset`, `tuple`, `Decimal`, `Fraction` and `timedelta` calls over
  immutable arguments. A same-module constant bound to a mutable value, any
  other call, and lambdas are still reported.

## 0.13.0

Adopting lint-it on an existing codebase, and flexibility for layouts that do
not match the built-in ones.

### Adoption

- **Baseline.** `workspace.baseline` names a JSON file of known findings,
  keyed by file, rule and message rather than line. `lint-it baseline` writes
  it; `check` reports only findings beyond it, plus a `LIT003` finding for
  entries that no longer match; `lint-it baseline --prune` only ever removes
  entries. `check --no-baseline` shows everything.
- **`[[ignore]]`** switches rules off by path glob and/or layer, with a reason.
  Unknown rules, `LIT001`/`LIT003`, and entries that suppress nothing in a full
  check are `LIT003` findings.
- **`lint-it report`** ranks findings (new and baselined) by rule, `LIT101`
  layer edge, target and directory, as text or JSON; `--rule` focuses it.
- Findings carry a `target`: the module, package, base, call or name they are
  about. JSON output includes it, and the summary adds `baselined` and
  `ignored` counts.

### Flexibility

- **Custom layers.** `[layers.<name>]` with a built-in `base` follows that
  layer's rules under its own name. It inherits the base's dependency, import
  and call policy unless the manifest names it, and counts as its base when
  imported. `deterministic = true` holds it to core's `LIT201` standard.
- **`LIT306 forbidden-call`** and `[forbidden_calls]`: per-layer bans on
  resolved call names, `module.*` for a whole module. Nothing by default.
- **`[[allowed_dependencies]]`** lets listed importer layers use named
  workspace modules (`module.*` for a tree) regardless of their layer, with a
  reason. Entries that match no module are `LIT003` findings.
- **Layout precedence.** A custom layout's globs now come after the
  conventional `tests/`, `scripts/`, `examples/` and `migrations/` patterns,
  so they can reclassify them. `src/**/__init__.py` markers still come last.

### Speed

- A 3,000-file workspace checks in about 7s instead of 72s with identical
  findings: top-level imports, initialization imports and resolved symbols are
  computed once per module, cyclic garbage collection is off during a run, and
  rule checks fan out to forked workers (`--jobs`, default one per CPU; falls
  back to in-process where `fork` is unavailable).

### Fixes

- A string constant holding a lone surrogate no longer crashes symbol
  resolution, and parsing strings as forward references no longer leaks
  `SyntaxWarning`s.
- Findings at the same position are ordered by message, so output is stable.

### Python API

- `Policy.layer_dependencies`, `forbidden_imports` and the new
  `forbidden_calls` are keyed by layer name. `Classification` gains `name`
  (the configured layer; `layer` is the base layer whose rules apply).
  `engine.run` returns new, baselined and ignored findings; `engine.check`
  still returns the findings to report.

## 0.12.0

- `LIT403 restricted-subclassing`: a class may only extend an allowlisted base
  (builtins, `typing`/`enum` bases, Pydantic models and settings, SQLAlchemy
  declarative bases and `TypeDecorator`) or a workspace class that directly
  extends one. Exception hierarchies may nest to any depth, and tables may mix
  in plain workspace classes next to a declarative base. Configure with `conventions.allowed_bases` and
  `conventions.extend_allowed_bases`.

## 0.11.0

- `[extend_forbidden_imports]` adds packages to a layer's forbidden list
  instead of replacing it; the key `"*"` adds them to every layer. Use it to
  keep a legacy package out of a new one without copying the defaults.

## 0.10.0

A redesign for the first public release. Nothing is backward compatible with
0.9: the manifest schema, rule codes, CLI and Python API have all changed.

### Workspace model

- A manifest is optional. Without `lint-it.toml`, every package is a `server`
  with the `domains` layout. There is no filename-guessing mode: every rule
  uses the layer of the file it checks.
- Packages have a `kind` (`server`, `client`, `library`) and a `layout`,
  replacing the eight package roles.
- Nine layers: `core`, `port`, `shell`, `adapter`, `router`, `boundary`,
  `transaction`, `test`, `marker`. Migrations are `transaction`; tests and
  fixtures are `test`.
- Built-in layouts `domains`, `hexagonal`, `flat`, `boundary` and
  `test-support`. Custom `[layouts.<name>]` may `extends` a built-in.
- Policy is data: `[layer_dependencies]`, `[forbidden_imports]` and
  `[conventions]` replace the built-in entries they name.
- Manifest problems are findings (`LIT003`). A manifest that cannot be loaded
  exits with status 2.

### Rules

Rules are renumbered by family and use the `LIT` prefix (0.9 used `PAL`). Each
has a name and a docstring, and `docs/rules.md` is generated from them.

| New | Replaces |
| --- | --- |
| LIT001 parse-error | PAL000 |
| LIT002 unclassified-file | PAL016 |
| LIT003 manifest | CLI coverage and override errors |
| LIT101 layer-dependency | PAL003, PAL010, PAL017, boundary imports in PAL024 |
| LIT102 forbidden-import | PAL007, PAL009, PAL012, imports in PAL014, PAL024 frameworks |
| LIT103 client-imports-server | PAL008 |
| LIT201 nondeterminism | PAL011 |
| LIT202 io-in-core | calls in PAL014 |
| LIT203 ambient-state | PAL020, without environment access |
| LIT204 borrowed-mutation | PAL019 |
| LIT205 frozen-values | PAL021 |
| LIT206 async-in-core | PAL022 |
| LIT207 effectful-capability | PAL023 |
| LIT301 environment-access | PAL004 |
| LIT302 transaction-boundary | PAL005 |
| LIT303 router-construction | PAL006 |
| LIT304 mocking | PAL002 |
| LIT305 immutable-defaults | PAL001, without the FastAPI exemptions |
| LIT401 boolean-policy | PAL013 |
| LIT402 expected-outcome | PAL015 |

- PAL018 (runtime settings naming) is removed.
- LIT101 checks every restricted layer, not only core and port: shells may not
  import adapters or edges, adapters may not import shells, and routers may not
  import core or adapters directly.
- LIT301 now allows environment access only in boundary, transaction and test
  modules; routers are no longer exempt.
- Identical findings are reported once.

### CLI

- Subcommands: `check`, `classify`, `explain`, `init`, `rules`.
- `check --format text|json|github`. JSON is `{"findings": [...], "summary": {...}}`.
  Filenames are relative to the workspace root.
- `check PATH...` reports findings under those paths but always analyzes the
  whole workspace.
- `python -m lint_it` runs the CLI.

### Removed

- The Flake8 adapter.
- `lint-it-advisory` (PLC001–006) and `lint-it-packages` (PKG001–003).

### Distribution

- Python 3.12 and later. CI tests 3.12, 3.13 and 3.14.
- A pre-commit hook (`.pre-commit-hooks.yaml`).

## 0.9.1

- Standalone release extracted from the existing 0.9.0 package.

## 0.9.0

Previously distributed through a private package index.
