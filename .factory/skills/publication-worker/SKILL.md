---
name: publication-worker
description: Produces public, evidence-linked technical publication outputs with licensing compliance and anti-fluff quality gates.
---

# Publication Worker

NOTE: Startup and cleanup are handled by `worker-base`. This skill defines the WORK PROCEDURE.

## When to Use This Skill

Use for features in milestone `performance-memo` and for publication/license packaging work, including related follow-up milestones (e.g., `misc-performance-followup`, `blog-release`, `misc-blog-polish`).

## Work Procedure

1. Read publication-related assertions (`VAL-PUB-*`, `VAL-CROSS-*`) and collect benchmark/parity artifacts first.
2. Build claim-evidence map before drafting narrative sections; every numeric claim must have artifact linkage.
   - **Uncertainty source:** Use `benchmarks/out/<run>/sampling_validation.json` as the authoritative source for all uncertainty stats (IQR/CI) in memo and Q&A claims. Do not hand-enter uncertainty values; extract them programmatically from the artifact.
3. Draft/update memo sections (methods, results, regressions, limitations, licensing, adversarial Q&A) from artifacts only.
4. **License inventory sequencing:** Generate or update `publication/license_inventory.json` **before** running `publication/license_audit.py`. The audit must fail fast when the inventory is missing or stale. This is a hard prerequisite — do not run the audit without a current inventory.
5. Generate publication-gate outputs: numeric-claim audit, specificity/style checks, reconciliation report.
6. **Commit-lineage traceability:** Enforce strict equality between the commit SHA cited in the memo, the parity evidence commit SHA, and the benchmark evidence commit SHA. All three must resolve to the same commit. Publication traceability checks must hard-fail on any mismatch — no fallback to unresolved `parity_run_ids`.
7. **Clean-checkout smoke reproducibility:** Execute a clean-checkout smoke reproducibility run against an actual isolated-worktree checkout/clone of the cited commit — not just commit existence verification plus current-tree execution. The clean-checkout evidence artifact (`publication/clean_checkout_reproducibility.json`) must include:
   - `schema_version` field
   - `requested_commit_sha` and `checked_out_commit_sha` (must be equal to the memo-cited publication commit SHA)
   - `execution_context` must be `isolated_worktree`
   - All checks in the artifact must pass
8. Ensure public fork publication package includes referenced scripts/manifests/checksums and traceable commit SHA.
9. Run required validators and publication checks from `.factory/services.yaml`.

   ### Validation scope rules by task type

   **Full publication gate suite is mandatory** for tasks that create or alter publication content with claim, evidence, or license implications. The full suite is: `publication_gate`, `publication_reconcile`, `publication_style_gate`, `publication_license_audit`, `publication_traceability`. This includes:
   - New memo drafts or material revisions to claim content, evidence linkage, or metrics tables in `ragas_blog_memo.md`
   - New or updated claim-evidence maps, license inventories, or traceability artifacts
   - Changes that add, remove, or modify numeric/factual claims in any publication output

   **Blog-draft and derivative-output tasks may use scoped validation** when the underlying memo and evidence artifacts are already validated and unchanged. A blog-draft derived from a validated memo (e.g., `ragas_dev_blog_draft.md`) does not re-introduce claims or evidence linkage — it adapts existing validated content for a different audience. Scoped validation for blog-draft tasks includes:
   - `publication_gate` and `publication_style_gate` (against the source memo, to confirm the memo remains clean)
   - Manual review of the blog draft for faithful alignment with the validated memo
   - `publication_reconcile`, `publication_license_audit`, and `publication_traceability` may be omitted **only if** the memo, claim-evidence map, license inventory, and traceability artifacts are unmodified from their last full-suite-validated state

   **Polish-only tasks** (prose rewording, formatting, help-text edits, or typo fixes that do not alter claims, evidence, or metrics) may use the narrowest scoped run limited to the directly affected check (e.g., running only `publication_style_gate` after a prose cleanup, or only `publication_reconcile` after a tolerance-related change).

   **Skill or tooling documentation changes** (e.g., updating `SKILL.md`, scripts, or non-publication configuration) do not require publication validators, since they do not touch publication content or artifacts.

   ### Deviation logging requirement

   When a reduced (scoped) validator set is used instead of the full gate suite, the worker **must** record the scope decision in the `EndFeatureRun` handoff. This applies to blog-draft scoped runs, polish-only runs, and any other non-full-suite validation. The record must include:
   - **Which validators were run** and their results
   - **Which validators were skipped** from the full suite
   - **Why the scoped run was sufficient** (e.g., "blog draft derived from unchanged validated memo; no new claims or evidence linkage")
   - This information must appear in `skillFeedback.deviations` (with `step` referencing "Step 9 — validation scope") **and** in `verification.commandsRun` (listing only the validators actually executed)

   Omitting this deviation record when a scoped run was used is a handoff quality failure.

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
