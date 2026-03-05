---
name: rewrite-worker
description: Implements baseline fixtures/tooling plus Rust search engine and CLI parity behavior using strict test-first workflow.
---

# Rewrite Worker

NOTE: Startup and cleanup are handled by `worker-base`. This skill defines the WORK PROCEDURE.

## When to Use This Skill

Use for features in milestones `baseline-and-fixtures`, `rust-search-core`, `rust-cli-parity`, and related hardening/follow-up milestones (e.g., `misc-ops-hardening`, `misc-performance-followup`).
This includes Python/parity-tooling hardening features, manifest/fixture regeneration, and script changes — not only Rust source changes.

## Work Procedure

### Common Steps (all feature types)

1. Read `mission.md`, `AGENTS.md`, `validation-contract.md`, and the assigned feature details before touching code.
2. Reproduce baseline behavior with `ag` for the feature scope and store fixture/output artifacts first.

### Rust Code Features

3. Add or update failing tests first (red): parity tests, fixture checks, and command-matrix assertions.
4. Implement changes to make tests pass (green), matching baseline behavior and repository style.

### Tooling / Script / Manifest Features

3. For tooling-focused features (Python scripts, manifests, fixture regeneration), the strict red-first test cycle may not apply literally. Instead:
   - When a failing test can be written before the change (e.g., a new validation check, a regression guard), write it first.
   - When the feature is regeneration-only or manifest sync work where a pre-existing test already covers correctness, running the scoped validator before and after the change is acceptable in place of a new red test.
   - Always include direct unit tests or command-transcript evidence that the exact regression path is fixed.
   - For argv/tokenization or escaping-related changes, include edge-case regression tests covering shell/regex escaping semantics (backslashes, quoted arguments, `{pattern}` placeholder expansion).
4. Implement the tooling change and verify with scoped validators.

### Shared Finalization Steps

5. Run scoped checks during iteration, then run full required validators from `.factory/services.yaml` commands.
6. Run manual CLI verification for assigned flows (command + observed output + exit code) and capture artifacts.
7. For tooling-focused features, include direct unit tests plus command-transcript evidence that the exact regression path is fixed.
8. Confirm no leftover temporary processes/files outside expected artifact paths.

### Procedure Compliance Evidence

When reporting `followedProcedure` in skill feedback, evaluate compliance against the feature type (Rust code vs tooling/manifests). Claiming `followedProcedure: true` requires that transcript ordering evidence shows tests or scoped validators ran before or alongside implementation edits — not only after.

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
