# Benchmarking Notes

Guidance for benchmark harness implementation and interpretation.

---

- Comparator set is fixed: **Rust rewrite + `ag` + `rg` + `ugrep`**.
- Heavy benchmark cadence: nightly CI + manual CI dispatch.
- Required controls: interleaved/randomized run order, warmup/sample policy, auditable outlier policy.
- Required outputs: raw samples, summary metrics, environment metadata, manifest hashes, checksums, publication manifest.
- No winner claims without claim-threshold gate pass across local + nightly + manual runs.
- Correctness gate policy: **`ag` vs `rust-ag` parity divergence is a hard failure**; cross-tool (`rg`/`ugrep`) hash differences are advisory details and do not fail the gate by themselves.
- Harness CLI contract: when correctness gate fails, `benchmarks/harness.py` benchmark modes must exit non-zero even if scenario cell execution itself reports zero errors.
- Latest-run resolution contract: treat only canonical timestamp-form run directories as eligible `latest` targets, and reject symlink targets that do not resolve to canonical run directories under the benchmark output root.
- Stdin/stream semantics: scenarios declaring `stdin_data` must execute as stdin-driven searches with no corpus/file argument. Template integrity enforcement (e.g., `{corpus}` placeholder checks) must not regress stdin-only execution paths.
