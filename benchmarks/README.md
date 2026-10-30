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
uv run python benchmarks/compare.py --runs 5 --jobs 1 4
```

The runner downloads immutable revisions listed in [projects.json](projects.json)
from Requests, Flask and Django into ignored `benchmarks/target/`. No upstream
project code is imported or executed. It overlays the **same** explicit lint-it
manifest for both executables: Python files are core, test directories are test,
examples are boundary, and package initializers are markers. This intentionally
exercises the rules; the resulting findings aren't recommendations for those
projects' architectures. Upstream source files remain unchanged.

Requests and Flask exercise `src` package identities and cross-file resolution.
Django provides a much larger tree and an intentionally invalid Python fixture.
The existing Python implementation only assigns module identities beneath `src/`;
the Rust implementation preserves that behavior for Django's flat tree.

For each project and worker setting the runner:

1. Warms both commands once and compares their complete JSON and exit statuses.
2. Runs five measured invocations of each, alternating execution order.
3. Requires every measured result to equal the reference, including filename,
   line, byte column, rule, message, target, package/file counts and suppressions.
4. Records every elapsed sample, median, speedup and input/output hashes in
   [results.json](results.json). Any mismatch aborts instead of publishing a speedup.

The filesystem is warm; there is no persistent analysis cache. Times are elapsed
wall time on the recorded host, not an isolated CPU microbenchmark. Python uses
its normal process-pool policy: at least 150 files per worker. Thus `--jobs 4`
still runs Requests and Flask serially in Python, while Rust uses four Rayon
threads. The one-worker rows provide the direct serial comparison.

## Results

Final measurements are recorded in `results.json`; the table below is generated
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

The native regression run passes 577 pytest cases, including 456 comparisons of
real workspace checks with the Python engine. It also compares CLI rendering and
manifest rejection, and exercises native baseline creation/pruning against
Python. Twelve Rust unit tests cover parser locations, alias scopes, globs,
workspace classification and syntax/configuration errors.

The pinned project comparison adds thousands of real files, every diagnostic
field, and both worker configurations. These are tested equivalence guarantees
for the supplied cases, not proof over all possible Python programs. See the
[implementation notes](../rust/README.md) for remaining parser wording and
unusual expression-rendering limitations.
