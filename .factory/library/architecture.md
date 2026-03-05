# Architecture

Architectural decisions and patterns for this mission.

---

## Mission Architecture

1. **Baseline Oracle Layer**
   - Uses original `ag` behavior as behavioral source of truth.
   - Stores fixture/corpus/query manifests with checksums.

2. **Rust Rewrite Layer**
   - Implements CLI/search behavior incrementally behind parity tests.
   - Parity compares `stdout`/`stderr`/exit semantics against baseline.

3. **Benchmark Harness Layer**
   - Runs scenario matrix across Rust rewrite + `ag` + `rg` + `ugrep`.
   - Captures run metadata, raw samples, summaries, and checksums.

4. **Publication Layer**
   - Generates evidence-linked long-form memo for `ragas.dev/blogs`.
   - Enforces claim-evidence mapping, reconciliation, and license disclosure.

## Hard Constraints

- No undocumented behavior changes from baseline in parity scope.
- No performance claim without claim-gate artifacts.
- Public publication commit must be traceable to measured evidence artifacts.

## Baseline Semantics Notes

- `ag` treats `--max-count=0` as effectively unlimited because truncation in `src/search.c` is gated on `opts.max_matches_per_file > 0`, even though help text mentions a default max-count of 10,000.
