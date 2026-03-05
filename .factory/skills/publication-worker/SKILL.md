---
name: publication-worker
description: Produces public, evidence-linked technical publication outputs with licensing compliance and anti-fluff quality gates.
---

# Publication Worker

NOTE: Startup and cleanup are handled by `worker-base`. This skill defines the WORK PROCEDURE.

## When to Use This Skill

Use for features in milestone `performance-memo` and for publication/license packaging work.

## Work Procedure

1. Read publication-related assertions (`VAL-PUB-*`, `VAL-CROSS-*`) and collect benchmark/parity artifacts first.
2. Build claim-evidence map before drafting narrative sections; every numeric claim must have artifact linkage.
3. Draft/update memo sections (methods, results, regressions, limitations, licensing, adversarial Q&A) from artifacts only.
4. Generate publication-gate outputs: numeric-claim audit, specificity/style checks, reconciliation report.
5. Ensure public fork publication package includes referenced scripts/manifests/checksums and traceable commit SHA.
6. Run required validators and publication checks from `.factory/services.yaml`.

## Example Handoff

```json
{
  "salientSummary": "Produced memo package and claim-evidence map with full artifact reconciliation and license disclosures.",
  "whatWasImplemented": "Added long-form performance memo draft for ragas.dev/blogs, generated claim-evidence mapping, linked regression/limitation artifacts, and enforced publication gate checks for unsupported numeric claims.",
  "whatWasLeftUndone": "",
  "verification": {
    "commandsRun": [
      {
        "command": "python3 publication/check_claims.py --memo publication/ragas_blog_memo.md",
        "exitCode": 0,
        "observation": "All numeric claims mapped to evidence IDs"
      },
      {
        "command": "python3 publication/reconcile_metrics.py --memo publication/ragas_blog_memo.md --summary benchmarks/out/latest/summary.json",
        "exitCode": 0,
        "observation": "No unresolved value diffs"
      },
      {
        "command": "python3 publication/license_audit.py",
        "exitCode": 0,
        "observation": "All third-party entries attributed"
      }
    ],
    "interactiveChecks": [
      {
        "action": "Open memo and verify every table/claim references evidence IDs",
        "observed": "Methods, regressions, and limitations sections are evidence-linked"
      }
    ]
  },
  "tests": {
    "added": [
      {
        "file": "publication/tests/test_claim_map.py",
        "cases": [
          {
            "name": "all_claims_have_ids",
            "verifies": "VAL-PUB-002"
          },
          {
            "name": "memo_artifact_reconciliation",
            "verifies": "VAL-CROSS-003"
          }
        ]
      }
    ]
  },
  "discoveredIssues": []
}
```

## When to Return to Orchestrator

- Required benchmark artifacts are missing for mandatory publication claims.
- License/provenance ambiguity cannot be resolved from repository history and manifests.
- Public publication target expectations change materially (format/scope) and require new mission scope decisions.
