# The Silver Searcher — Rust Rewrite & Performance Study

A code-searching tool similar to `ack`, with a focus on speed.
This repository contains the original C implementation of `ag` **and** an
incremental Rust rewrite (`rust-ag`) with a reproducible benchmark harness and
an evidence-linked technical performance memo.

## Mission Context

This fork carries a structured rewrite of [ggreer/the_silver_searcher](https://github.com/ggreer/the_silver_searcher)
into Rust, accompanied by:

- **Parity tests** — golden-output fixtures that compare `rust-ag` against
  baseline `ag` across stdout, stderr, and exit-code channels.
- **Benchmark harness** — scenario-matrix benchmarks comparing the Rust rewrite
  against `ag`, `rg` (ripgrep), and `ugrep` with interleaved runs, warmup
  policy, environment metadata capture, and raw-sample retention.
- **Publication package** — a long-form technical memo with claim-evidence
  linkage, metric reconciliation, license inventory, and adversarial Q&A,
  intended for publication at `ragas.dev/blogs`.

Public fork: <https://github.com/sagaragas/the_silver_searcher>

## Repository Layout

```
.
├── src/                 # Original C source for ag
├── rust-ag/             # Rust rewrite (Cargo workspace member)
│   ├── src/             #   Rust source (main.rs, search, ignore, CLI)
│   └── tests/           #   Rust integration / parity tests
├── tests/               # Upstream cram-based ag tests
├── scripts/
│   ├── parity/          # Parity runner & validation scripts
│   └── bench/           # Scenario-manifest builder
├── benchmarks/          # Benchmark harness, validators, and output artifacts
│   ├── harness.py       #   Main harness entry point
│   ├── out/             #   Run artifacts (latest symlink)
│   └── tests/           #   Harness unit tests
├── publication/         # Memo, claim-evidence map, license inventory, gates
├── Cargo.toml           # Workspace root (members: rust-ag)
├── build.sh             # Original C build (autogen + configure + make)
└── .factory/            # Mission infrastructure (services, library, init)
```

## Prerequisites

| Dependency | Purpose |
|---|---|
| Homebrew | macOS package manager (init script uses `brew`) |
| `automake`, `autoconf`, `pkg-config` | C build toolchain for baseline `ag` |
| `pcre`, `xz` | Libraries required by baseline `ag` |
| Rust / Cargo | Rust rewrite build and test |
| `ripgrep` (`rg`) | Benchmark comparator |
| `ugrep` | Benchmark comparator |
| Python 3 | Parity scripts, benchmark harness, publication gates |
| `cram` (Python, in `.venv-ag-tests`) | Upstream ag test runner |

All prerequisites are installed automatically by the init script (see below).

## Setup

Run the one-time init script to install dependencies, create the Python venv,
build baseline `ag`, and fetch Rust crates:

```sh
.factory/init.sh
```

This is idempotent and safe to re-run.

## Building

Build the original C `ag` binary and the Rust rewrite:

```sh
# Original C ag
./build.sh

# Rust rewrite (debug)
cargo build --workspace

# Rust rewrite (release, used by benchmarks)
cargo build --workspace --release
```

## Running Tests

### All tests (baseline ag + Rust)

```sh
PATH=".venv-ag-tests/bin:$PATH" make test   # upstream cram tests for C ag
cargo test --workspace -- --test-threads=5   # Rust unit + integration tests
```

### Lint and type-check (Rust)

```sh
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo check --workspace
```

## Parity Validation

Parity scripts compare `rust-ag` output against baseline `ag` on golden
fixtures across stdout, stderr, and exit code.

```sh
# Smoke parity (baseline)
python3 scripts/parity/run_matrix.py --target baseline --group smoke

# Core ignore/recursion parity (Rust)
python3 scripts/parity/run_matrix.py --target rust --group core-ignore-recursion

# Core matching parity (Rust)
python3 scripts/parity/run_matrix.py --target rust --group core-matching

# CLI count/stream parity (Rust)
python3 scripts/parity/run_matrix.py --target rust --group cli-count-stream

# Validate latest parity run
python3 scripts/parity/validate_outputs.py --run latest

# Verify fixture and scenario manifest integrity
python3 scripts/parity/validate_fixture_integrity.py
python3 scripts/parity/build_fixture_manifest.py --verify
python3 scripts/bench/build_scenario_manifest.py --verify
```

## Benchmark Harness

The harness runs scenario-matrix benchmarks with interleaved execution,
warmup, and raw-sample capture across four comparators.

```sh
# Smoke benchmark (quick, no statistical claims)
python3 benchmarks/harness.py smoke --comparators rust ag rg ugrep

# Measured benchmark (statistical samples)
python3 benchmarks/harness.py measured --comparators rust ag rg ugrep \
    --scenarios literal-simple --warmup 2 --samples 3 --timeout 30

# Validate latest benchmark run
python3 benchmarks/validate_manifest.py --run latest
python3 benchmarks/validate_env_metadata.py --run latest
python3 benchmarks/validate_sampling.py --run latest
python3 benchmarks/manifest_pinning.py verify --run latest

# Correctness gate (ag vs rust-ag parity is a hard failure)
python3 benchmarks/correctness_gate.py --run latest

# Claim gate (threshold checks for performance claims)
python3 benchmarks/claim_gate.py --run latest

# Benchmark unit tests
python3 -m pytest benchmarks/tests/ -v
```

## Publication & Evidence Workflow

The publication layer produces a long-form technical memo with claim-evidence
linkage, metric reconciliation against benchmark artifacts, license disclosure,
and style/quality gates.

```sh
# Claim-evidence validation
python3 publication/check_claims.py --memo publication/ragas_blog_memo.md

# Metric reconciliation (memo values vs benchmark summary)
python3 publication/reconcile_metrics.py --memo publication/ragas_blog_memo.md \
    --summary benchmarks/out/latest/summary.json

# Style and specificity gate
python3 publication/style_gate.py --memo publication/ragas_blog_memo.md

# License audit (requires publication/license_inventory.json)
python3 publication/license_audit.py

# Traceability check (memo commit ↔ parity/benchmark evidence)
python3 publication/traceability_check.py --memo publication/ragas_blog_memo.md \
    --run latest

# Metric table validation
python3 publication/validate_metrics_tables.py --memo publication/ragas_blog_memo.md

# Publication test suite
python3 -m pytest publication/tests/ -v

# Package publication artifacts (checksums + manifest)
python3 benchmarks/package_publication_artifacts.py --run latest
python3 benchmarks/verify_checksums.py \
    --manifest benchmarks/out/latest/publication/publication_manifest.json
```

## Original C Build (Upstream Reference)

<details>
<summary>Upstream build and install instructions (for reference)</summary>

### Building from source

1. Install dependencies (Automake, pkg-config, PCRE, LZMA):

   **macOS:**
   ```sh
   brew install automake pkg-config pcre xz
   ```

   **Ubuntu/Debian:**
   ```sh
   apt-get install -y automake pkg-config libpcre3-dev zlib1g-dev liblzma-dev
   ```

   **Fedora:**
   ```sh
   yum -y install pkgconfig automake gcc zlib-devel pcre-devel xz-devel
   ```

2. Run the build script:
   ```sh
   ./build.sh
   ```

3. Install:
   ```sh
   sudo make install
   ```

### Building a release tarball

GPG-signed releases are available at <http://geoff.greer.fm/ag>.

```sh
./configure
make
make install
```

</details>

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

The original Silver Searcher is copyright 2011–2016 Geoff Greer.
The Rust rewrite (`rust-ag`) is licensed under Apache-2.0.
Third-party attribution is documented in `publication/license_inventory.json`.
