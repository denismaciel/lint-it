# Python / Rust comparison

This benchmark compares the existing Python implementation with the standalone
Rust port. It measures a complete fresh-process `check --format json`, including
startup, file discovery, parsing, symbol resolution, rules and output. It does
not compare lint-it's rules with Ruff's different rules.

## Reproduce

```sh
uv sync --locked
cargo build --locked --release --manifest-path rust/Cargo.toml
uv run python -m pytest -p benchmarks.differential_plugin
uv run python benchmarks/compare.py --project requests --project flask --runs 7 --jobs 1 4
```

The runner downloads immutable revisions listed in [projects.json](projects.json)
into ignored `benchmarks/target/`. Requests and Flask are the default selection;
CI also uses only those two projects. No upstream
project code is imported or executed. It overlays the **same** explicit lint-it
manifest for both executables: Python files are core, test directories are test,
examples are boundary, and package initializers are markers. This intentionally
exercises the rules; the resulting findings aren't recommendations for those
projects' architectures. Upstream source files remain unchanged.

Requests and Flask exercise `src` package identities and cross-file resolution.
The original report also includes historical Django measurements. Django was
not rerun for the optimization report.

For each project and worker setting the runner:

1. Warms both commands once and compares their complete JSON and exit statuses.
2. Runs seven measured invocations of each, rotating execution order.
3. Requires every measured result to equal the reference, including filename,
   line, byte column, rule, message, target, package/file counts and suppressions.
4. Records every elapsed sample, median, speedup and input/output hashes in
   [results.json](results.json). Any mismatch aborts instead of publishing a speedup.

The filesystem is warm; there is no persistent analysis cache. Times are elapsed
wall time on the recorded host, not an isolated CPU microbenchmark. Python uses
its normal process-pool policy: at least 150 files per worker. Thus `--jobs 4`
still runs Requests and Flask serially in Python, while Rust uses four Rayon
threads. The one-worker rows provide the direct serial comparison.

## Optimization results

Seven runs per configuration, comparing Python, the original Rust binary from
`020dcf8`, and the optimized Rust binary in the same run. Complete JSON and exit
statuses match across all three binaries on every invocation. Raw timings and
binary/input hashes: [optimized-results.json](optimized-results.json).

| Project | Workers | Python | Rust before | Rust after | Rust gain | vs Python |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Requests | 1 | 0.998 s | 0.419 s | 0.299 s | 1.40× | 3.34× |
| Requests | 4 | 1.010 s | 0.194 s | 0.127 s | 1.53× | 7.97× |
| Flask | 1 | 1.096 s | 0.510 s | 0.342 s | 1.49× | 3.20× |
| Flask | 4 | 1.173 s | 0.177 s | 0.146 s | 1.21× | 8.04× |

The changes remove recursive subtree copies during AST construction and reuse
complete import traversals within a command. Duplicate loaded targets are removed
in first-encounter order; importer-specific policy and source locations remain
separate. No persistent analysis cache is used.

Initial single-worker profiling put AST conversion at 38–41% of command time,
versus 3–5 ms for Ruff parsing. Dependency checks took another 16–26%. These
measurements motivated the two changes; final benchmarks use uninstrumented
release binaries. Typed AST storage and cheaper symbol lookups remain possible
future improvements.

To compare a saved original binary with the current release:

```sh
uv run python benchmarks/compare.py --project requests --project flask --runs 7 --jobs 1 4 \
  --baseline-binary /path/to/original/lint-it-rust --output benchmarks/optimized-results.json
```

## Eight-worker follow-up

[eight-worker-results.json](eight-worker-results.json) records seven full
Python/original-Rust/optimized-Rust comparisons at eight workers, followed by
11 alternating four/eight-worker pairs on the optimized binary. Each pair checks
complete JSON and exit status against Python after one warmup pair.

| Project | 4 workers | 8 workers | 8-worker speedup |
| --- | ---: | ---: | ---: |
| Requests | 327 ms | 312 ms | 1.05× |
| Flask | 357 ms | 354 ms | 1.01× |

Several unrelated Rust compilations were running during this follow-up. Absolute
times are not comparable to the earlier optimization results. Under this load,
eight workers show little benefit; these measurements do not establish scaling
on an idle host. Every output still matches Python exactly.

## Original port results (historical)

Original measurements are recorded in `results.json`; the table below is generated
from those medians after the equivalence gates pass.

| Project | Workers | Files | Findings | Python | Rust | Speedup |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Requests | 1 | 36 | 637 | 1.002 s | 0.442 s | 2.26× |
| Requests | 4 | 36 | 637 | 1.074 s | 0.179 s | 6.01× |
| Flask | 1 | 83 | 279 | 1.221 s | 0.508 s | 2.40× |
| Flask | 4 | 83 | 279 | 1.168 s | 0.171 s | 6.84× |
| Django | 1 | 2,818 | 10,860 | 28.272 s | 15.750 s | 1.80× |
| Django | 4 | 2,818 | 10,860 | 9.753 s | 7.276 s | 1.34× |

Host: AMD Ryzen 7 255 w/ Radeon 780M Graphics (16 logical CPUs), Python 3.14.9, Rust 1.99.0.

All six configurations passed full equivalence. Rust was faster in each measured
configuration; the advantage varies considerably with project size and worker policy.

## Equivalence coverage

The native regression run passes 578 pytest cases, including 457 comparisons of
real workspace checks with the Python engine. It also compares CLI rendering and
manifest rejection, and exercises native baseline creation/pruning against
Python. Twelve Rust unit tests cover parser locations, alias scopes, globs,
workspace classification and syntax/configuration errors.

The pinned project comparison adds thousands of real files, every diagnostic
field, and both worker configurations. These are tested equivalence guarantees
for the supplied cases, not proof over all possible Python programs. See the
[implementation notes](../rust/README.md) for remaining parser wording and
unusual expression-rendering limitations.
