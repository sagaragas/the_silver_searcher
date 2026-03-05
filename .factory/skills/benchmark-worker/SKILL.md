---
name: benchmark-worker
description: Builds and validates reproducible benchmark harnesses, CI benchmark workflows, and audit-grade performance artifacts.
---

# Benchmark Worker

NOTE: Startup and cleanup are handled by `worker-base`. This skill defines the WORK PROCEDURE.

## When to Use This Skill

Use for features in milestone `benchmark-harness`.

## Work Procedure

1. Read assigned feature plus `validation-contract.md` entries for `VAL-BENCH-*` and `VAL-CROSS-*` in scope.
2. Implement harness behavior test-first: schema tests, matrix completeness tests, and gate tests before runtime code.
3. Ensure command equivalence across `ag`, Rust rewrite, `rg`, and `ugrep` with explicit scenario manifests.
4. Capture immutable run metadata: commit SHA, corpus/query hashes, tool versions, environment snapshot.
5. Enforce sampling/warmup/order policy and outlier policy via machine-checked artifacts.
6. Run local smoke + required benchmark validator commands; update CI workflows for nightly + manual dispatch.
7. Emit raw/summary/checksum artifacts and verify publication manifest completeness.

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
