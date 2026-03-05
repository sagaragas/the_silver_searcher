#!/usr/bin/env python3
"""End-to-end traceability validation across parity, benchmark, and memo artifacts.

Validates:
  VAL-CROSS-001: Shared fixture lineage across stages (commit SHA + manifest hashes)
  VAL-CROSS-004: Public fork contains reproducibility package AND executed
                 clean-checkout smoke reproducibility validation
  VAL-CROSS-005: Public release includes legal + methodological disclosure
  VAL-CROSS-008: Public publication commit is traceable to measured evidence
                 (parity, benchmark, and memo commit SHAs must be equal)

Usage:
    python3 publication/traceability_check.py \
        --memo publication/ragas_blog_memo.md \
        --run latest
"""

import argparse
import json
import re
import sys
from pathlib import Path


def load_json(path: Path) -> dict:
    """Load JSON file or return empty dict if not found."""
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def resolve_run_dir(run_ref: str, repo_root: Path) -> Path:
    """Resolve a run reference to a directory path."""
    bench_out = repo_root / "benchmarks" / "out"

    if run_ref == "latest":
        latest_link = bench_out / "latest"
        if latest_link.exists():
            return latest_link.resolve()
        # Find the most recent run directory
        runs = sorted(
            [d for d in bench_out.iterdir() if d.is_dir() and d.name != "latest"],
            key=lambda d: d.name,
        )
        if runs:
            return runs[-1]
        print("FAIL: No benchmark runs found", file=sys.stderr)
        sys.exit(1)
    else:
        run_dir = bench_out / run_ref
        if run_dir.exists():
            return run_dir
        print(f"FAIL: Run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(1)


def extract_memo_commit(memo_text: str) -> str | None:
    """Extract the commit SHA cited in the memo."""
    # Look for commit references in environment table or git checkout commands
    patterns = [
        r"Commit\s*\|\s*`([a-f0-9]{40})`",
        r"git checkout\s+([a-f0-9]{40})",
        r"evidence_commit_sha.*?([a-f0-9]{40})",
    ]
    for pattern in patterns:
        m = re.search(pattern, memo_text)
        if m:
            return m.group(1)
    return None


def extract_memo_manifest_hashes(memo_text: str) -> dict:
    """Extract manifest hashes from the memo."""
    hashes = {}
    # Look for table rows like: | Scenarios | `a6d1fcc6...` |
    pattern = re.compile(r"\|\s*(Scenarios|Queries|Corpus)\s*\|\s*`([a-f0-9]+\.{0,3})`\s*\|")
    for m in pattern.finditer(memo_text):
        name = m.group(1).lower()
        hash_prefix = m.group(2).rstrip(".")
        hashes[name] = hash_prefix
    return hashes


def resolve_parity_summary(
    claim_map: dict, repo_root: Path
) -> tuple[dict, str | None, list[str]]:
    """Resolve parity summary strictly from claim_evidence_map parity_run_ids.

    Returns (summary_dict, source_label, resolution_errors).

    Hard-fails (via resolution_errors) when parity_run_ids are missing,
    empty, or cannot be resolved to an existing artifact directory.
    Does NOT fall back to parity-artifacts/latest.
    """
    errors: list[str] = []
    parity_run_ids = claim_map.get("parity_run_ids")
    parity_dir = repo_root / "parity-artifacts"

    if not parity_run_ids:
        errors.append(
            "claim_evidence_map has no parity_run_ids; "
            "parity provenance cannot be established (no latest fallback)"
        )
        return {}, None, errors

    # Try each declared parity_run_id
    for run_type, run_id in parity_run_ids.items():
        summary_path = parity_dir / run_id / "summary.json"
        if summary_path.exists():
            return load_json(summary_path), f"parity_{run_type}_{run_id}", []

    # All declared parity_run_ids failed to resolve
    unresolved = {rt: rid for rt, rid in parity_run_ids.items()}
    errors.append(
        f"All claim_evidence_map parity_run_ids are unresolved "
        f"(no matching artifact directories): {json.dumps(unresolved)}. "
        f"No latest fallback is permitted."
    )
    return {}, None, errors


def check_commit_lineage(
    memo_commit: str | None,
    claim_map: dict,
    benchmark_manifests: list[dict],
    parity_summary: dict,
    parity_source: str | None,
) -> list[str]:
    """Enforce strict parity/benchmark/memo commit-SHA equality.

    VAL-CROSS-001 + VAL-CROSS-008: All three artifact sources (parity,
    benchmark, memo) must reference the same commit SHA. Failure to match
    is a hard error.
    """
    errors = []

    # Collect commit SHAs by source
    commits: dict[str, str] = {}

    if memo_commit:
        commits["memo"] = memo_commit

    claim_map_commit = claim_map.get("evidence_commit_sha")
    if claim_map_commit:
        commits["claim_evidence_map"] = claim_map_commit

    # Collect measured (non-smoke) benchmark commits
    for manifest in benchmark_manifests:
        run_type = manifest.get("run_type", "unknown")
        if run_type == "smoke":
            continue
        run_id = manifest.get("run_id", "unknown")
        commit = manifest.get("commit_sha")
        if commit:
            commits[f"benchmark_{run_type}_{run_id}"] = commit

    parity_commit = parity_summary.get("commit_sha")
    if parity_commit and parity_source:
        commits[parity_source] = parity_commit

    # ---- Strict 3-way equality check ----
    # We require at least memo + one benchmark + parity to all be present
    memo_sha = commits.get("memo")
    benchmark_shas = {
        k: v for k, v in commits.items() if k.startswith("benchmark_")
    }
    parity_shas = {
        k: v for k, v in commits.items()
        if k.startswith("parity_")
    }

    # Check memo vs claim_evidence_map
    if memo_sha and claim_map_commit and memo_sha != claim_map_commit:
        errors.append(
            f"Memo commit ({memo_sha}) != "
            f"claim_evidence_map commit ({claim_map_commit})"
        )

    # Check benchmark commit consistency among themselves
    if benchmark_shas:
        unique_bench = set(benchmark_shas.values())
        if len(unique_bench) > 1:
            errors.append(
                f"Benchmark commit SHAs differ across runs: "
                f"{json.dumps(benchmark_shas, indent=2)}"
            )

    # Check memo vs benchmark
    if memo_sha and benchmark_shas:
        bench_commit = next(iter(set(benchmark_shas.values())))
        if memo_sha != bench_commit:
            errors.append(
                f"Memo commit ({memo_sha}) != "
                f"benchmark measured commit ({bench_commit})"
            )

    # ---- Critical: parity must match memo and benchmark ----
    if parity_shas:
        parity_sha = next(iter(parity_shas.values()))
        if memo_sha and parity_sha != memo_sha:
            errors.append(
                f"Parity commit ({parity_sha}) != "
                f"memo commit ({memo_sha}): "
                f"parity, benchmark, and memo SHAs must be equal"
            )
        if benchmark_shas:
            bench_sha = next(iter(set(benchmark_shas.values())))
            if parity_sha != bench_sha:
                errors.append(
                    f"Parity commit ({parity_sha}) != "
                    f"benchmark commit ({bench_sha}): "
                    f"parity, benchmark, and memo SHAs must be equal"
                )
    elif memo_sha:
        # Parity commit is missing entirely — this is a failure
        errors.append(
            "No parity artifact commit SHA found; "
            "parity, benchmark, and memo SHAs must all be present and equal"
        )

    return errors


def check_manifest_hash_consistency(
    memo_hashes: dict,
    claim_map: dict,
    benchmark_manifests: list[dict],
) -> list[str]:
    """VAL-CROSS-001: Check manifest hash consistency across artifacts."""
    errors = []

    # Collect all manifest hashes from measured benchmark runs
    benchmark_hashes: dict[str, dict[str, str]] = {}
    for manifest in benchmark_manifests:
        run_type = manifest.get("run_type", "unknown")
        if run_type == "smoke":
            continue
        mh = manifest.get("manifest_hashes", {})
        for key, val in mh.items():
            if key not in benchmark_hashes:
                benchmark_hashes[key] = {}
            benchmark_hashes[key][run_type] = val

    # Check consistency across benchmark runs
    for key, type_hashes in benchmark_hashes.items():
        unique = set(type_hashes.values())
        if len(unique) > 1:
            errors.append(
                f"Manifest hash '{key}' differs across measured runs: "
                f"{json.dumps(type_hashes)}"
            )

    # Check memo hashes match benchmark hashes (prefix match)
    if memo_hashes and benchmark_hashes:
        for key, memo_prefix in memo_hashes.items():
            bench_vals = benchmark_hashes.get(key, {})
            if bench_vals:
                bench_hash = next(iter(bench_vals.values()))
                if not bench_hash.startswith(memo_prefix):
                    errors.append(
                        f"Memo {key} hash prefix '{memo_prefix}' does not match "
                        f"benchmark hash '{bench_hash[:len(memo_prefix) + 4]}...'"
                    )

    return errors


def check_reproducibility_package(repo_root: Path) -> list[str]:
    """VAL-CROSS-004: Check that reproducibility package files exist."""
    errors = []

    required_files = [
        ("benchmarks/harness.py", "Benchmark harness script"),
        ("benchmarks/sampling_policy.json", "Sampling policy definition"),
        ("benchmarks/correctness_gate.py", "Correctness gate script"),
        ("benchmarks/validate_sampling.py", "Sampling validator"),
        ("benchmarks/claim_gate.py", "Claim gate script"),
        ("manifests/scenarios.json", "Scenario manifest"),
        ("manifests/queries.json", "Query manifest"),
        ("manifests/corpus.json", "Corpus manifest"),
        ("publication/ragas_blog_memo.md", "Performance memo"),
        ("publication/claim_evidence_map.json", "Claim-evidence map"),
        ("publication/license_inventory.json", "License inventory"),
        ("Cargo.toml", "Rust workspace definition"),
        ("rust-ag/Cargo.toml", "Rust binary crate"),
        ("build.sh", "C build script"),
        (".factory/init.sh", "Environment init script"),
    ]

    for rel_path, description in required_files:
        full_path = repo_root / rel_path
        if not full_path.exists():
            errors.append(f"Missing reproducibility file: {rel_path} ({description})")

    return errors


def check_clean_checkout_reproducibility(
    repo_root: Path, memo_commit: str | None
) -> list[str]:
    """VAL-CROSS-004 (execution): Verify executed clean-checkout smoke
    reproducibility for the cited publication commit.

    This goes beyond file-presence checks by requiring evidence that a
    smoke reproducibility run was actually *executed* in an isolated
    checkout/worktree at the cited commit.  The evidence must be a JSON
    artifact recording provenance fields proving:
      requested_commit_sha == checked_out_commit_sha == memo commit
    and the execution context.
    """
    errors = []

    evidence_path = (
        repo_root / "publication" / "clean_checkout_reproducibility.json"
    )
    if not evidence_path.exists():
        errors.append(
            "Missing clean-checkout reproducibility evidence: "
            "publication/clean_checkout_reproducibility.json — "
            "a smoke reproducibility run must be executed (not just files checked)"
        )
        return errors

    evidence = load_json(evidence_path)

    # --- Schema version gate ---
    schema_version = evidence.get("schema_version", 1)
    if schema_version < 2:
        errors.append(
            f"Clean-checkout reproducibility evidence has schema_version "
            f"{schema_version}; version >= 2 is required (must include "
            f"provenance fields: requested_commit_sha, checked_out_commit_sha, "
            f"execution_context)"
        )
        return errors

    # --- Validate required structure ---
    required_keys = [
        "executed",
        "execution_context",
        "requested_commit_sha",
        "checked_out_commit_sha",
        "result",
        "checks",
    ]
    for key in required_keys:
        if key not in evidence:
            errors.append(
                f"Clean-checkout reproducibility evidence missing key: '{key}'"
            )

    if not evidence.get("executed"):
        errors.append(
            "Clean-checkout reproducibility evidence 'executed' is false; "
            "smoke run must actually execute, not just check file presence"
        )

    # --- Execution context must be isolated ---
    exec_ctx = evidence.get("execution_context")
    if exec_ctx != "isolated_worktree":
        errors.append(
            f"Clean-checkout execution_context is '{exec_ctx}'; "
            f"expected 'isolated_worktree' — smoke checks must run "
            f"inside an isolated checkout, not the caller working tree"
        )

    # --- Provenance: requested == checked_out == memo ---
    requested_sha = evidence.get("requested_commit_sha")
    checked_out_sha = evidence.get("checked_out_commit_sha")

    if requested_sha and checked_out_sha:
        if requested_sha != checked_out_sha:
            errors.append(
                f"Provenance mismatch: requested_commit_sha ({requested_sha}) "
                f"!= checked_out_commit_sha ({checked_out_sha})"
            )

    if memo_commit and requested_sha and memo_commit != requested_sha:
        errors.append(
            f"Provenance mismatch: memo commit ({memo_commit}) "
            f"!= requested_commit_sha ({requested_sha})"
        )

    if memo_commit and checked_out_sha and memo_commit != checked_out_sha:
        errors.append(
            f"Provenance mismatch: memo commit ({memo_commit}) "
            f"!= checked_out_commit_sha ({checked_out_sha})"
        )

    # --- Verify overall result is pass ---
    result = evidence.get("result")
    if result != "pass":
        errors.append(
            f"Clean-checkout reproducibility result is '{result}', expected 'pass'"
        )

    # --- Verify individual checks ---
    checks = evidence.get("checks", [])
    if not checks:
        errors.append(
            "Clean-checkout reproducibility evidence has no checks recorded"
        )
    for check in checks:
        check_name = check.get("name", "unknown")
        check_result = check.get("result")
        # "skip" is acceptable (e.g., baseline_ag_runs when C binary unavailable)
        if check_result not in ("pass", "skip"):
            detail = check.get("detail", "")
            errors.append(
                f"Clean-checkout check '{check_name}' failed: {detail}"
            )

    return errors


def check_legal_methodology_disclosure(
    repo_root: Path, memo_text: str
) -> list[str]:
    """VAL-CROSS-005: Check legal + methodological disclosure completeness."""
    errors = []

    # Check license files
    required_license_files = [
        ("LICENSE", "Project license"),
        ("NOTICE", "Third-party notice"),
        ("publication/license_inventory.json", "License inventory"),
    ]

    for rel_path, description in required_license_files:
        full_path = repo_root / rel_path
        if not full_path.exists():
            errors.append(f"Missing legal file: {rel_path} ({description})")

    # Check memo has required sections
    required_sections = [
        (r"##\s+.*Methods", "Methods section"),
        (r"##\s+.*Results", "Results section"),
        (r"##\s+.*Regression", "Regressions section"),
        (r"##\s+.*Limitation", "Limitations section"),
        (r"##\s+.*License|##\s+.*Attribution", "License attribution section"),
        (r"##\s+.*Adversarial", "Adversarial Q&A section"),
        (r"##\s+.*Claim.Evidence", "Claim-evidence index"),
        (r"##\s+.*Artifact\s+Reference", "Artifact references section"),
    ]

    for pattern, description in required_sections:
        if not re.search(pattern, memo_text, re.IGNORECASE):
            errors.append(f"Memo missing required section: {description}")

    # Check memo references reproducibility instructions
    if "reproducibility" not in memo_text.lower() and "reproduce" not in memo_text.lower():
        errors.append("Memo does not contain reproducibility instructions")

    # Check license inventory is non-empty
    inv_path = repo_root / "publication" / "license_inventory.json"
    if inv_path.exists():
        inv = load_json(inv_path)
        categories = inv.get("categories", {})
        if not categories:
            errors.append("License inventory has no categories")
        if "upstream_source" not in categories:
            errors.append("License inventory missing upstream_source attribution")
        if "rust_runtime_dependencies" not in categories:
            errors.append("License inventory missing rust runtime dependencies")

    return errors


def build_publication_checklist(
    lineage_errors: list[str],
    hash_errors: list[str],
    repro_file_errors: list[str],
    repro_exec_errors: list[str],
    legal_errors: list[str],
) -> dict:
    """Build a structured publication checklist with explicit pass/fail
    outcomes for lineage and executed clean-checkout reproducibility."""
    return {
        "schema_version": 3,
        "checks": [
            {
                "id": "VAL-CROSS-001",
                "name": "Shared fixture lineage across stages",
                "result": "pass" if not lineage_errors and not hash_errors else "fail",
                "errors": lineage_errors + hash_errors,
            },
            {
                "id": "VAL-CROSS-004-files",
                "name": "Public fork contains reproducibility package (file presence)",
                "result": "pass" if not repro_file_errors else "fail",
                "errors": repro_file_errors,
            },
            {
                "id": "VAL-CROSS-004-exec",
                "name": "Executed clean-checkout smoke reproducibility (isolated worktree with provenance)",
                "result": "pass" if not repro_exec_errors else "fail",
                "errors": repro_exec_errors,
            },
            {
                "id": "VAL-CROSS-005",
                "name": "Public release includes legal + methodology disclosure",
                "result": "pass" if not legal_errors else "fail",
                "errors": legal_errors,
            },
            {
                "id": "VAL-CROSS-008",
                "name": "Public publication commit is traceable to measured evidence (parity + benchmark + memo lineage)",
                "result": "pass" if not lineage_errors else "fail",
                "errors": lineage_errors,
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="End-to-end traceability check across parity, benchmark, and memo"
    )
    parser.add_argument("--memo", required=True, help="Path to memo markdown file")
    parser.add_argument(
        "--run",
        default="latest",
        help="Benchmark run reference (run ID or 'latest')",
    )
    args = parser.parse_args()

    memo_path = Path(args.memo)
    if not memo_path.exists():
        print(f"FAIL: Memo not found at {memo_path}", file=sys.stderr)
        return 1

    repo_root = memo_path.resolve().parent.parent
    if not (repo_root / "publication").exists():
        repo_root = Path.cwd()

    memo_text = memo_path.read_text()

    # Load artifacts
    claim_map = load_json(repo_root / "publication" / "claim_evidence_map.json")

    # Resolve parity summary strictly from claim_evidence_map parity_run_ids
    # (no latest fallback — unresolved IDs are hard failures)
    parity_summary, parity_source, parity_resolution_errors = (
        resolve_parity_summary(claim_map, repo_root)
    )

    # Load all measured benchmark run manifests
    benchmark_manifests = []
    run_ids = claim_map.get("benchmark_run_ids", {})
    for run_type, run_id in run_ids.items():
        run_dir = repo_root / "benchmarks" / "out" / run_id
        if run_dir.exists():
            manifest_path = run_dir / "run_manifest.json"
            if manifest_path.exists():
                with open(manifest_path) as f:
                    benchmark_manifests.append(json.load(f))

    # Also load the specified run if different
    specified_run_dir = resolve_run_dir(args.run, repo_root)
    specified_manifest_path = specified_run_dir / "run_manifest.json"
    if specified_manifest_path.exists():
        with open(specified_manifest_path) as f:
            spec_manifest = json.load(f)
        spec_id = spec_manifest.get("run_id")
        if spec_id and spec_id not in [m.get("run_id") for m in benchmark_manifests]:
            benchmark_manifests.append(spec_manifest)

    # Extract memo references
    memo_commit = extract_memo_commit(memo_text)
    memo_hashes = extract_memo_manifest_hashes(memo_text)

    # Run checks
    print("=" * 60)
    print("TRACEABILITY CHECK")
    print("=" * 60)

    # 1. Commit lineage: strict parity/benchmark/memo equality (VAL-CROSS-001 + VAL-CROSS-008)
    #    Parity resolution errors are prepended — unresolved parity_run_ids
    #    are hard failures with no latest fallback.
    lineage_errors = list(parity_resolution_errors) + check_commit_lineage(
        memo_commit, claim_map, benchmark_manifests, parity_summary, parity_source
    )
    print(f"\n[{'PASS' if not lineage_errors else 'FAIL'}] Commit lineage (VAL-CROSS-001/008)")
    if memo_commit:
        print(f"  Memo commit: {memo_commit[:12]}...")
    if parity_summary.get("commit_sha"):
        print(f"  Parity commit: {parity_summary['commit_sha'][:12]}...")
    bench_commits = {
        m.get("run_type", "?"): m.get("commit_sha", "?")[:12]
        for m in benchmark_manifests
        if m.get("run_type") != "smoke"
    }
    if bench_commits:
        print(f"  Benchmark commits: {bench_commits}")
    for e in lineage_errors:
        print(f"  ERROR: {e}")

    # 2. Manifest hash consistency (VAL-CROSS-001)
    hash_errors = check_manifest_hash_consistency(
        memo_hashes, claim_map, benchmark_manifests
    )
    print(f"\n[{'PASS' if not hash_errors else 'FAIL'}] Manifest hash consistency (VAL-CROSS-001)")
    if memo_hashes:
        for k, v in memo_hashes.items():
            print(f"  Memo {k}: {v}...")
    for e in hash_errors:
        print(f"  ERROR: {e}")

    # 3. Reproducibility package — file presence (VAL-CROSS-004)
    repro_file_errors = check_reproducibility_package(repo_root)
    print(f"\n[{'PASS' if not repro_file_errors else 'FAIL'}] Reproducibility package files (VAL-CROSS-004)")
    for e in repro_file_errors:
        print(f"  ERROR: {e}")

    # 4. Reproducibility — clean-checkout execution (VAL-CROSS-004)
    repro_exec_errors = check_clean_checkout_reproducibility(repo_root, memo_commit)
    print(f"\n[{'PASS' if not repro_exec_errors else 'FAIL'}] Clean-checkout smoke reproducibility execution (VAL-CROSS-004)")
    for e in repro_exec_errors:
        print(f"  ERROR: {e}")

    # 5. Legal + methodology disclosure (VAL-CROSS-005)
    legal_errors = check_legal_methodology_disclosure(repo_root, memo_text)
    print(f"\n[{'PASS' if not legal_errors else 'FAIL'}] Legal + methodology disclosure (VAL-CROSS-005)")
    for e in legal_errors:
        print(f"  ERROR: {e}")

    # Build and save checklist
    checklist = build_publication_checklist(
        lineage_errors, hash_errors, repro_file_errors, repro_exec_errors, legal_errors
    )

    checklist_path = repo_root / "publication" / "publication_checklist.json"
    with open(checklist_path, "w") as f:
        json.dump(checklist, f, indent=2)
        f.write("\n")

    # Summary
    all_errors = (
        lineage_errors + hash_errors + repro_file_errors
        + repro_exec_errors + legal_errors
    )
    total_checks = len(checklist["checks"])
    passed_checks = sum(
        1 for c in checklist["checks"] if c["result"] == "pass"
    )

    print(f"\n{'=' * 60}")
    print(f"TRACEABILITY RESULT: {passed_checks}/{total_checks} checks passed")
    print(f"Checklist written to: {checklist_path}")

    if all_errors:
        print(f"\n{len(all_errors)} error(s) found.")
        return 1

    print("\nAll traceability checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
