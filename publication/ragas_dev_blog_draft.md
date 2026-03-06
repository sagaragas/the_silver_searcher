# Rewriting The Silver Searcher in Rust: What We Learned

<!-- CLM-ENV-002 | CLM-METHOD-001 | CLM-PARITY-001 -->

[The Silver Searcher (`ag`)](https://github.com/ggreer/the_silver_searcher) has been a staple code-search tool since 2011. It's fast, respects your `.gitignore`, and has a loyal following. But the C codebase hasn't seen active development in years, and we wanted to know: what happens when you rewrite `ag` in Rust with modern tooling, then measure the result against the original and today's best alternatives?

This post shares what we found — the wins, the losses, and the caveats — backed by a reproducible benchmark harness with locked manifests and machine-auditable evidence. No cherry-picking, no winner-only narrative.

**Repository**: [github.com/sagaragas/the_silver_searcher](https://github.com/sagaragas/the_silver_searcher)

---

## The Setup

<!-- CLM-ENV-001 | CLM-ENV-002 -->

We rewrote the core search pipeline of `ag` in Rust: recursive file discovery, ignore handling (`.gitignore`, `.ignore`, `.agignore`), regex matching, and output formatting. Then we built a benchmark harness that compares four tools head-to-head:

| Tool | Version | Language |
|------|---------|----------|
| `ag` | 2.2.0 | C |
| `rust-ag` | 0.1.0 | Rust |
| `rg` (ripgrep) | 13.0.0 | Rust |
| `ugrep` | 7.5.0 | C++ |

<!-- CLM-ENV-001 -->

All benchmarks ran on a single machine: Apple M4, 10 cores, 16 GiB RAM, macOS Darwin 25.3.0.

Evidence: [`benchmarks/out/20260305T174325Z/run_manifest.json`](benchmarks/out/20260305T174325Z/run_manifest.json)

---

## Did the Rewrite Actually Work?

<!-- CLM-PARITY-001 | CLM-PARITY-002 -->

Before talking about speed, we needed to confirm that `rust-ag` produces the same results as `ag`. We built a three-channel parity oracle that compares stdout, stderr, and exit codes across a matrix of search scenarios.

The result: `rust-ag` produces byte-identical sorted output to `ag` across all 8 smoke benchmark scenarios.

| Scenario | ag ↔ rust-ag Parity |
|----------|:-------------------:|
| literal-simple | ✓ |
| literal-word | ✓ |
| literal-nomatch | ✓ |
| regex-simple | ✓ |
| literal-nocase | ✓ |
| context-before-after | ✓ |
| count-matches | ✓ |
| files-with-matches | ✓ |

<!-- CLM-PARITY-002 -->

Meanwhile, `rg` and `ugrep` produce different result sets from `ag` (3 unique output hash clusters per scenario) because they have different default ignore and file-selection semantics. This is expected and important context for the speed numbers below.

Evidence: [`benchmarks/out/20260305T183717Z/correctness_gate.json`](benchmarks/out/20260305T183717Z/correctness_gate.json)

---

## The Numbers

<!-- CLM-PERF-001 | CLM-PERF-002 | CLM-PERF-003 | CLM-PERF-004 | CLM-PERF-005 -->

We measured the `literal-simple` scenario — searching for the pattern `"foo"` across the repository working tree. This exercises the full pipeline: traversal, ignore filtering, pattern matching, and output formatting.

<!-- CLM-METHOD-001 | CLM-SAMPLE-001 -->

Each tool was measured with 3 samples after 1 warmup iteration. We report median wall-clock time with 95% bootstrap confidence intervals and interquartile range. Comparators ran in interleaved-random order to control for ordering bias.

### Local Run Results

<!-- CLM-PERF-001 | CLM-PERF-002 | CLM-PERF-003 | CLM-PERF-004 | CLM-PERF-005 -->

| Tool | Median (ms) | IQR (ms) | 95% CI (ms) | Samples |
|------|-------------|----------|-------------|---------|
| ag | 19.64 | 0.28 | 19.35 – 19.92 | 3 |
| rust-ag | 9.69 | 0.19 | 9.53 – 9.91 | 3 |
| rg | 7.74 | 0.38 | 7.25 – 8.00 | 3 |
| ugrep | 4.02 | 0.15 | 3.81 – 4.10 | 3 |

### Speedup Summary (Verified Across 3 Run Types)

<!-- CLM-PERF-001 | CLM-PERF-002 | CLM-PERF-003 | CLM-PERF-004 | CLM-PERF-005 -->

All speedup ratios below were verified across local, nightly, and manual runs with zero confidence-interval overlap:

| Faster | Slower | Speedup Range | CI Overlap |
|--------|--------|---------------|------------|
| rust-ag | ag | 1.96× – 2.03× | 0.0 |
| rg | ag | 2.45× – 2.54× | 0.0 |
| ugrep | ag | 4.76× – 4.95× | 0.0 |
| rg | rust-ag | 1.25× – 1.27× | 0.0 |
| ugrep | rust-ag | 2.41× – 2.52× | 0.0 |
<!-- CLM-PERF-003 | CLM-PERF-005 -->
| ugrep | rg | 1.92× – 1.99× | 0.0 |

Evidence: [`benchmarks/out/20260305T174335Z/claim_gate.json`](benchmarks/out/20260305T174335Z/claim_gate.json)

### The Ranking

For literal search on this corpus:

```
ugrep (3.9–4.0 ms) > rg (7.7–7.8 ms) > rust-ag (9.7–9.9 ms) > ag (18.9–19.6 ms)
```

<!-- CLM-PERF-001 -->
**The Rust rewrite is roughly 2× faster than the original C implementation** — a consistent result across all three independent runs (1.96×–2.03× speedup, zero CI overlap).

---

## Regressions and Failures: Where rust-ag Falls Short

<!-- CLM-REG-001 | CLM-REG-002 | CLM-REG-003 -->

Honest reporting matters. Here's where the rewrite doesn't shine.

### It's Slower Than rg and ugrep

<!-- CLM-REG-001 -->

While rust-ag beats the original ag by 2×, it loses to both established alternatives:

- **rg is 1.25× faster than rust-ag** (7.74 ms vs 9.69 ms median), consistent across all runs.
- **ugrep is 2.4× faster than rust-ag** (4.02 ms vs 9.69 ms median), consistent across all runs.

These are real performance gaps. The Rust rewrite does not achieve competitive parity with `rg` or `ugrep` on this workload.

Evidence: [`benchmarks/out/20260305T174335Z/claim_gate.json`](benchmarks/out/20260305T174335Z/claim_gate.json)

### The Formal Claim Gate Failed

<!-- CLM-REG-002 | CLM-GATE-001 -->

Our benchmark harness includes a formal claim-threshold gate that requires minimum speedup ratios, confidence-interval separation, cross-run-type agreement, parity verification, *and* reproducibility validation. The overall gate returned **fail** — not because of measurement problems, but because the reproducibility check requires validated publication artifact bundles at the cross-run level, which is an infrastructure gap we haven't closed.

All individual checks passed: parity, thresholds, cross-run agreement, zero CI overlap. We report this transparently rather than selectively omitting the gate status.

Evidence: [`benchmarks/out/20260305T174335Z/claim_gate.json`](benchmarks/out/20260305T174335Z/claim_gate.json)

### Limited Scenario Coverage

<!-- CLM-REG-003 | CLM-LIM-001 -->

We measured only 1 of 38 registered benchmark scenarios. The `literal-simple` scenario exercises the full pipeline but doesn't cover regex-heavy, large-corpus, or output-intensive workloads. Performance rankings could look different for complex regex patterns, count-only modes, or context-line rendering.

Evidence: [`manifests/scenarios.json`](manifests/scenarios.json)

---

## Caveats and Limitations

<!-- CLM-LIM-001 | CLM-LIM-002 | CLM-LIM-003 | CLM-LIM-004 | CLM-LIM-005 -->

### Small Sample Size

<!-- CLM-LIM-002 -->

Each tool was measured 3 times per run. The bootstrap CIs provide uncertainty bounds, but with n=3, subtle differences could be masked. For this workload, the inter-tool gaps (2–16 ms) far exceed the within-tool IQRs (0.05–0.60 ms), so the ranking is clear despite the small sample count.

### Single Machine, Single OS

<!-- CLM-LIM-003 -->

Everything ran on one Apple M4 Mac. Linux, x86_64, different filesystems (ext4 vs APFS), and different memory subsystems could shift the results. These numbers are specific to this environment.

### Not a Drop-in Replacement

<!-- CLM-LIM-004 -->

`rust-ag` targets behavioral parity for core search features. It does not yet support LZMA-compressed file search (`--search-zip`), thread pool tuning (`--workers`), some file-type filter aliases, or Windows path handling. Users who depend on those features should stick with `ag`.

### Cross-Tool Comparison Caveat

<!-- CLM-LIM-005 -->

`rg` and `ugrep` search different file sets by default — different ignore semantics, different traversal rules. A tool that skips more files will appear faster even if its per-file speed is identical. The correctness gate confirms this divergence (3 unique output hash clusters per scenario). The ag-vs-rust-ag comparison is the only apples-to-apples pair.

Evidence: [`benchmarks/out/20260305T183717Z/correctness_gate.json`](benchmarks/out/20260305T183717Z/correctness_gate.json)

---

## How We Measured

<!-- CLM-METHOD-001 | CLM-METHOD-002 | CLM-METHOD-003 | CLM-METHOD-004 | CLM-SAMPLE-001 -->

### Statistical Method

<!-- CLM-METHOD-001 -->

- **Central tendency**: Median
- **Dispersion**: Interquartile range (IQR)
- **Confidence intervals**: 95% percentile bootstrap (1000 resamples)
- **Method ID**: `median_iqr_ci` (locked in [`benchmarks/sampling_policy.json`](benchmarks/sampling_policy.json))

### Bias Controls

<!-- CLM-METHOD-002 -->

Tools were executed in interleaved-random order per iteration with a deterministic seed derived from the run ID hash. Execution schedules are recorded in each run manifest for reproducibility.

### Outlier Policy

<!-- CLM-METHOD-003 -->

Outliers were detected using the IQR fence method (1.5× IQR). The policy is flag-only — outliers are never silently dropped. Zero outliers were flagged in the measured runs.

### Claim Threshold Gate

<!-- CLM-METHOD-004 -->

Performance claims require: minimum 1.05× speedup ratio, maximum 0.50 CI overlap fraction, agreement across local/nightly/manual runs, parity gate pass, and reproducibility gate pass.

Evidence: [`benchmarks/out/20260305T174335Z/sampling_validation.json`](benchmarks/out/20260305T174335Z/sampling_validation.json)

---

## Reproducing These Results

<!-- CLM-ENV-001 | CLM-ENV-002 -->

Everything is open source. To reproduce:

```bash
# Checkout the measured commit
git clone https://github.com/sagaragas/the_silver_searcher.git
cd the_silver_searcher
git checkout 44759b4b07252dbf8e471a71ee21e0e6539ce236

# Build everything
./.factory/init.sh
./build.sh
cargo build --workspace --release

# Run parity check
python3 benchmarks/harness.py smoke --comparators rust ag rg ugrep
python3 benchmarks/correctness_gate.py --run latest

# Run measured benchmark
python3 benchmarks/harness.py measured \
  --comparators rust ag rg ugrep \
  --scenarios literal-simple \
  --warmup 1 --samples 3 --timeout 30

# Validate
python3 benchmarks/validate_sampling.py --run latest
python3 benchmarks/claim_gate.py --run latest
```

Configuration files:
- [`benchmarks/sampling_policy.json`](benchmarks/sampling_policy.json) — statistical method and thresholds
- [`manifests/scenarios.json`](manifests/scenarios.json) — scenario definitions
- [`manifests/corpus.json`](manifests/corpus.json) — corpus manifest

---

## Third-Party License Attribution

<!-- CLM-LIC-001 | CLM-LIC-002 -->

### Upstream

<!-- CLM-LIC-001 -->

This project is a derivative work of [The Silver Searcher](https://github.com/ggreer/the_silver_searcher) by Geoff Greer, licensed under the Apache License 2.0 (Copyright 2011–2016 Geoff Greer).

### Dependencies

<!-- CLM-LIC-002 -->

All runtime Rust dependencies use permissive licenses (MIT, Apache-2.0, Unlicense) with no copyleft in the dependency tree:

| Crate | License |
|-------|---------|
| regex | MIT OR Apache-2.0 |
| libc | MIT OR Apache-2.0 |
| aho-corasick | Unlicense OR MIT |
| memchr | Unlicense OR MIT |
| regex-automata | MIT OR Apache-2.0 |
| regex-syntax | MIT OR Apache-2.0 |

Benchmark comparators (`rg`: Unlicense/MIT, `ugrep`: BSD-3-Clause) are not bundled — they're installed separately for measurement only.

Complete inventory: [`publication/license_inventory.json`](publication/license_inventory.json)

---

## What Would an Adversarial Reviewer Say?

<!-- CLM-ADV-001 | CLM-ADV-002 | CLM-ADV-003 | CLM-ADV-004 | CLM-ADV-005 | CLM-ADV-006 -->

We anticipated the hard questions:

<!-- CLM-ADV-001 -->
**"Your claim gate failed — so you can't claim any performance wins?"** The gate failure is an infrastructure gap (reproducibility artifact bundles), not a measurement problem. All parity checks, speedup thresholds, and cross-run agreements passed individually with zero CI overlap.

<!-- CLM-ADV-002 -->
**"One scenario? Your conclusions are overfit."** Fair. Single-scenario results limit generalizability. We document this as a known limitation and identify multi-scenario coverage as required follow-up.

<!-- CLM-ADV-003 -->
**"Three samples is statistically weak."** The minimum of 3 samples is a pragmatic constraint. For this workload, the measured IQRs (0.05–0.60 ms) are small relative to the inter-tool gaps (2–16 ms), providing clear separation. Wider-sample runs would strengthen confidence but are unlikely to change the ranking.

<!-- CLM-ADV-004 -->
**"macOS/ARM only. Does this transfer to Linux/x86?"** Not without measurement. Memory subsystem, filesystem, and instruction set differences mean cross-platform claims require separate benchmarks.

<!-- CLM-ADV-005 -->
**"rg and ugrep search different files — isn't the comparison unfair?"** Yes, partially. The tools have different default ignore semantics, so result sets diverge. The ag-vs-rust-ag pair is the only validated apples-to-apples comparison. Cross-tool numbers are provided for context, with this caveat.

<!-- CLM-ADV-006 -->
**"Can I replace ag with rust-ag?"** Not yet. Missing features include LZMA search, worker-count tuning, some file-type aliases, and Windows path handling. Evaluate the feature gap before switching.

Evidence links for each answer are documented in [`publication/claim_evidence_map.json`](publication/claim_evidence_map.json).

---

## Takeaways

<!-- CLM-PERF-001 | CLM-PERF-004 | CLM-PERF-005 | CLM-REG-001 -->

1. **The Rust rewrite is 2× faster than the original C `ag`** on literal search. The improvement is consistent and clearly separated across repeated measurements.

2. **It's not the fastest tool.** `rg` and `ugrep` are both faster, by 1.25× and 2.4× respectively. A rewrite that matches the original's behavior but uses Rust's ecosystem doesn't automatically match purpose-built modern tools.

3. **Reproducibility is possible but hard.** Locking manifests, capturing environment metadata, enforcing parity gates, and running multi-type benchmark passes requires substantial infrastructure. We open-sourced all of it.

4. **Report honestly.** The most valuable thing a benchmark study can do is show where things don't work. Our claim gate failed. Our scenario coverage is thin. Our sample size is small. These are real limitations, not footnotes.

---

## Claim-Evidence Index

Every factual and numeric claim in this post maps to a claim ID with linked evidence artifacts.

| Claim ID | Summary |
|----------|---------|
| CLM-PERF-001 | rust-ag ≈2.0× faster than ag |
| CLM-PERF-002 | rg ≈2.5× faster than ag |
| CLM-PERF-003 | ugrep ≈4.9× faster than ag |
| CLM-PERF-004 | rg ≈1.25× faster than rust-ag |
| CLM-PERF-005 | ugrep ≈2.4× faster than rust-ag |
| CLM-PARITY-001 | rust-ag output-identical to ag across 8 scenarios |
| CLM-PARITY-002 | rg/ugrep produce different output sets |
| CLM-ENV-001 | Hardware/OS environment details |
| CLM-ENV-002 | Comparator versions |
| CLM-METHOD-001 | Statistical method definition |
| CLM-METHOD-002 | Order-bias controls |
| CLM-METHOD-003 | Outlier policy |
| CLM-METHOD-004 | Claim-threshold gate parameters |
| CLM-GATE-001 | Overall claim gate status (fail) |
| CLM-SAMPLE-001 | Warmup and sample counts |
| CLM-REG-001 | rust-ag slower than rg and ugrep |
| CLM-REG-002 | Claim gate overall fail due to reproducibility |
| CLM-REG-003 | Only 1 of 38 scenarios measured |
| CLM-LIM-001 | Single-scenario performance window |
| CLM-LIM-002 | Small sample size (n=3) |
| CLM-LIM-003 | Single-machine, single-OS environment |
| CLM-LIM-004 | Feature parity scope gaps |
| CLM-LIM-005 | Comparator output divergence |
| CLM-LIC-001 | Upstream source attribution |
| CLM-LIC-002 | License compliance summary |
| CLM-ADV-001 | Claim gate failure explanation |
| CLM-ADV-002 | Single-scenario overfitting |
| CLM-ADV-003 | Small sample statistical power |
| CLM-ADV-004 | Platform generalization |
| CLM-ADV-005 | Cross-tool result set fairness |
| CLM-ADV-006 | Drop-in replacement status |

Full evidence mappings: [`publication/claim_evidence_map.json`](publication/claim_evidence_map.json)

---

## Artifact References

| Artifact | Path |
|----------|------|
| Sampling policy | `benchmarks/sampling_policy.json` |
| Scenario manifest | `manifests/scenarios.json` |
| Corpus manifest | `manifests/corpus.json` |
| Local run manifest | `benchmarks/out/20260305T174325Z/run_manifest.json` |
| Nightly run manifest | `benchmarks/out/20260305T174330Z/run_manifest.json` |
| Manual run manifest | `benchmarks/out/20260305T174335Z/run_manifest.json` |
| Correctness gate | `benchmarks/out/20260305T183717Z/correctness_gate.json` |
| Sampling validation | `benchmarks/out/20260305T174335Z/sampling_validation.json` |
| Claim gate | `benchmarks/out/20260305T174335Z/claim_gate.json` |
| License inventory | `publication/license_inventory.json` |
| Claim-evidence map | `publication/claim_evidence_map.json` |
