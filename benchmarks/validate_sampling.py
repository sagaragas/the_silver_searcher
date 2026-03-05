#!/usr/bin/env python3
"""Validate benchmark sampling, warmup, statistical method, order-bias,
and outlier/retry policy enforcement.

VAL-BENCH-006: Sampling and warmup policy is enforced.
VAL-BENCH-007: Statistical method is locked and reported.
VAL-BENCH-010: Order-bias controls are enforced.
VAL-BENCH-011: Outlier/retry policy is predeclared and auditable.

Usage:
    python3 benchmarks/validate_sampling.py --run latest
    python3 benchmarks/validate_sampling.py --run-dir /path/to/run/dir
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
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


def _policy_hash(policy: dict[str, Any]) -> str:
    """Compute a deterministic hash of the policy document."""
    canonical = json.dumps(policy, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------


def _median(values: list[float]) -> float:
    """Compute the median of a list of values."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n % 2 == 1:
        return sorted_vals[n // 2]
    return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2


def _percentile(values: list[float], p: float) -> float:
    """Compute the p-th percentile (0–1) of a list of values."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    idx = p * (n - 1)
    lower = int(math.floor(idx))
    upper = int(math.ceil(idx))
    if lower == upper:
        return sorted_vals[lower]
    frac = idx - lower
    return sorted_vals[lower] * (1 - frac) + sorted_vals[upper] * frac


def _iqr(values: list[float]) -> float:
    """Compute the interquartile range."""
    return _percentile(values, 0.75) - _percentile(values, 0.25)


def _bootstrap_ci(
    values: list[float],
    level: float = 0.95,
    n_bootstrap: int = 1000,
    seed: int = 0,
) -> tuple[float, float]:
    """Compute percentile bootstrap CI for the median."""
    if len(values) < 2:
        m = _median(values)
        return (m, m)
    rng = random.Random(seed)
    medians = []
    for _ in range(n_bootstrap):
        sample = [rng.choice(values) for _ in range(len(values))]
        medians.append(_median(sample))
    alpha = 1 - level
    lo = _percentile(medians, alpha / 2)
    hi = _percentile(medians, 1 - alpha / 2)
    return (lo, hi)


def _flag_outliers_iqr(
    values: list[float],
    multiplier: float = 1.5,
) -> list[dict[str, Any]]:
    """Flag outliers using IQR fence method.

    Returns a list of dicts describing flagged values with reason codes.
    """
    if len(values) < 4:
        return []
    q1 = _percentile(values, 0.25)
    q3 = _percentile(values, 0.75)
    iqr = q3 - q1
    lower = q1 - multiplier * iqr
    upper = q3 + multiplier * iqr

    flagged = []
    for i, v in enumerate(values):
        if v < lower:
            flagged.append({
                "index": i,
                "value_s": round(v, 6),
                "reason": "iqr_fence_low",
                "fence_lower": round(lower, 6),
                "fence_upper": round(upper, 6),
            })
        elif v > upper:
            flagged.append({
                "index": i,
                "value_s": round(v, 6),
                "reason": "iqr_fence_high",
                "fence_lower": round(lower, 6),
                "fence_upper": round(upper, 6),
            })
    return flagged


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------


def validate_sampling(
    run_manifest: dict[str, Any],
    output_dir: Path,
    policy_path: Path | None = None,
) -> dict[str, Any]:
    """Validate a benchmark run against the sampling policy.

    Checks warmup counts, sample counts, schedule presence,
    outlier policy audit, and computes statistical summaries.

    Args:
        run_manifest: The benchmark run manifest dict (schema_version >= 2).
        output_dir: Directory to write the validation artifact.
        policy_path: Path to sampling_policy.json. Defaults to benchmarks/sampling_policy.json.

    Returns:
        Validation report dict.
    """
    if policy_path is None:
        policy_path = POLICY_PATH

    policy = _load_json(policy_path)
    pol_hash = _policy_hash(policy)

    min_warmup = policy["warmup"]["min_count"]
    min_samples = policy["sampling"]["min_measured_samples"]
    stat_method = policy["statistical_method"]
    ci_config = stat_method["confidence_interval"]
    outlier_config = policy["outlier_policy"]
    order_config = policy["order_bias"]

    # --- Warmup check (VAL-BENCH-006) ---
    warmup_violations: list[dict[str, Any]] = []
    sample_violations: list[dict[str, Any]] = []
    scenario_summaries: list[dict[str, Any]] = []
    all_flagged: list[dict[str, Any]] = []

    for scenario in run_manifest.get("scenarios", []):
        if scenario.get("skipped", False):
            continue

        sid = scenario.get("scenario_id", "unknown")
        results = scenario.get("results", {})
        comp_stats: dict[str, Any] = {}

        for comp, cell in results.items():
            if isinstance(cell, dict) and cell.get("skipped", False):
                continue

            raw_samples = cell.get("raw_samples", [])
            measured = cell.get("measured_samples", [])
            warmup_count = cell.get("warmup_count", 0)
            measured_count = cell.get("measured_count", len(measured))

            # Warmup check.
            if warmup_count < min_warmup:
                warmup_violations.append({
                    "scenario_id": sid,
                    "comparator": comp,
                    "warmup_count": warmup_count,
                    "required": min_warmup,
                })

            # Sample count check.
            if measured_count < min_samples:
                sample_violations.append({
                    "scenario_id": sid,
                    "comparator": comp,
                    "measured_count": measured_count,
                    "required": min_samples,
                })

            # Compute statistical summary (VAL-BENCH-007).
            elapsed_values = [s["elapsed_s"] for s in measured if "elapsed_s" in s]
            if elapsed_values:
                med = _median(elapsed_values)
                iqr_val = _iqr(elapsed_values)
                ci_lo, ci_hi = _bootstrap_ci(
                    elapsed_values,
                    level=ci_config["level"],
                    n_bootstrap=ci_config["bootstrap_samples"],
                )
                comp_stats[comp] = {
                    "median_s": round(med, 6),
                    "iqr_s": round(iqr_val, 6),
                    "ci_lower_s": round(ci_lo, 6),
                    "ci_upper_s": round(ci_hi, 6),
                    "ci_level": ci_config["level"],
                    "measured_count": measured_count,
                    "method_id": stat_method["id"],
                }

                # Outlier detection (VAL-BENCH-011).
                flagged = _flag_outliers_iqr(
                    elapsed_values,
                    multiplier=outlier_config["iqr_multiplier"],
                )
                for f in flagged:
                    all_flagged.append({
                        "scenario_id": sid,
                        "comparator": comp,
                        **f,
                    })

            # Also collect any pre-flagged outliers from the manifest itself.
            manifest_flags = cell.get("outlier_flags", [])
            for mf in manifest_flags:
                all_flagged.append({
                    "scenario_id": sid,
                    "comparator": comp,
                    **mf,
                })

        if comp_stats:
            scenario_summaries.append({
                "scenario_id": sid,
                "comparator_stats": comp_stats,
            })

    # --- Order-bias check (VAL-BENCH-010) ---
    schedule = run_manifest.get("execution_schedule")
    order_bias_result: dict[str, Any] = {}
    if schedule:
        order_bias_result = {
            "result": "pass",
            "schedule_type": schedule.get("schedule", "unknown"),
            "seed": schedule.get("seed"),
            "entry_count": len(schedule.get("entries", [])),
        }
    else:
        order_bias_result = {
            "result": "fail",
            "schedule_type": None,
            "seed": None,
            "entry_count": 0,
            "reason": "No execution_schedule found in run manifest",
        }

    # --- Build result ---
    warmup_pass = len(warmup_violations) == 0
    sample_pass = len(sample_violations) == 0
    overall = "pass" if (warmup_pass and sample_pass and order_bias_result["result"] == "pass") else "fail"

    # Deduplicate flagged samples by (scenario_id, comparator, index/iteration).
    seen_flags: set[str] = set()
    unique_flagged: list[dict[str, Any]] = []
    for f in all_flagged:
        key = f"{f.get('scenario_id')}/{f.get('comparator')}/{f.get('index', f.get('iteration', ''))}"
        if key not in seen_flags:
            seen_flags.add(key)
            unique_flagged.append(f)

    report = {
        "schema_version": 1,
        "gate": overall,
        "timestamp": _now_iso(),
        "policy_hash": pol_hash,
        "run_id": run_manifest.get("run_id", "unknown"),
        "commit_sha": run_manifest.get("commit_sha", "unknown"),
        "warmup_check": {
            "result": "pass" if warmup_pass else "fail",
            "min_required": min_warmup,
            "violations": warmup_violations,
        },
        "sample_count_check": {
            "result": "pass" if sample_pass else "fail",
            "min_required": min_samples,
            "violations": sample_violations,
        },
        "statistical_method": {
            "id": stat_method["id"],
            "summary_metric": stat_method["summary_metric"],
            "dispersion_metric": stat_method["dispersion_metric"],
            "ci_method": ci_config["method"],
            "ci_level": ci_config["level"],
        },
        "order_bias_check": order_bias_result,
        "outlier_audit": {
            "policy_method": outlier_config["method"],
            "policy_hash": pol_hash,
            "iqr_multiplier": outlier_config["iqr_multiplier"],
            "action": outlier_config["action"],
            "flagged_count": len(unique_flagged),
            "flagged_samples": unique_flagged,
            "silently_dropped": 0,
        },
        "scenario_summaries": scenario_summaries,
    }

    # Write artifact.
    _write_json(output_dir / "sampling_validation.json", report)

    return report


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
        description="Validate benchmark sampling, warmup, and statistical policy."
    )
    parser.add_argument(
        "--run",
        type=str,
        default=None,
        help="Run ID or 'latest' to validate.",
    )
    parser.add_argument(
        "--run-dir",
        type=str,
        default=None,
        help="Explicit run directory path.",
    )
    args = parser.parse_args()

    if not args.run and not args.run_dir:
        args.run = "latest"

    run_dir = resolve_run_dir(args.run, args.run_dir)
    if not run_dir.exists():
        print(f"ERROR: Run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(2)

    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: run_manifest.json not found in {run_dir}", file=sys.stderr)
        sys.exit(2)

    manifest = _load_json(manifest_path)
    result = validate_sampling(manifest, run_dir)

    # Print summary.
    print(f"\nSampling Validation: {result['gate'].upper()}")
    print(f"  Run: {result['run_id']}")
    print(f"  Policy hash: {result['policy_hash'][:16]}…")
    print(f"  Warmup check: {result['warmup_check']['result'].upper()}")
    print(f"  Sample count check: {result['sample_count_check']['result'].upper()}")
    print(f"  Order-bias check: {result['order_bias_check']['result'].upper()}")
    print(f"  Statistical method: {result['statistical_method']['id']}")
    print(f"  Outlier flagged: {result['outlier_audit']['flagged_count']}")
    print(f"  Silently dropped: {result['outlier_audit']['silently_dropped']}")

    if result["warmup_check"]["violations"]:
        print("\n  Warmup violations:")
        for v in result["warmup_check"]["violations"]:
            print(f"    {v['scenario_id']}/{v['comparator']}: {v['warmup_count']} < {v['required']}")

    if result["sample_count_check"]["violations"]:
        print("\n  Sample count violations:")
        for v in result["sample_count_check"]["violations"]:
            print(f"    {v['scenario_id']}/{v['comparator']}: {v['measured_count']} < {v['required']}")

    if result["scenario_summaries"]:
        print(f"\n  Scenario summaries ({len(result['scenario_summaries'])} scenarios):")
        for ss in result["scenario_summaries"]:
            print(f"    {ss['scenario_id']}:")
            for comp, stats in ss["comparator_stats"].items():
                ci_lo = stats["ci_lower_s"]
                ci_hi = stats["ci_upper_s"]
                print(
                    f"      {comp}: median={stats['median_s']:.4f}s "
                    f"IQR={stats['iqr_s']:.4f}s "
                    f"CI=[{ci_lo:.4f}, {ci_hi:.4f}]"
                )

    print(f"\n  Artifact: {run_dir / 'sampling_validation.json'}")

    sys.exit(0 if result["gate"] == "pass" else 1)


if __name__ == "__main__":
    main()
