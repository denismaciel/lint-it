# Changelog

## Unreleased

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
