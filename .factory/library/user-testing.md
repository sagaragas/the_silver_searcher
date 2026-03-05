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

## Evidence Capture Requirements

- Always record command, `stdout`, `stderr`, and exit code for CLI parity checks.
- For benchmark checks, attach run manifest, environment metadata, and checksum report.
- For publication checks, attach claim-evidence map and metric reconciliation report.
