# Releasing the native Python package

Distribution remains GitHub Git tags and attached Python wheels/sdists. Installing
from Git or an sdist uses `hatch_build.py` to fetch a release executable and verify
its SHA-256 against the committed `native-artifacts.json`. Wheel installations
need no download. No runtime fallback or runtime network access is used.

1. Update the version in `pyproject.toml`, `rust/Cargo.toml`, `rust/Cargo.lock`,
   `uv.lock`, and the changelog. Build Rust locally and use
   `LINT_IT_NATIVE_BINARY=/absolute/path/to/lint-it-rust uv sync` for development.
2. Run the **Native release artifacts** workflow on the release commit. All five
   targets must build and pass native/Python packaging smoke tests. Download the
   artifacts; Linux executables are statically linked musl builds.
3. Generate `native-artifacts.json` with the version and SHA-256 of each executable.
   Do not rebuild Rust after this step without replacing the manifest and artifacts.
   Regenerate `THIRD_PARTY_NOTICES.txt` with `uv run python scripts/generate_notices.py`
   when changing dependencies or the Rust toolchain, updating pinned runtime notices
   when needed.
4. Build each wheel from the final checkout using `LINT_IT_NATIVE_BINARY` and
   `LINT_IT_NATIVE_TARGET` for the matching downloaded executable. Build the sdist
   from that same checkout. Verify metadata, embedded executables, notices, and
   clean wheel/sdist installations. Run the complete differential suite and CI.
5. Commit the checksum manifest and metadata, merge, and tag `v<VERSION>`. Create
   the GitHub release with all five executables, wheels, sdist, and `SHA256SUMS`.
   The manifest pins executable bytes; retain these assets for pinned Git clients.
6. Verify a fresh Git-tag install and the pre-commit hook after publication, without
   `LINT_IT_NATIVE_BINARY` or a Rust toolchain in the client's environment.

`LINT_IT_NATIVE_BINARY` is an explicit development/release-build override; normal
client builds always use the version-pinned, checksum-verified release assets.
`LINT_IT_NATIVE_TARGET` supports packaging a prebuilt executable for another host;
it must match the supplied binary. Release builders are responsible for verifying
that pairing. Never publish a locally built Nix/glibc binary as the portable Linux
musl artifact.
