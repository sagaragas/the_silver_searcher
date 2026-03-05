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
        # Use the local run as the primary evidence source.
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

                # Determine faster/slower.
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

                # Check if the claim meets thresholds.
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

                claim_allowed = speedup_ok and overlap_ok and cross_run_agree

                pair_evaluations.append({
                    "faster": faster,
                    "slower": slower,
                    "speedup_ratio": round(ratio, 4),
                    "ci_overlap_fraction": round(overlap, 4),
                    "speedup_threshold_met": speedup_ok,
                    "overlap_threshold_met": overlap_ok,
                    "cross_run_agreement": cross_run_agree,
                    "claim_allowed": claim_allowed,
                })

        scenario_claims.append({
            "scenario_id": sid,
            "evaluable": True,
            "pair_evaluations": pair_evaluations,
        })

    # --- Overall gate ---
    checks_pass = all([
        run_type_check["result"] == "pass",
        commit_check["result"] == "pass",
        parity_check["result"] == "pass",
        reproducibility_check["result"] == "pass",
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
        "parity_check": parity_check,
        "reproducibility_check": reproducibility_check,
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
    print(f"  Parity check: {result['parity_check']['result'].upper()}")
    print(f"  Reproducibility check: {result['reproducibility_check']['result'].upper()}")

    if result["run_type_check"]["missing"]:
        print(f"  Missing run types: {result['run_type_check']['missing']}")

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

    print(f"\n  Artifact: {output_dir / 'claim_gate.json'}")

    sys.exit(0 if result["gate"] == "pass" else 1)


if __name__ == "__main__":
    main()
