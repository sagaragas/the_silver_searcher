---
name: rewrite-worker
description: Implements baseline fixtures, Rust search engine behavior, and CLI parity for the Silver Searcher rewrite using strict test-first workflow.
---

# Rewrite Worker

NOTE: Startup and cleanup are handled by `worker-base`. This skill defines the WORK PROCEDURE.

## When to Use This Skill

Use for features in milestones `baseline-and-fixtures`, `rust-search-core`, and `rust-cli-parity`.

## Work Procedure

1. Read `mission.md`, `AGENTS.md`, `validation-contract.md`, and the assigned feature details before touching code.
2. Reproduce baseline behavior with `ag` for the feature scope and store fixture/output artifacts first.
3. Add or update failing tests first (red): parity tests, fixture checks, and command-matrix assertions.
4. Implement Rust changes to make tests pass (green), matching baseline behavior and repository style.
5. Run scoped checks during iteration, then run full required validators from `.factory/services.yaml` commands.
6. Run manual CLI verification for assigned flows (command + observed output + exit code) and capture artifacts.
7. Confirm no leftover temporary processes/files outside expected artifact paths.

## Example Handoff

```json
{
  "salientSummary": "Implemented Rust ignore and recursion semantics with parity fixtures; all scoped and full validators passed.",
  "whatWasImplemented": "Added fixture-driven parity tests for default ignore, -U behavior, and recursion depth. Implemented Rust traversal/ignore logic to match baseline ag behavior including hidden and constrained traversal paths.",
  "whatWasLeftUndone": "",
  "verification": {
    "commandsRun": [
      {
        "command": "cargo test -p rust-ag parity_ignore_matrix",
        "exitCode": 0,
        "observation": "6 parity cases passed"
      },
      {
        "command": "python3 scripts/parity/run_matrix.py --group core-ignore",
        "exitCode": 0,
        "observation": "No output diffs; manifest hashes recorded"
      },
      {
        "command": "make -C . test",
        "exitCode": 0,
        "observation": "Upstream baseline checks still passing"
      }
    ],
    "interactiveChecks": [
      {
        "action": "Run rust binary and baseline ag on fixture with default and -U flags",
        "observed": "stdout/stderr and exit codes match after normalization"
      }
    ]
  },
  "tests": {
    "added": [
      {
        "file": "rust-ag/tests/parity_ignore.rs",
        "cases": [
          {
            "name": "default_ignore_matrix",
            "verifies": "VAL-CORE-002"
          },
          {
            "name": "u_flag_matrix",
            "verifies": "VAL-CORE-003"
          }
        ]
      }
    ]
  },
  "discoveredIssues": []
}
```

## When to Return to Orchestrator

- Baseline behavior is ambiguous or contradictory across docs/tests for the same flag.
- Feature requires decisions that change CLI contract beyond approved scope.
- Required comparator/tooling is unavailable and cannot be restored inside mission boundaries.
