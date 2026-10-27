<p align="center"><img src="docs/icon.svg" width="96" height="96" alt=""></p>

# lint-it

**A leash for LLM-written Python.**

Python has the ecosystem, and language models write a lot of it. What they write
tends to drift the same way: state mutated in place, environment variables read
deep inside business logic, `datetime.now()` in the middle of a calculation,
`bool` flags that quietly switch modes, framework models leaking into everything.
Each line looks reasonable on its own. Six months later nothing can be tested
without mocks, and no function can be understood without reading all the others.

lint-it makes the structured version the only version that passes. Your code
gets a **functional core** (plain functions over immutable values) and an
**imperative shell** (the code that does I/O, reads the clock, and talks to
frameworks), and lint-it checks that each stays in its lane. It runs in CI and
pre-commit, so the agent hits the wall, reads the message, and fixes its own
code before you review it.

## What it catches

A function an assistant might write in `src/shop/domains/orders/core.py`:

```python
import os
from datetime import datetime

from pydantic import BaseModel

APPLIED = {}


class Order(BaseModel):
    id: str
    total: float


def apply_discount(order: Order, vip: bool) -> bool:
    if vip or os.getenv("PROMO_ACTIVE"):
        order.total = order.total * 0.9
        APPLIED[order.id] = datetime.now()
        return True
    return False
```

```text
$ lint-it check
src/shop/domains/orders/core.py:4:1: LIT102 core modules cannot import pydantic
src/shop/domains/orders/core.py:14:1: LIT401 decision 'apply_discount' returns bool; return a named result or enum
src/shop/domains/orders/core.py:14:34: LIT401 policy input 'vip' is boolean; use a named enum or value type
src/shop/domains/orders/core.py:15:15: LIT301 core modules cannot read the environment; read configuration at a boundary and pass it in
src/shop/domains/orders/core.py:16:9: LIT204 mutation of caller-owned 'order'; build and return a new value
src/shop/domains/orders/core.py:17:9: LIT203 mutable module state 'APPLIED'; use an immutable constant or pass a snapshot
src/shop/domains/orders/core.py:17:29: LIT201 datetime.datetime.now hides nondeterminism; pass the observed time, ID, or random value into the core
7 findings in 1 file (1 file in 1 package checked)
```

Seven findings in nineteen lines, and every message says what to do instead.
The version that passes takes everything it depends on as an argument and
returns a new value:

```python
def apply_discount(order: Order, tier: Tier, promo: Promo, now: datetime) -> Order | Discounted:
    if tier is Tier.REGULAR and promo is Promo.INACTIVE:
        return order
    return Discounted(replace(order, total=order.total * 0.9), applied_at=now)
```

`Order` and `Discounted` are frozen dataclasses; `Tier` and `Promo` are enums.
The shell reads the environment and the clock once and passes the results in.
Testing this function takes no mocks, no fixtures and no frozen clock, because
it has nothing to patch.

## The ideas behind it

None of this is new. lint-it turns a few well-known ideas into rules a machine
can enforce:

- [Functional Core, Imperative Shell](https://www.destroyallsoftware.com/screencasts/catalog/functional-core-imperative-shell)
  and [Boundaries](https://www.destroyallsoftware.com/talks/boundaries), by
  Gary Bernhardt: decisions are pure functions over values; effects live in a
  thin shell around them.
- [Parse, don't validate](https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/),
  by Alexis King: turn untrusted input into precise types once, at the edge.
  Validation frameworks stay at the boundary (LIT102), and the core receives
  enums and frozen values (LIT205, LIT401) instead of re-checking raw data.
- [The Zen of Python](https://peps.python.org/pep-0020/): "There should be one,
  and preferably only one, obvious way to do it." Python has accumulated many
  ways. lint-it picks one: functions and values, with effects at the edges.

## How it works

Every file belongs to a layer, decided by its path: `core`, `port`, `shell`,
`adapter`, `router`, `boundary`, `transaction`, `test`. Each layer has rules
about what it may import and which effects it may perform. Imports are followed
across packages, re-exports and `__init__.py` files, so a dependency can't be
laundered through a re-export.

- **No escape hatches.** There are no `# noqa` comments, no baselines and no
  per-rule switches. A real exception goes in `lint-it.toml` with a reason and
  an issue link, and counts against an explicit budget that starts at zero.
- **Reads code, never runs it.** lint-it parses source and never imports your
  modules. It has no runtime dependencies and supports Python 3.12 and later.
- **Fast enough to run on every commit.** Checking lint-it's own 45 files takes
  about half a second.

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
