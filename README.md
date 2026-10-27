<p align="center"><img src="docs/icon.svg" width="96" height="96" alt=""></p>

# lint-it

Architecture rules for Python workspaces built as a functional core with an
imperative shell. Every file belongs to a layer; each layer has rules about what
it may import and what effects it may perform. The core computes decisions from
values; the shell does I/O, reads the clock, and talks to frameworks.

lint-it reads source code only: it never imports your modules. It has no runtime
dependencies and supports Python 3.12 and later.

## Install

lint-it is distributed from GitHub, not PyPI. Pin a release tag:

```bash
uv add --dev 'lint-it @ git+https://github.com/denismaciel/lint-it.git@<tag>'
```

Or run it with pre-commit:

```yaml
repos:
  - repo: https://github.com/denismaciel/lint-it
    rev: <tag>
    hooks:
      - id: lint-it
```

## Use

```bash
lint-it init --layout domains   # write a starter lint-it.toml
lint-it check                   # check the whole workspace
lint-it check src/app/orders    # report findings under these paths only
lint-it classify src            # show each file's layer and the pattern that matched
lint-it explain LIT101          # show a rule's documentation
lint-it rules                   # list every rule
```

`check` finds the workspace root from the nearest `lint-it.toml` (or
`pyproject.toml` if there is none), discovers every package with a
`pyproject.toml` below it, and always analyzes the whole workspace so that
imports are followed across files and packages. Output formats are `text`,
`json` (`{"findings": [...], "summary": {...}}`) and `github` (workflow
annotations). Exit status is 0 when clean, 1 when there are findings, and 2 for
usage errors or a manifest that cannot be loaded.

There are no suppressions and no per-rule switches. To change what the rules
mean, change the policy in `lint-it.toml`. Narrow, documented exceptions go in
`[[overrides]]` and `[[dependency_overrides]]` and count against budgets.

## Layers

| Layer | Holds | May import (default) |
| --- | --- | --- |
| `core` | decisions, values, policies | core, port |
| `port` | interfaces the core needs | core, port |
| `shell` | orchestration of core and ports | core, port, shell |
| `adapter` | implementations of ports | core, port, adapter |
| `router` | HTTP handlers | shell, boundary, router, transaction |
| `boundary` | entry points, configuration, schemas | anything |
| `transaction` | units of work, migrations | anything |
| `test` | tests and fixtures | anything |
| `marker` | `__init__.py` files | anything (followed, never a target) |

A package's `layout` maps paths to layers. The built-in layouts are `domains`
(`src/<pkg>/domains/<domain>/{core,model,policy,ports,service}.py`, `app/`,
`integrations/`), `hexagonal` (`domain/`, `application/`, `adapters/`, `web/`),
`flat` (everything is shell, except `model.py`, `core.py`, `policy.py`,
`ports.py`, `adapters/` and `cli.py`), `boundary`, and `test-support`. A
package's `kind` (`server`, `client` or `library`) controls whether other
packages may depend on it.

See [docs/rules.md](docs/rules.md) for every rule and
[docs/configuration.md](docs/configuration.md) for the manifest.

## Development

```bash
uv sync
uv run pytest
uv run ruff format --check . && uv run ruff check .
uv run ty check
uv run lint-it check                                  # lint-it checks itself
uv run lint-it rules --format markdown > docs/rules.md  # after changing a rule docstring
```

A rule is a class with a `code`, a `name`, a docstring (its documentation) and
`check(file: SourceFile)`. Register it in `src/lint_it/rules/registry.py`.

## License

MIT. See [LICENSE](LICENSE).
