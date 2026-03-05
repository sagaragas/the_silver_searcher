# Architecture

Architectural decisions and patterns for this mission.

---

## Mission Architecture

1. **Baseline Oracle Layer**
   - Uses original `ag` behavior as behavioral source of truth.
   - Stores fixture/corpus/query manifests with checksums.

2. **Rust Rewrite Layer**
   - Implements CLI/search behavior incrementally behind parity tests.
   - Parity compares `stdout`, `stderr`, and exit code against baseline (all three channels are compared and contribute to the pass/fail verdict as of summary schema v2).

3. **Benchmark Harness Layer**
   - Runs scenario matrix across Rust rewrite + `ag` + `rg` + `ugrep`.
   - Captures run metadata, raw samples, summaries, and checksums.

4. **Publication Layer**
   - Generates evidence-linked long-form memo for `ragas.dev/blogs`.
   - Enforces claim-evidence mapping, reconciliation, and license disclosure.

## Parity Contract: Three-Channel Comparison

The parity runner (`scripts/parity/run_matrix.py`) compares three channels between
baseline (`ag`) and each target comparator:

1. **stdout** (normalised) — ANSI-stripped, sorted-line normalisation; diff artifact
   stored as `{target}.diff`. Mismatch → parity fail.
2. **stderr** (normalised) — same normalisation as stdout; diff artifact stored as
   `{target}.stderr.diff`. Mismatch → parity fail.
3. **exit code** — exact integer comparison. Mismatch → parity fail.

All three channels must match for a scenario comparison to pass. The parity verdict
field is `"pass"` only when `output_match`, `stderr_match`, and `exit_code_match`
are all `true`. This was introduced in summary schema version 2; schema version 1
runs did not compare stderr content and may have `stderr_match` absent from results.

The output validator (`scripts/parity/validate_outputs.py`) enforces the presence of
`stderr_match` in all comparison results for schema v2+ runs and checks that
`{target}.stderr.diff` artifacts are present and well-formed.

## Hard Constraints

- No undocumented behavior changes from baseline in parity scope.
- No performance claim without claim-gate artifacts.
- Public publication commit must be traceable to measured evidence artifacts.

## Baseline Semantics Notes

- `ag` treats `--max-count=0` as effectively unlimited because truncation in `src/search.c` is gated on `opts.max_matches_per_file > 0`, even though help text mentions a default max-count of 10,000.
- In rust-ag, `-m0`/`--max-count=0` is mapped to `usize::MAX` (truly unlimited). The default when no `-m` flag is given remains 10,000.
- Stream mode `-c -v` must count non-matching lines (invert semantics), not matching lines; parity coverage exists in `rust-ag/tests/parity_cli_count_filename_stream.rs`.
- Stream stdin handling must stay byte-tolerant (read bytes and decode lossily) so non-UTF8 input never panics.
- For `-g` filename filtering, baseline `ag` evaluates the regex against raw traversal paths, then normalizes paths only for printed output. Matching against normalized display paths can regress patterns that intentionally include a leading `./`.
