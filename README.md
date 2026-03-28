# The Silver Searcher — Rust Rewrite

A code-searching tool similar to `ack`, with a focus on speed.
This repository contains the original C implementation of `ag` and `rust-ag`,
an incremental Rust rewrite validated against the upstream tool with parity
fixtures and manifests. The rewrite was produced as part of a brief Factory AI
mission/capabilities test.

## Repository Layout

```text
.
├── src/             # Original C source for ag
├── rust-ag/         # Rust rewrite (workspace member)
├── tests/           # Upstream cram tests and edge-case fixtures
├── scripts/parity/  # Parity runner and validation tooling
├── manifests/       # Deterministic fixture, query, and scenario manifests
├── Cargo.toml       # Workspace root
└── build.sh         # C build entry point
```

## Prerequisites

- `automake`, `autoconf`, `pkg-config`
- `pcre`, `xz`
- Rust / Cargo
- Python 3
- `cram` on `PATH` for `make test`
- `pytest` for parity-tooling tests

## Build

```sh
./build.sh
cargo build --workspace
```

## Bootstrap Edge-Case Fixtures

A fresh clone does not include the generated edge-case artifacts under
`tests/edge-cases/` (notably `large-file/large.txt` and the per-fixture
`.git/` metadata used by the parity fixtures). Before running the validators
below, bootstrap them once:

```sh
python3 tests/edge-cases/setup_fixtures.py
```

## Test

```sh
make test
cargo test --workspace -- --test-threads=5
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo check --workspace
python3 -m pytest scripts/parity -v
python3 scripts/parity/build_fixture_manifest.py --verify
python3 scripts/parity/validate_fixture_integrity.py
python3 scripts/parity/run_matrix.py --target rust --group smoke
python3 scripts/parity/validate_outputs.py --run latest
```

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
The original Silver Searcher is copyright 2011–2016 Geoff Greer.
