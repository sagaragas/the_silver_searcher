# Publication Notes

Worker-facing guidance for the final long-form memo/blog output.

---

- Target output: long-form technical memo intended for `ragas.dev/blogs`.
- Mandatory sections: methods, results, regressions/failures, limitations/trade-offs, licensing, adversarial Q&A.
- Every numeric claim must map to a claim ID and evidence artifact.
- Memo metrics must reconcile exactly with benchmark summary artifacts.
- For uncertainty stats (IQR/CI) used in memo/Q&A claims, treat `benchmarks/out/<run>/sampling_validation.json` as the authoritative evidence artifact.
- Narrative must include regressions and caveats; no winner-only reporting.
- Public publication commit must be traceable to parity and benchmark evidence commits.
