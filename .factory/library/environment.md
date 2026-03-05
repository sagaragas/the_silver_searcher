# Environment

Environment variables, external dependencies, and setup notes.

**What belongs here:** Required env vars, dependency setup caveats, platform notes.
**What does NOT belong here:** Service ports/commands (use `.factory/services.yaml`).

---

- Mission is CLI-only; no external services required.
- Docker is unavailable in this environment and must not be required.
- Required toolchain: `automake`, `autoconf`, `pkg-config`, `pcre`, `xz`, `ripgrep`, `ugrep`, `rust/cargo`, `python3`.
- Python venv for baseline tests: `.venv-ag-tests` with `cram` installed.
- Baseline build entrypoint: `./build.sh`.
- Public fork remote expected: `fork -> https://github.com/sagaragas/the_silver_searcher.git`.
