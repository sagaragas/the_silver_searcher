# User Testing Surface

Testing surface information for validators and workers.

---

## Surface

- Primary surface: CLI commands (`ag` baseline and Rust rewrite binary).
- Comparator CLIs for benchmarks: `ag`, `rg`, `ugrep`, Rust rewrite binary.
- No browser/TUI flows required for this mission.

## Setup Steps

1. Run `./.factory/init.sh`.
2. Build baseline if needed: `./build.sh`.
3. Validate baseline tests: `PATH=".venv-ag-tests/bin:$PATH" make test`.
4. Run smoke benchmark command from services manifest once harness exists.

## Known Quirks

- Docker daemon is unavailable; no Docker-based setup.
- `cram` must be installed in local venv (`.venv-ag-tests`), not system pip.
- One-device/symlink edge cases may be platform-dependent and require explicit skip notes.
- Version output may vary by compile-time features; normalize format where required by contract.
- `scripts/parity/run_matrix.py` has CLI groups `cli-formatting`, `cli-exit-errors`, and `cli-count-stream`; `cli-count-stream` artifacts currently cover multi-file count/filename slices, while full `VAL-CLI-001..003` evidence still requires explicit single-file and stdin stream checks.
- Baseline `ag` disables stdin stream mode when `--parallel` is enabled; stream parity checks should omit `--parallel` while keeping deterministic flags (`--nocolor --workers=1 --noaffinity`).
- Running selected parity pytest targets can mutate generated manifest snapshots (for example `manifests/fixtures.json`) during verification workflows; restore/verify manifest state before finalizing validation evidence.

## Evidence Capture Requirements

- Always record command, `stdout`, `stderr`, and exit code for CLI parity checks.
- For benchmark checks, attach run manifest, environment metadata, and checksum report.
- For publication checks, attach claim-evidence map and metric reconciliation report.

## Flow Validator Guidance: CLI

- Parallel flow validators must use only assigned assertion IDs and data namespace labels in their reports.
- Do not modify source code, manifests, or baseline artifacts during validation runs.
- Keep all generated evidence under `.factory/validation/<milestone>/user-testing/flows/` with deterministic JSON output.
- Treat shared filesystem state as read-only except for assigned flow report files.
