# Native lint-it

Standalone Rust implementation of lint-it's 23 registered rules and seven CLI
commands. The Python distribution bundles this executable and invokes it from
`lint-it` and `python -m lint_it`. The Python implementation remains the reference.

```sh
# Rust >= 1.97, a C compiler and make (jemalloc); validated with Rust 1.99
cargo build --locked --release --manifest-path rust/Cargo.toml
rust/target/release/lint-it-rust check --format json
# Or install the executable:
cargo install --locked --path rust
```

## Implementation

The parser is **Ruff's actual parser**, pinned to `ruff_python_parser`,
`ruff_python_ast` and `ruff_text_size` 0.0.20. These are MIT-licensed upstream
crates, reused as dependencies rather than copied or approximated with regexes.
See [Ruff's parser](https://github.com/astral-sh/ruff/tree/main/crates/ruff_python_parser).

Following techniques used by Ruff, the native implementation uses:

- Rayon workers for reading, parsing, resolving symbols and checking files;
- one immutable workspace snapshot, indexed module lookup and lazy cached
  import/export edges, shared across rules;
- directory pruning before descent, avoiding virtual environments and build trees;
- jemalloc on Unix, following [Ruff's allocator selection](https://github.com/astral-sh/ruff/blob/main/crates/ruff/src/main.rs);
- an optimized release build with thin LTO, deterministic sorted diagnostics,
  and no Python interpreter, subprocess, or Python package dependencies at runtime.

`ast.rs` adapts Ruff's typed AST into the Python-shaped node representation used
by the ported rules. This currently uses in-memory `serde_json::Value` nodes;
there is no JSON serialization between analysis stages. It makes semantic parity
review straightforward but adds allocation/traversal overhead compared with
checking Ruff's typed AST directly. The benchmark measures that cost too.

`symbols.rs` preserves Python's conservative alias resolution, function-local
shadowing, branch merges, forward annotations and comprehension scopes.
`workspace.rs` loads manifests and classifies files; `dependencies.rs` follows
re-exports and package initialization; `engine.rs` applies ignores, baselines and
path selection. All user-facing diagnostic fields retain their Python meanings,
including zero-based UTF-8 byte columns in JSON.

## Verification

From the repository root:

```sh
uv sync --locked
cargo test --locked --release --manifest-path rust/Cargo.toml
cargo clippy --locked --release --manifest-path rust/Cargo.toml --all-targets -- -D warnings
cargo fmt --manifest-path rust/Cargo.toml --check
uv run python -m pytest -p benchmarks.differential_plugin
uv run python benchmarks/compare.py --project requests --project flask --runs 5 --jobs 1 4
```

The differential pytest plugin runs the existing Python fixtures and compares
native findings, summaries, exit statuses, manifest validation errors, and
non-mutating CLI output. In-memory Python snapshot tests remain Python-only;
they aren't representable by a filesystem CLI invocation. Separate native CLI
tests compare initialization, baseline creation/pruning, and all check formats.

The project benchmark requires complete JSON and exit-status equality before
recording timing, and checks every timed invocation again. See
[the benchmark report](../benchmarks/README.md) and [raw results](../benchmarks/results.json).

Equivalence is tested, not assumed from matching counts. It is not a proof over
all Python input: uncommon malformed Python/TOML/JSON can retain upstream parser
wording, and unusual dynamic class-base expressions may render differently from
CPython's `ast.unparse`. The supported manifests, fixtures and pinned project
corpora are the regression contract enforced by CI.

## Profiling

Build with `cargo build --release --features profile --manifest-path rust/Cargo.toml`
and run `check --jobs 1`. The command writes JSON phase timings to stderr;
stdout remains the normal diagnostics. Timings are inclusive, and parallel
runs sum worker times, so phase totals must not be added together. Build again
without `--features profile` before equivalence checks or performance reporting;
normal builds compile instrumentation away.

The adapter moves owned subtrees into parents instead of serializing borrowed
values with `json!`, which previously copied descendants at each nesting level.
Dependency analysis caches complete loaded-module traversals per workspace,
preserving their first-encounter order and removing duplicate targets. Recursive
partial traversals remain uncached because cycle guards affect their results.
Layer policy, overrides and finding locations are still evaluated per importer.
The cache stores source indices, is shared across workers, and is discarded at
command exit; concurrent cache misses can compute the same result independently.
