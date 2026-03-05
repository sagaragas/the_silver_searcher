#!/usr/bin/env python3
"""Claim-threshold gate: blocks performance winner claims unless evidence
from local, nightly, and manual benchmark runs on the same commit/manifests
meets declared threshold rules.

VAL-BENCH-012: Claim-threshold gate is enforced across local and CI.
    Performance winner claims are allowed only when declared claim-threshold
    rules pass for local run + nightly CI run + manual CI run on the same
    commit and manifests.

Usage:
    python3 benchmarks/claim_gate.py --run latest
    python3 benchmarks/claim_gate.py --evidence-dir /path/to/evidence
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
BENCHMARKS_OUT = BENCHMARKS_DIR / "out"
POLICY_PATH = BENCHMARKS_DIR / "sampling_policy.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=False, ensure_ascii=False)
        f.write("\n")


def _ci_overlap_fraction(
    lo_a: float, hi_a: float,
    lo_b: float, hi_b: float,
) -> float:
    """Compute the fraction of overlap between two confidence intervals.

    Returns the overlap length divided by the length of the shorter interval.
    Returns 0.0 if no overlap. Returns 1.0 if one contains the other.
    """
    overlap_lo = max(lo_a, lo_b)
    overlap_hi = min(hi_a, hi_b)
    overlap = max(0.0, overlap_hi - overlap_lo)

    len_a = hi_a - lo_a
    len_b = hi_b - lo_b
    shorter = min(len_a, len_b)

    if shorter <= 0:
        return 0.0

    return min(overlap / shorter, 1.0)


# ---------------------------------------------------------------------------
# Cross-run alignment evidence (VAL-CROSS-007)
# ---------------------------------------------------------------------------

# Required fields for evidence schema validation.
_EVIDENCE_REQUIRED_FIELDS = [
    "run_id", "run_type", "commit_sha", "manifest_hashes",
    "parity_gate", "reproducibility_gate", "scenario_summaries",
]


def _validate_evidence_schema(evidence_item: dict[str, Any]) -> dict[str, Any]:
    """Validate that a single run evidence dict has all required fields.

    Returns a dict with 'result' ('pass'/'fail'), 'run_id', 'run_type',
    and optional 'missing_fields'.
    """
    missing = [f for f in _EVIDENCE_REQUIRED_FIELDS if f not in evidence_item]
    run_id = evidence_item.get("run_id", "unknown")
    run_type = evidence_item.get("run_type", "unknown")
    return {
        "run_id": run_id,
        "run_type": run_type,
        "result": "pass" if not missing else "fail",
        "missing_fields": missing,
    }


def _generate_local_vs_ci_comparison_report(
    evidence: list[dict[str, Any]],
    commit_check: dict[str, Any],
    manifest_hash_check: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Generate a machine-readable local-vs-CI reproducibility comparison report.

    Links local/nightly/manual runs for the same commit and manifests,
    validates per-run schema, and writes the report as an artifact.

    Returns the report dict.
    """
    # Build linked runs with run_type and run_id.
    linked_runs = [
        {"run_id": e["run_id"], "run_type": e["run_type"]}
        for e in evidence
    ]

    # Per-run schema validity.
    per_run_schema = [_validate_evidence_schema(e) for e in evidence]

    # Commit match: reuse the existing commit check result.
    commit_match = {
        "result": commit_check["result"],
        "unique_commits": commit_check["unique_commits"],
    }

    # Manifest match: reuse the existing manifest hash check result.
    manifest_match = {
        "result": manifest_hash_check["result"],
        "reference_hashes": manifest_hash_check.get("reference_hashes", {}),
        "mismatches": manifest_hash_check.get("mismatches", []),
    }

    # Schema validity overall.
    schema_all_pass = all(s["result"] == "pass" for s in per_run_schema)

    # Overall result: pass only if commit, manifest, and schema all pass.
    overall = "pass" if (
        commit_match["result"] == "pass"
        and manifest_match["result"] == "pass"
        and schema_all_pass
    ) else "fail"

    report: dict[str, Any] = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "result": overall,
        "linked_runs": linked_runs,
        "commit_match": commit_match,
        "manifest_match": manifest_match,
        "per_run_schema_validity": per_run_schema,
    }

    _write_json(output_dir / "local_vs_ci_comparison_report.json", report)
    return report


