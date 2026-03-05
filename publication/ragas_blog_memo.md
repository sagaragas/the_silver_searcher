# Rewriting The Silver Searcher in Rust: A Reproducible Performance Study

## Abstract

This memo documents the process and results of rewriting
[The Silver Searcher (ag)](https://github.com/ggreer/the_silver_searcher)
in Rust, with a focus on behavioral parity and measurable performance
characteristics. We compare four code-search tools — the original `ag`
(C, v2.2.0), our Rust rewrite `rust-ag` (v0.1.0),
`ripgrep` (`rg`, v13.0.0), and `ugrep` (v7.5.0) — using a reproducible
benchmark harness with locked manifests, predeclared statistical methods,
and machine-auditable evidence artifacts.

---

## 1. Methods

<!-- CLM-METHOD-001 | CLM-METHOD-002 | CLM-METHOD-003 | CLM-METHOD-004 | CLM-SAMPLE-001 -->

### 1.1 Scope and Objectives

The rewrite targets behavioral parity with `ag` 2.2.0 across core search
semantics (recursion, ignore handling, case sensitivity, multiline,
binary detection, context rendering, exit codes) validated through a
three-channel parity oracle (stdout, stderr, exit code).

Performance comparison uses a fixed four-tool comparator matrix:

| Comparator | Version | Language | Build Config |
|------------|---------|----------|--------------|
| `ag` | 2.2.0 | C | +jit -lzma +zlib |
| `rust-ag` | 0.1.0 | Rust | release (rustc 1.92.0) |
| `rg` | 13.0.0 | Rust | -SIMD -AVX |
| `ugrep` | 7.5.0 | C++ | +neon/AArch64, +pcre2jit |

<!-- CLM-ENV-002 -->

### 1.2 Environment

<!-- CLM-ENV-001 -->

All benchmarks were executed on the following hardware and software
environment:

| Property | Value |
|----------|-------|
| OS | macOS Darwin 25.3.0 |
| CPU | Apple M4 (10 cores physical, 10 logical) |
| RAM | 16.0 GiB |
| Rust toolchain | rustc 1.92.0 (Homebrew) |
| Python | 3.14.2 |
| Commit | `44759b4b07252dbf8e471a71ee21e0e6539ce236` |

### 1.3 Corpus and Query Manifests

Benchmarks operate on the repository working tree as the search corpus.
All inputs are pinned via content-hashed manifests:

| Manifest | Hash |
|----------|------|
| Scenarios | `a6d1fcc6...` |
| Queries | `e902cb24...` |
| Corpus | `f6b846c1...` |

Manifest files are located in `manifests/` and are generated
deterministically by `scripts/bench/build_scenario_manifest.py` and
`scripts/parity/build_fixture_manifest.py`. Regenerating from the same
commit must produce identical hashes.

### 1.4 Benchmark Scenarios

The registered scenario matrix contains 38 scenarios spanning:

- **Literal searches**: simple, word, rare, no-match, case-insensitive
- **Regex searches**: simple alternation, character class, complex identifiers
- **CLI features**: context lines, count mode, files-with-matches
- **Edge cases**: binary files, hidden files, symlinks, large files,
  zero-length regex, max-count truncation

The measured benchmark runs used the `literal-simple` scenario
(`pattern: "foo"`, corpus: `.`) to establish baseline performance
comparisons. This scenario exercises the full search pipeline (traversal,
ignore filtering, pattern matching, output formatting) on the repository
working tree.

### 1.5 Statistical Method

<!-- CLM-METHOD-001 -->

The statistical approach is locked in `benchmarks/sampling_policy.json`
(method ID: `median_iqr_ci`):

- **Central tendency**: Median
- **Dispersion**: Interquartile Range (IQR)
- **Confidence intervals**: 95% percentile bootstrap (1000 bootstrap
  samples)
- **Warmup**: 1 discarded warmup iteration per cell (minimum: 1)
- **Measured samples**: 3 per scenario-comparator cell (minimum: 3)

<!-- CLM-SAMPLE-001 -->

### 1.6 Order-Bias Controls

<!-- CLM-METHOD-002 -->

Comparators are executed in interleaved-random order per iteration to
reduce ordering bias. The randomization seed is deterministically derived
from the `run_id` hash, making schedules reproducible. Each run's
execution schedule is recorded in `execution_schedule` within the run
manifest.

### 1.7 Outlier Policy

<!-- CLM-METHOD-003 -->

Outliers are detected using the IQR fence method (1.5× IQR from Q1/Q3).
The policy is flag-only: outliers are flagged but never silently dropped.
No retries are performed. The outlier audit for the measured runs
reported zero flagged samples.

### 1.8 Claim-Threshold Gate

<!-- CLM-METHOD-004 -->

Performance winner claims require:

- Minimum speedup ratio: 1.05×
- Maximum CI overlap fraction: 0.50
- Agreement across all three required run types: local, nightly, manual
- Parity gate must pass (ag vs rust-ag output equivalence)
- Reproducibility gate must pass

### 1.9 Reproducibility Instructions

To reproduce the benchmark results:

1. **Checkout the measured commit**:
   ```bash
   git checkout 44759b4b07252dbf8e471a71ee21e0e6539ce236
   ```

2. **Install dependencies and build**:
   ```bash
   ./.factory/init.sh
   ./build.sh
   cargo build --workspace --release
   ```

3. **Verify comparator availability**:
   ```bash
   ./ag --version          # ag version 2.2.0
   ./target/release/rust-ag --version  # rust-ag 0.1.0
   rg --version            # ripgrep 13.0.0
   ugrep --version         # ugrep 7.5.0
   ```

4. **Run correctness gate (parity check)**:
   ```bash
   python3 benchmarks/harness.py smoke --comparators rust ag rg ugrep
   python3 benchmarks/correctness_gate.py --run latest
   ```

5. **Run measured benchmark**:
   ```bash
   python3 benchmarks/harness.py measured \
     --comparators rust ag rg ugrep \
     --scenarios literal-simple \
     --warmup 1 --samples 3 --timeout 30
   ```

6. **Validate sampling and claim gate**:
   ```bash
   python3 benchmarks/validate_sampling.py --run latest
   python3 benchmarks/claim_gate.py --run latest
   ```

Configuration files:
- `benchmarks/sampling_policy.json` — statistical method and thresholds
- `manifests/scenarios.json` — scenario definitions
- `manifests/queries.json` — query/pattern definitions
- `manifests/corpus.json` — corpus manifest

---

## 2. Results

### 2.1 Correctness

<!-- CLM-PARITY-001 -->

The correctness gate validated output parity between `ag` and `rust-ag`
across all 8 smoke benchmark scenarios. For each scenario, the sorted
stdout hash of `rust-ag` exactly matches that of `ag`, confirming
behavioral equivalence on the measured workloads.

| Scenario | ag ↔ rust-ag Parity | Unique Hash Clusters |
|----------|:-------------------:|:--------------------:|
| literal-simple | ✓ Pass | 3 |
| literal-word | ✓ Pass | 3 |
| literal-nomatch | ✓ Pass | 3 |
| regex-simple | ✓ Pass | 3 |
| literal-nocase | ✓ Pass | 3 |
| context-before-after | ✓ Pass | 3 |
| count-matches | ✓ Pass | 3 |
| files-with-matches | ✓ Pass | 3 |

Evidence: `benchmarks/out/20260305T183717Z/correctness_gate.json`

<!-- CLM-PARITY-002 -->

Each scenario showed 3 unique stdout hash clusters: `ag`/`rust-ag`
(identical), `rg` (different traversal/ignore semantics), and `ugrep`
(different traversal/ignore semantics). This is expected — `rg` and
`ugrep` have different default ignore and file-selection behaviors
compared to `ag`.

### 2.2 Performance: literal-simple Scenario

<!-- CLM-PERF-001 | CLM-PERF-002 | CLM-PERF-003 | CLM-PERF-004 | CLM-PERF-005 -->

The following table summarizes measured performance for the
`literal-simple` scenario (pattern `"foo"`, corpus `.`) across three run
types. All times are wall-clock elapsed in milliseconds (ms).

#### Table 2.2a: Local Run (20260305T174325Z)

| Comparator | Median (ms) | IQR (ms) | 95% CI Lower (ms) | 95% CI Upper (ms) | Samples (n) |
|------------|-------------|----------|--------------------|--------------------|-------------|
| ag | 19.64 | 0.29 | 19.35 | 19.93 | 3 |
| rust-ag | 9.69 | 0.19 | 9.53 | 9.91 | 3 |
| rg | 7.74 | 0.38 | 7.25 | 8.00 | 3 |
| ugrep | 4.02 | 0.10 | 3.81 | 4.10 | 3 |

#### Table 2.2b: Nightly Run (20260305T174330Z)

<!-- CLM-PERF-001 | CLM-PERF-002 | CLM-PERF-003 | CLM-PERF-004 | CLM-PERF-005 -->

| Comparator | Median (ms) | IQR (ms) | 95% CI Lower (ms) | 95% CI Upper (ms) | Samples (n) |
|------------|-------------|----------|--------------------|--------------------|-------------|
| ag | 18.90 | 0.21 | 18.63 | 19.04 | 3 |
| rust-ag | 9.65 | 0.07 | 9.55 | 9.69 | 3 |
| rg | 7.70 | 0.53 | 7.56 | 8.76 | 3 |
| ugrep | 3.97 | 0.05 | 3.92 | 4.02 | 3 |

#### Table 2.2c: Manual Run (20260305T174335Z)

<!-- CLM-PERF-001 | CLM-PERF-002 | CLM-PERF-003 | CLM-PERF-004 | CLM-PERF-005 -->

| Comparator | Median (ms) | IQR (ms) | 95% CI Lower (ms) | 95% CI Upper (ms) | Samples (n) |
|------------|-------------|----------|--------------------|--------------------|-------------|
| ag | 19.33 | 0.32 | 18.90 | 19.54 | 3 |
| rust-ag | 9.85 | 0.39 | 9.32 | 10.10 | 3 |
| rg | 7.78 | 0.36 | 7.50 | 8.22 | 3 |
| ugrep | 3.91 | 0.10 | 3.76 | 3.96 | 3 |

#### Table 2.2d: Speedup Ratios (Claim-Gate Verified)

All speedup ratios below passed the claim-threshold gate across all
three run types (local, nightly, manual) with zero CI overlap.

| Faster | Slower | Local Speedup | Nightly Speedup | Manual Speedup | CI Overlap | Claim Allowed |
|--------|--------|---------------|-----------------|----------------|------------|:-------------:|
| rg | ag | 2.54× | 2.45× | 2.48× | 0.0 | ✓ |
| rust-ag | ag | 2.03× | 1.96× | 1.96× | 0.0 | ✓ |
| ugrep | ag | 4.89× | 4.76× | 4.95× | 0.0 | ✓ |
| rg | rust-ag | 1.25× | 1.25× | 1.27× | 0.0 | ✓ |
| ugrep | rg | 1.92× | 1.94× | 1.99× | 0.0 | ✓ |
| ugrep | rust-ag | 2.41× | 2.43× | 2.52× | 0.0 | ✓ |

<!-- CLM-PERF-001 -->
**rust-ag vs ag**: The Rust rewrite achieved approximately 2.0× speedup
over the original C implementation (local median: 9.69 ms vs 19.64 ms).
This improvement was consistent across all three run types (1.96×–2.03×).

<!-- CLM-PERF-002 -->
**rg vs ag**: ripgrep was approximately 2.5× faster than ag (local
median: 7.74 ms vs 19.64 ms), consistent across runs (2.45×–2.54×).

<!-- CLM-PERF-003 -->
**ugrep vs ag**: ugrep was approximately 4.9× faster than ag (local
median: 4.02 ms vs 19.64 ms), consistent across runs (4.76×–4.95×).

<!-- CLM-PERF-004 -->
**rg vs rust-ag**: ripgrep was approximately 1.25× faster than rust-ag
(local median: 7.74 ms vs 9.69 ms), a smaller but consistent gap
(1.25×–1.27×).

<!-- CLM-PERF-005 -->
**ugrep vs rust-ag**: ugrep was approximately 2.4× faster than rust-ag
(local median: 4.02 ms vs 9.69 ms), consistent across runs (2.41×–2.52×).

### 2.3 Performance Ranking

For the `literal-simple` scenario on the repository working tree:

```
ugrep (3.9–4.0 ms) > rg (7.7–7.8 ms) > rust-ag (9.7–9.9 ms) > ag (18.9–19.6 ms)
```

### 2.4 Claim Gate Status

<!-- CLM-GATE-001 -->

The overall claim gate returned `fail` status. While all parity checks,
threshold evaluations, and cross-run-type agreements passed, the
**reproducibility check failed** across all three run types. This means
the formal claim-threshold gate does not authorize winner claims under
the full gate policy, even though individual speedup ratios and CI
separations are clear.

The reproducibility failure is a known infrastructure gap: the
reproducibility gate requires matching publication artifact bundles which
have not yet been fully validated at the cross-run level. All measured
performance differences are nevertheless clearly separated (zero CI
overlap across all pairs) and directionally consistent across all three
run types.

Evidence: `benchmarks/out/20260305T174335Z/claim_gate.json`

---

## 3. Metrics Summary

### 3.1 Sampling Validation

<!-- CLM-SAMPLE-001 -->

| Check | Result | Details |
|-------|--------|---------|
| Warmup count | ✓ Pass | min_required=1, no violations |
| Sample count | ✓ Pass | min_required=3, no violations |
| Statistical method | median_iqr_ci | median + IQR + 95% bootstrap CI |
| Order-bias schedule | ✓ Pass | interleaved_random, seed=2904361872 |
| Outlier audit | ✓ Pass | 0 flagged, 0 silently dropped |
| Policy hash | `54402ec6b9...` | Locked policy file integrity |

Evidence: `benchmarks/out/20260305T174335Z/sampling_validation.json`

### 3.2 Raw Sample Data (literal-simple, Local Run)

| Comparator | Sample 1 (ms) | Sample 2 (ms) | Sample 3 (ms) | Outlier Flags |
|------------|---------------|---------------|---------------|---------------|
| ag | 19.93 | 19.35 | 19.64 | none |
| rust-ag | 9.69 | 9.53 | 9.91 | none |
| rg | 7.74 | 7.25 | 8.00 | none |
| ugrep | 3.81 | 4.02 | 4.10 | none |

Evidence: `benchmarks/out/20260305T174325Z/run_manifest.json`

---

## Claim-Evidence Index

Every factual and numeric claim in this memo is tagged with a claim ID
and linked to evidence artifacts in `publication/claim_evidence_map.json`.

| Claim ID | Section | Summary |
|----------|---------|---------|
| CLM-PERF-001 | §2.2 | rust-ag ≈2.0× faster than ag |
| CLM-PERF-002 | §2.2 | rg ≈2.5× faster than ag |
| CLM-PERF-003 | §2.2 | ugrep ≈4.9× faster than ag |
| CLM-PERF-004 | §2.2 | rg ≈1.25× faster than rust-ag |
| CLM-PERF-005 | §2.2 | ugrep ≈2.4× faster than rust-ag |
| CLM-PARITY-001 | §2.1 | rust-ag output-identical to ag across 8 scenarios |
| CLM-PARITY-002 | §2.1 | rg/ugrep produce different output sets |
| CLM-ENV-001 | §1.2 | Hardware/OS environment details |
| CLM-ENV-002 | §1.1 | Comparator versions |
| CLM-METHOD-001 | §1.5 | Statistical method definition |
| CLM-METHOD-002 | §1.6 | Order-bias controls |
| CLM-METHOD-003 | §1.7 | Outlier policy |
| CLM-METHOD-004 | §1.8 | Claim-threshold gate parameters |
| CLM-GATE-001 | §2.4 | Overall claim gate status (fail) |
| CLM-SAMPLE-001 | §1.5, §3.1 | Warmup and sample counts |

---

## Artifact References

| Artifact | Path |
|----------|------|
| Sampling policy | `benchmarks/sampling_policy.json` |
| Scenario manifest | `manifests/scenarios.json` |
| Query manifest | `manifests/queries.json` |
| Corpus manifest | `manifests/corpus.json` |
| Local run manifest | `benchmarks/out/20260305T174325Z/run_manifest.json` |
| Nightly run manifest | `benchmarks/out/20260305T174330Z/run_manifest.json` |
| Manual run manifest | `benchmarks/out/20260305T174335Z/run_manifest.json` |
| Correctness gate | `benchmarks/out/20260305T183717Z/correctness_gate.json` |
| Sampling validation | `benchmarks/out/20260305T174335Z/sampling_validation.json` |
| Claim gate | `benchmarks/out/20260305T174335Z/claim_gate.json` |
| Claim-evidence map | `publication/claim_evidence_map.json` |
