---
name: benchmark-worker
description: Builds and validates reproducible benchmark harnesses, CI benchmark workflows, and audit-grade performance artifacts.
---

# Benchmark Worker

NOTE: Startup and cleanup are handled by `worker-base`. This skill defines the WORK PROCEDURE.

## When to Use This Skill

Use for features in milestone `benchmark-harness` and related benchmark hardening/follow-up milestones (e.g., `misc-ops-hardening`, `misc-performance-followup`).

## Work Procedure

1. Read assigned feature plus `validation-contract.md` entries for `VAL-BENCH-*` and `VAL-CROSS-*` in scope.
2. Implement harness behavior test-first: schema tests, matrix completeness tests, and gate tests before runtime code.
3. Ensure command equivalence across `ag`, Rust rewrite, `rg`, and `ugrep` with explicit scenario manifests.
   - **Comparator completeness policy:** Each benchmark scenario must define and execute the full required comparator set (`ag`, `rust-ag`, `rg`, `ugrep`). Missing comparator command templates or cells are always blocking failures — never skip or mark as advisory.
4. Capture immutable run metadata: commit SHA, corpus/query hashes, tool versions, environment snapshot.
5. Enforce sampling/warmup/order policy and outlier policy via machine-checked artifacts.
6. **Correctness gate enforcement:**
   - `ag` vs `rust-ag` parity divergence is a **hard failure**; cross-tool (`rg`/`ugrep`) hash differences are advisory and do not fail the gate by themselves.
   - When correctness gate fails, harness CLI modes (`smoke`, `run`, `measured`) must exit non-zero even if scenario cell execution itself reports zero errors.
   - Include explicit **fail-state propagation tests** that verify non-zero CLI exit codes when correctness gate fails.
7. Run local smoke + required benchmark validator commands; update CI workflows for nightly + manual dispatch.
8. Emit raw/summary/checksum artifacts and verify publication manifest completeness.
   - Include **negative-path tests** for publication gating controls: verify that missing `REQUIRED_RAW_ARTIFACTS` and tampered/partial checksum maps cause hard failures, not warnings.

## Example Handoff

```json
{
  "salientSummary": "Implemented benchmark manifest pipeline and claim gate checks; local smoke and CI config validation passed.",
  "whatWasImplemented": "Added benchmark scenario/command expansion, run metadata capture, sample aggregation, and claim-threshold gating with reproducibility reports across local and CI metadata schemas.",
  "whatWasLeftUndone": "",
  "verification": {
    "commandsRun": [
      {
        "command": "python3 benchmarks/harness.py smoke --comparators ag rust rg ugrep",
        "exitCode": 0,
        "observation": "All comparator cells executed"
      },
      {
        "command": "python3 benchmarks/validate_artifacts.py --run latest",
        "exitCode": 0,
        "observation": "Schema and checksum validation passed"
      },
      {
        "command": "python3 benchmarks/claim_gate.py --run latest",
        "exitCode": 0,
        "observation": "Claim gate report generated with local/nightly/manual links placeholder checks"
      }
    ],
    "interactiveChecks": [
      {
        "action": "Inspect generated run manifest and scenario matrix coverage",
        "observed": "No missing scenario-comparator cells"
      }
    ]
  },
  "tests": {
    "added": [
      {
        "file": "benchmarks/tests/test_manifest_integrity.py",
        "cases": [
          {
            "name": "matrix_complete",
            "verifies": "VAL-BENCH-001"
          },
          {
            "name": "scenario_equivalence",
            "verifies": "VAL-BENCH-009"
          }
        ]
      }
    ]
  },
  "discoveredIssues": []
}
```

## When to Return to Orchestrator

- Comparator binaries cannot be installed/used within approved mission boundaries.
- CI constraints prevent required nightly/manual benchmark execution policy.
- Statistical policy requirements conflict with mission-approved claim thresholds.