def _generate_run_manifest_set_equality_diff_report(
    evidence: list[dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    """Generate a run-manifest set-equality diff report.

    Computes the union of all scenario IDs across evidence runs and checks
    that each run covers the same set. Reports missing and extra scenarios
    per run_type relative to the union.

    Returns the report dict.
    """
    # Collect scenario sets per run_type.
    per_run_type_scenarios: dict[str, list[str]] = {}
    for e in evidence:
        rt = e["run_type"]
        sids = sorted({
            s["scenario_id"] for s in e.get("scenario_summaries", [])
        })
        per_run_type_scenarios[rt] = sids

    # Compute the union set.
    all_scenario_ids: set[str] = set()
    for sids in per_run_type_scenarios.values():
        all_scenario_ids.update(sids)
    union_set = sorted(all_scenario_ids)

    # Compute per-run diffs against the union.
    missing_scenarios: list[dict[str, Any]] = []
    extra_scenarios: list[dict[str, Any]] = []

    # For each run type, check if it has the full union set.
    # "missing" = in union but not in this run.
    # "extra" = in this run but not in other runs' intersection.
    # For simplicity and clarity: compare each run against the union.
    # If a scenario is in the union but NOT in a particular run, it's missing
    # from that run. If scenario sets differ, there are missing entries.
    for rt, sids in per_run_type_scenarios.items():
        sid_set = set(sids)
        missing_from_rt = sorted(all_scenario_ids - sid_set)
        if missing_from_rt:
            missing_scenarios.append({
                "run_type": rt,
                "missing": missing_from_rt,
            })
        # Extra: scenarios in this run but not in the intersection
        # (i.e., not present in all runs).
        if len(per_run_type_scenarios) > 1:
            intersection = set(all_scenario_ids)
            for other_sids in per_run_type_scenarios.values():
                intersection &= set(other_sids)
            extra_from_rt = sorted(sid_set - intersection)
            if extra_from_rt:
                extra_scenarios.append({
                    "run_type": rt,
                    "extra": extra_from_rt,
                })

    # Result: pass only if all runs have identical scenario sets.
    all_equal = all(
        set(sids) == all_scenario_ids
        for sids in per_run_type_scenarios.values()
    )
    result = "pass" if all_equal else "fail"

    report: dict[str, Any] = {
        "schema_version": 1,
        "timestamp": _now_iso(),
        "result": result,
        "union_scenarios": union_set,
        "per_run_type_scenarios": {
            rt: sids for rt, sids in sorted(per_run_type_scenarios.items())
        },
        "missing_scenarios": missing_scenarios,
        "extra_scenarios": extra_scenarios,
    }

    _write_json(
        output_dir / "run_manifest_set_equality_diff_report.json", report
    )
    return report


# ---------------------------------------------------------------------------
# Claim gate evaluation
# ---------------------------------------------------------------------------


def evaluate_claim_gate(
    evidence: list[dict[str, Any]],
    output_dir: Path,
    policy_path: Path | None = None,
) -> dict[str, Any]:
    """Evaluate the claim gate against run evidence from multiple run types.

    Args:
        evidence: List of run evidence dicts, each containing:
            - run_id, run_type, commit_sha, manifest_hashes
            - parity_gate ("pass"/"fail"), reproducibility_gate ("pass"/"fail")
            - scenario_summaries (list of scenario summary dicts)
        output_dir: Directory to write the claim gate artifact.
        policy_path: Path to sampling_policy.json.

    Returns:
        Claim gate report dict.
    """
    if policy_path is None:
        policy_path = POLICY_PATH

    policy = _load_json(policy_path)
    thresholds = policy["claim_thresholds"]

    required_types = set(thresholds["required_run_types"])
    min_speedup = thresholds["min_speedup_ratio"]
    max_overlap = thresholds["max_ci_overlap_fraction"]
    parity_required = thresholds["parity_gate_required"]
    repro_required = thresholds["reproducibility_gate_required"]

    # --- Run type check ---
    present_types = {e["run_type"] for e in evidence}
    missing_types = required_types - present_types
    run_type_check = {
        "result": "pass" if not missing_types else "fail",
        "required": sorted(required_types),
        "present": sorted(present_types),
        "missing": sorted(missing_types),
    }

    # --- Commit consistency check ---
    commit_shas = {e["commit_sha"] for e in evidence}
    commit_check = {
        "result": "pass" if len(commit_shas) <= 1 else "fail",
        "unique_commits": sorted(commit_shas),
    }

    # --- Manifest hash consistency check ---
    manifest_hash_sets: list[dict[str, str]] = [
        e.get("manifest_hashes", {}) for e in evidence
    ]
    if len(manifest_hash_sets) <= 1:
        manifest_hash_consistent = True
        manifest_hash_mismatches: list[str] = []
    else:
        reference = manifest_hash_sets[0]
        manifest_hash_mismatches = []
        for idx, mh in enumerate(manifest_hash_sets[1:], start=1):
            if mh != reference:
                differing_keys = sorted(
                    k for k in set(reference) | set(mh)
                    if reference.get(k) != mh.get(k)
                )
                manifest_hash_mismatches.append(
                    f"run[{idx}] ({evidence[idx]['run_id']}): "
                    f"differs on keys {differing_keys}"
                )
        manifest_hash_consistent = len(manifest_hash_mismatches) == 0

    manifest_hash_check = {
        "result": "pass" if manifest_hash_consistent else "fail",
        "reference_run_id": evidence[0]["run_id"] if evidence else None,
        "reference_hashes": manifest_hash_sets[0] if manifest_hash_sets else {},
        "mismatches": manifest_hash_mismatches,
    }

    # --- Parity gate check ---
    parity_results = [e.get("parity_gate", "unknown") for e in evidence]
    parity_all_pass = all(p == "pass" for p in parity_results)
    parity_check = {
        "result": "pass" if (not parity_required or parity_all_pass) else "fail",
        "required": parity_required,
        "run_results": {e["run_id"]: e.get("parity_gate", "unknown") for e in evidence},
    }

    # --- Reproducibility gate check ---
    repro_results = [e.get("reproducibility_gate", "unknown") for e in evidence]
    repro_all_pass = all(r == "pass" for r in repro_results)
    reproducibility_check = {
        "result": "pass" if (not repro_required or repro_all_pass) else "fail",
        "required": repro_required,
        "run_results": {e["run_id"]: e.get("reproducibility_gate", "unknown") for e in evidence},
    }

    # --- Scenario-level claim evaluation ---
    # Aggregate scenario summaries across run types.
    # For claim evaluation, we use the summaries from each run type.
    scenario_claims: list[dict[str, Any]] = []

    # Collect all scenario IDs across all evidence.
    all_scenario_ids: set[str] = set()
    for e in evidence:
        for ss in e.get("scenario_summaries", []):
            all_scenario_ids.add(ss["scenario_id"])

    for sid in sorted(all_scenario_ids):
        # Collect per-run-type stats for this scenario.
        run_type_stats: dict[str, dict[str, Any]] = {}
        for e in evidence:
            for ss in e.get("scenario_summaries", []):
                if ss["scenario_id"] == sid:
                    run_type_stats[e["run_type"]] = ss.get("comparator_stats", {})
                    break

        # Only evaluate if we have all required run types for this scenario.
        if not required_types.issubset(run_type_stats.keys()):
            scenario_claims.append({
                "scenario_id": sid,
                "evaluable": False,
                "reason": f"Missing run types: {sorted(required_types - run_type_stats.keys())}",
                "pair_evaluations": [],
            })
            continue

        # Evaluate pairwise comparator claims.
        # Use the local run as the primary evidence source for direction.
        primary_stats = run_type_stats.get("local", {})
        comparators = sorted(primary_stats.keys())

        pair_evaluations: list[dict[str, Any]] = []
        for i, comp_a in enumerate(comparators):
            for comp_b in comparators[i + 1:]:
                stats_a = primary_stats[comp_a]
                stats_b = primary_stats[comp_b]

                med_a = stats_a["median_s"]
                med_b = stats_b["median_s"]

                if med_a <= 0 or med_b <= 0:
                    continue

                # Determine faster/slower from primary (local) run.
                if med_a < med_b:
                    faster, slower = comp_a, comp_b
                    ratio = med_b / med_a
                    ci_faster = (stats_a["ci_lower_s"], stats_a["ci_upper_s"])
                    ci_slower = (stats_b["ci_lower_s"], stats_b["ci_upper_s"])
                else:
                    faster, slower = comp_b, comp_a
                    ratio = med_a / med_b
                    ci_faster = (stats_b["ci_lower_s"], stats_b["ci_upper_s"])
                    ci_slower = (stats_a["ci_lower_s"], stats_a["ci_upper_s"])

                overlap = _ci_overlap_fraction(
                    ci_faster[0], ci_faster[1],
                    ci_slower[0], ci_slower[1],
                )

                # Check if the claim meets thresholds on primary run.
                speedup_ok = ratio >= min_speedup
                overlap_ok = overlap <= max_overlap

                # Check agreement across all run types.
                cross_run_agree = True
                if thresholds.get("all_run_types_must_agree", True):
                    for rt, rt_stats in run_type_stats.items():
                        if faster in rt_stats and slower in rt_stats:
                            rt_faster_med = rt_stats[faster]["median_s"]
                            rt_slower_med = rt_stats[slower]["median_s"]
                            if rt_faster_med > 0 and rt_slower_med > 0:
                                rt_ratio = rt_slower_med / rt_faster_med
                                if rt_ratio < 1.0:
                                    # Direction disagreement.
                                    cross_run_agree = False
                                    break

                # Per-run-type threshold evaluation: each required run type
                # must independently pass speedup and CI overlap thresholds.
                per_run_type_results: dict[str, dict[str, Any]] = {}
                per_run_type_all_pass = True
                for rt in sorted(required_types):
                    rt_stats_map = run_type_stats.get(rt, {})
                    if faster not in rt_stats_map or slower not in rt_stats_map:
                        per_run_type_results[rt] = {
                            "result": "skip",
                            "reason": "comparator missing",
                        }
                        per_run_type_all_pass = False
                        continue

                    rt_faster_stats = rt_stats_map[faster]
                    rt_slower_stats = rt_stats_map[slower]

                    rt_faster_med = rt_faster_stats["median_s"]
                    rt_slower_med = rt_slower_stats["median_s"]

                    if rt_faster_med <= 0 or rt_slower_med <= 0:
                        per_run_type_results[rt] = {
                            "result": "skip",
                            "reason": "zero or negative median",
                        }
                        per_run_type_all_pass = False
                        continue

                    rt_ratio = rt_slower_med / rt_faster_med
                    rt_speedup_ok = rt_ratio >= min_speedup

                    rt_ci_faster = (
                        rt_faster_stats["ci_lower_s"],
                        rt_faster_stats["ci_upper_s"],
                    )
                    rt_ci_slower = (
                        rt_slower_stats["ci_lower_s"],
                        rt_slower_stats["ci_upper_s"],
                    )
                    rt_overlap = _ci_overlap_fraction(
                        rt_ci_faster[0], rt_ci_faster[1],
                        rt_ci_slower[0], rt_ci_slower[1],
                    )
                    rt_overlap_ok = rt_overlap <= max_overlap

                    rt_pass = rt_speedup_ok and rt_overlap_ok
                    if not rt_pass:
                        per_run_type_all_pass = False

                    per_run_type_results[rt] = {
                        "result": "pass" if rt_pass else "fail",
                        "speedup_ratio": round(rt_ratio, 4),
                        "ci_overlap_fraction": round(rt_overlap, 4),
                        "speedup_threshold_met": rt_speedup_ok,
                        "overlap_threshold_met": rt_overlap_ok,
                    }

                claim_allowed = (
                    speedup_ok
                    and overlap_ok
                    and cross_run_agree
                    and per_run_type_all_pass
                )

                pair_evaluations.append({
                    "faster": faster,
                    "slower": slower,
                    "speedup_ratio": round(ratio, 4),
                    "ci_overlap_fraction": round(overlap, 4),
                    "speedup_threshold_met": speedup_ok,
                    "overlap_threshold_met": overlap_ok,
                    "cross_run_agreement": cross_run_agree,
                    "per_run_type_pass": per_run_type_all_pass,
                    "per_run_type_results": per_run_type_results,
                    "claim_allowed": claim_allowed,
                })

        scenario_claims.append({
            "scenario_id": sid,
            "evaluable": True,
            "pair_evaluations": pair_evaluations,
        })

    # --- Cross-run alignment: set equality (VAL-CROSS-007) ---
    set_equality_report = _generate_run_manifest_set_equality_diff_report(
        evidence, output_dir,
    )
    set_equality_check = {
        "result": set_equality_report["result"],
        "union_scenarios": set_equality_report["union_scenarios"],
        "missing_scenarios": set_equality_report["missing_scenarios"],
        "extra_scenarios": set_equality_report["extra_scenarios"],
    }

    # --- Cross-run alignment: local-vs-CI comparison (VAL-CROSS-007) ---
    _generate_local_vs_ci_comparison_report(
        evidence, commit_check, manifest_hash_check, output_dir,
    )

    # --- Overall gate ---
    checks_pass = all([
        run_type_check["result"] == "pass",
        commit_check["result"] == "pass",
        manifest_hash_check["result"] == "pass",
        parity_check["result"] == "pass",
        reproducibility_check["result"] == "pass",
        set_equality_check["result"] == "pass",
    ])
    overall = "pass" if checks_pass else "fail"

    linked_run_ids = [e["run_id"] for e in evidence]

    report = {
        "schema_version": 1,
        "gate": overall,
        "timestamp": _now_iso(),
        "linked_run_ids": linked_run_ids,
        "threshold_config": {
            "min_speedup_ratio": min_speedup,
            "max_ci_overlap_fraction": max_overlap,
            "required_run_types": sorted(required_types),
            "parity_gate_required": parity_required,
            "reproducibility_gate_required": repro_required,
        },
        "run_type_check": run_type_check,
        "commit_check": commit_check,
        "manifest_hash_check": manifest_hash_check,
        "parity_check": parity_check,
        "reproducibility_check": reproducibility_check,
        "set_equality_check": set_equality_check,
        "scenario_claims": scenario_claims,
    }

    _write_json(output_dir / "claim_gate.json", report)

    return report


# ---------------------------------------------------------------------------
# Evidence loading from run directories
# ---------------------------------------------------------------------------


def load_run_evidence(run_dir: Path) -> dict[str, Any]:
    """Load run evidence from a benchmark run directory.

    Reads run_manifest.json, correctness_gate.json, sampling_validation.json,
    and reproducibility_report.json to build a complete evidence record.
    """
    manifest = _load_json(run_dir / "run_manifest.json")

    # Determine parity gate status.
    parity_gate = "unknown"
    correctness_path = run_dir / "correctness_gate.json"
    if correctness_path.exists():
        cg = _load_json(correctness_path)
        parity_gate = cg.get("gate", "unknown")

    # Determine reproducibility gate status.
    repro_gate = "unknown"
    repro_path = run_dir / "reproducibility_report.json"
    if repro_path.exists():
        rr = _load_json(repro_path)
        repro_gate = rr.get("result", "unknown")
    else:
        # If no reproducibility report, check manifest hashes on disk.
        try:
            from manifest_pinning import verify_manifest_hashes_on_disk
            result = verify_manifest_hashes_on_disk(manifest)
            repro_gate = result["result"]
        except (ImportError, Exception):
            repro_gate = "unknown"

    # Load sampling validation for scenario summaries.
    scenario_summaries = []
    sampling_path = run_dir / "sampling_validation.json"
    if sampling_path.exists():
        sv = _load_json(sampling_path)
        scenario_summaries = sv.get("scenario_summaries", [])

    return {
        "run_id": manifest.get("run_id", "unknown"),
        "run_type": manifest.get("run_type", "local"),
        "commit_sha": manifest.get("commit_sha", "unknown"),
        "manifest_hashes": manifest.get("manifest_hashes", {}),
        "parity_gate": parity_gate,
        "reproducibility_gate": repro_gate,
        "scenario_summaries": scenario_summaries,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def resolve_run_dir(run_id: str | None, run_dir: str | None) -> Path:
    """Resolve run directory from run ID or explicit path."""
    if run_dir:
        return Path(run_dir)
    if run_id == "latest":
        latest = BENCHMARKS_OUT / "latest"
        if latest.is_symlink():
            return latest.resolve()
        if not BENCHMARKS_OUT.exists():
            print("ERROR: No benchmark output directory found", file=sys.stderr)
            sys.exit(2)
        runs = sorted(
            [d for d in BENCHMARKS_OUT.iterdir() if d.is_dir() and d.name != "latest"],
            reverse=True,
        )
        if not runs:
            print("ERROR: No benchmark runs found", file=sys.stderr)
            sys.exit(2)
        return runs[0]
    return BENCHMARKS_OUT / run_id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Claim-threshold gate: evaluate performance claim eligibility."
    )
    parser.add_argument(
        "--run",
        type=str,
        default=None,
        help="Run ID or 'latest' to evaluate as local evidence.",
    )
    parser.add_argument(
        "--run-dir",
        type=str,
        default=None,
        help="Explicit run directory for local evidence.",
    )
    parser.add_argument(
        "--evidence-dir",
        type=str,
        default=None,
        help="Directory containing run evidence subdirs by run_type.",
    )
    args = parser.parse_args()

    # Build evidence list.
    evidence: list[dict[str, Any]] = []

    if args.evidence_dir:
        edir = Path(args.evidence_dir)
        if not edir.exists():
            print(f"ERROR: Evidence directory not found: {edir}", file=sys.stderr)
            sys.exit(2)
        for subdir in sorted(edir.iterdir()):
            if subdir.is_dir() and (subdir / "run_manifest.json").exists():
                evidence.append(load_run_evidence(subdir))
    else:
        # Single run mode: load as local evidence.
        if not args.run and not args.run_dir:
            args.run = "latest"
        run_dir = resolve_run_dir(args.run, args.run_dir)
        if not run_dir.exists():
            print(f"ERROR: Run directory not found: {run_dir}", file=sys.stderr)
            sys.exit(2)
        evidence.append(load_run_evidence(run_dir))

    # Determine output directory.
    if args.evidence_dir:
        output_dir = Path(args.evidence_dir)
    elif args.run_dir:
        output_dir = Path(args.run_dir)
    else:
        output_dir = resolve_run_dir(args.run, args.run_dir)

    result = evaluate_claim_gate(evidence, output_dir)

    # Print summary.
    print(f"\nClaim Gate: {result['gate'].upper()}")
    print(f"  Linked runs: {result['linked_run_ids']}")
    print(f"  Run type check: {result['run_type_check']['result'].upper()}")
    print(f"  Commit check: {result['commit_check']['result'].upper()}")
    print(f"  Manifest hash check: {result['manifest_hash_check']['result'].upper()}")
    print(f"  Parity check: {result['parity_check']['result'].upper()}")
    print(f"  Reproducibility check: {result['reproducibility_check']['result'].upper()}")
    print(f"  Set equality check: {result['set_equality_check']['result'].upper()}")

    if result["run_type_check"]["missing"]:
        print(f"  Missing run types: {result['run_type_check']['missing']}")

    if result["manifest_hash_check"]["mismatches"]:
        print("  Manifest hash mismatches:")
        for m in result["manifest_hash_check"]["mismatches"]:
            print(f"    {m}")

    if result["scenario_claims"]:
        print(f"\n  Scenario claims ({len(result['scenario_claims'])}):")
        for sc in result["scenario_claims"]:
            if not sc.get("evaluable", False):
                print(f"    {sc['scenario_id']}: NOT EVALUABLE — {sc.get('reason', '')}")
                continue
            print(f"    {sc['scenario_id']}:")
            for pe in sc.get("pair_evaluations", []):
                status = "✓ ALLOWED" if pe["claim_allowed"] else "✗ BLOCKED"
                print(
                    f"      {pe['faster']} > {pe['slower']}: "
                    f"{pe['speedup_ratio']:.2f}x {status}"
                )

    print(f"\n  Artifacts:")
    print(f"    {output_dir / 'claim_gate.json'}")
    print(f"    {output_dir / 'local_vs_ci_comparison_report.json'}")
    print(f"    {output_dir / 'run_manifest_set_equality_diff_report.json'}")

    sys.exit(0 if result["gate"] == "pass" else 1)


if __name__ == "__main__":
    main()
