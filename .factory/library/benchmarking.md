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
