#!/usr/bin/env python3
"""End-to-end traceability validation across parity, benchmark, and memo artifacts.

Validates:
  VAL-CROSS-001: Shared fixture lineage across stages (commit SHA + manifest hashes)
  VAL-CROSS-004: Public fork contains reproducibility package
  VAL-CROSS-005: Public release includes legal + methodological disclosure
  VAL-CROSS-008: Public publication commit is traceable to measured evidence

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


def check_cross_artifact_commit_consistency(
    memo_commit: str | None,
    claim_map: dict,
    benchmark_manifests: list[dict],
    parity_summary: dict,
) -> list[str]:
    """VAL-CROSS-001 + VAL-CROSS-008: Check commit SHA consistency across artifacts."""
    errors = []

    # Collect all commit SHAs
    commits = {}

    if memo_commit:
        commits["memo"] = memo_commit

    claim_map_commit = claim_map.get("evidence_commit_sha")
    if claim_map_commit:
        commits["claim_evidence_map"] = claim_map_commit

    for manifest in benchmark_manifests:
        run_id = manifest.get("run_id", "unknown")
        run_type = manifest.get("run_type", "unknown")
        commit = manifest.get("commit_sha")
        if commit:
            commits[f"benchmark_{run_type}_{run_id}"] = commit

    parity_commit = parity_summary.get("commit_sha")
    if parity_commit:
        commits["parity"] = parity_commit

    # Check consistency among measured benchmark runs
    benchmark_commits = {
        k: v for k, v in commits.items() if k.startswith("benchmark_") and "smoke" not in k
    }
    if benchmark_commits:
        unique_bench = set(benchmark_commits.values())
        if len(unique_bench) > 1:
            errors.append(
                f"Benchmark commit SHAs differ across runs: "
                f"{json.dumps(benchmark_commits, indent=2)}"
            )

    # Check memo commit matches benchmark evidence commit
    if memo_commit and claim_map_commit:
        if memo_commit != claim_map_commit:
            errors.append(
                f"Memo commit ({memo_commit}) != "
                f"claim_evidence_map commit ({claim_map_commit})"
            )

    if memo_commit and benchmark_commits:
        bench_commit = next(iter(set(benchmark_commits.values())))
        if memo_commit != bench_commit:
            errors.append(
                f"Memo commit ({memo_commit}) != "
                f"benchmark measured commit ({bench_commit})"
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
    benchmark_hashes = {}
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
    commit_errors: list[str],
    hash_errors: list[str],
    repro_errors: list[str],
    legal_errors: list[str],
) -> dict:
    """Build a structured publication checklist."""
    return {
        "schema_version": 1,
        "checks": [
            {
                "id": "VAL-CROSS-001",
                "name": "Shared fixture lineage across stages",
                "result": "pass" if not commit_errors and not hash_errors else "fail",
                "errors": commit_errors + hash_errors,
            },
            {
                "id": "VAL-CROSS-004",
                "name": "Public fork contains reproducibility package",
                "result": "pass" if not repro_errors else "fail",
                "errors": repro_errors,
            },
            {
                "id": "VAL-CROSS-005",
                "name": "Public release includes legal + methodology disclosure",
                "result": "pass" if not legal_errors else "fail",
                "errors": legal_errors,
            },
            {
                "id": "VAL-CROSS-008",
                "name": "Public publication commit is traceable to measured evidence",
                "result": "pass" if not commit_errors else "fail",
                "errors": commit_errors,
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
    parity_latest = repo_root / "parity-artifacts" / "latest"
    parity_summary = load_json(parity_latest / "summary.json") if parity_latest.exists() else {}

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

    # 1. Cross-artifact commit consistency (VAL-CROSS-001 + VAL-CROSS-008)
    commit_errors = check_cross_artifact_commit_consistency(
        memo_commit, claim_map, benchmark_manifests, parity_summary
    )
    print(f"\n[{'PASS' if not commit_errors else 'FAIL'}] Commit SHA consistency (VAL-CROSS-001/008)")
    if memo_commit:
        print(f"  Memo commit: {memo_commit[:12]}...")
    for e in commit_errors:
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

    # 3. Reproducibility package (VAL-CROSS-004)
    repro_errors = check_reproducibility_package(repo_root)
    print(f"\n[{'PASS' if not repro_errors else 'FAIL'}] Reproducibility package (VAL-CROSS-004)")
    for e in repro_errors:
        print(f"  ERROR: {e}")

    # 4. Legal + methodology disclosure (VAL-CROSS-005)
    legal_errors = check_legal_methodology_disclosure(repo_root, memo_text)
    print(f"\n[{'PASS' if not legal_errors else 'FAIL'}] Legal + methodology disclosure (VAL-CROSS-005)")
    for e in legal_errors:
        print(f"  ERROR: {e}")

    # Build and save checklist
    checklist = build_publication_checklist(
        commit_errors, hash_errors, repro_errors, legal_errors
    )

    checklist_path = repo_root / "publication" / "publication_checklist.json"
    with open(checklist_path, "w") as f:
        json.dump(checklist, f, indent=2)
        f.write("\n")

    # Summary
    all_errors = commit_errors + hash_errors + repro_errors + legal_errors
    total_checks = 4
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
