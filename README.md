<p align="center"><img src="docs/icon.svg" width="96" height="96" alt=""></p>

# lint-it

**A leash for LLM-written Python.**

## Why?

Python written by LLMs sucks.

lint-it is the remedy for that. It's based on a handful of good ideas:

- [Functional Core, Imperative Shell](https://www.destroyallsoftware.com/screencasts/catalog/functional-core-imperative-shell).
- [Parse, don't validate](https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/).
- [The Zen of Python](https://peps.python.org/pep-0020/): "There should be one, and preferably only one, obvious way to do it."

- Separate business logic from code that talks to the outside world (data you don't control).
- Isolate side effects.
- Build on pure functions and values.
- Don't rely on global state.
- Inject your dependencies; it makes testing easier.
- Parse outside data with Pydantic, convert it to dataclasses, then run the business logic.
- Model domain data as well-structured dataclasses.
- Prefer functions to methods.
- You rarely need subclassing.
- Raise exceptions only in specific places.
- No default arguments or default values. Be explicit: you're not the one writing the code, the LLM is.

## How it works

Every file belongs to a layer, decided by its path: `core`, `port`, `shell`,
`adapter`, `router`, `boundary`, `transaction`, `test`. Each layer has rules
about what it may import and which effects it may perform. Imports are followed
across packages, re-exports and `__init__.py` files, so a dependency can't be
laundered through a re-export.

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
lint-it report                  # rank findings by rule, layer edge, target and area
lint-it baseline                # record current findings so only new ones fail
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
usage errors or a manifest that cannot be loaded. Large workspaces are checked
in parallel worker processes; `--jobs 1` checks in-process.

### Adopting lint-it on an existing codebase

Describe the code you have instead of moving it first: a custom layout maps
today's directories to layers, and custom layers name the roles that don't fit
the built-in ones (a Temporal workflow is a deterministic router). Then:

1. `lint-it report` shows which rules, layer edges and imported modules produce
   the findings, so you can tell policy questions from real debt.
2. Settle policy in the manifest: `[[allowed_dependencies]]` for modules that
   act as ports, `[[ignore]]` for a rule you are not adopting yet in a given
   place, `[conventions]` for your framework bases. Each needs a reason.
3. Set `workspace.baseline` and run `lint-it baseline`. `check` now fails only
   on new findings, and on baseline entries that no longer match until you run
   `lint-it baseline --prune`, so the baseline can only shrink.

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
conventional module may grow into a package of the same name: the files of
`domains/orders/core/` are core like `domains/orders/core.py`. A
package's `kind` (`server`, `client` or `library`) controls whether other
packages may depend on it. Custom layers (`[layers.<name>]`) follow a built-in
layer's rules with their own dependency policy.

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
