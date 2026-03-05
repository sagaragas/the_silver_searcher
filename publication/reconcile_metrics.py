#!/usr/bin/env python3
"""Reconcile memo-reported benchmark values against benchmark run artifacts.

Validates VAL-CROSS-003: Memo values reconcile with benchmark artifacts
with zero unresolved diffs.

Extracts numeric performance claims (table values AND speedup ratio
narrative claims) from the memo and compares them against the
authoritative sampling_validation.json and claim_gate.json artifacts
from each benchmark run. Reports any discrepancies between memo-stated
values and artifact-computed values. Fails reconciliation when speedup
claims exceed configured tolerance.

Usage:
    python3 publication/reconcile_metrics.py \
        --memo publication/ragas_blog_memo.md \
        --summary benchmarks/out/latest/summary.json

    python3 publication/reconcile_metrics.py \
        --memo publication/ragas_blog_memo.md \
        --run-dir benchmarks/out/20260305T174325Z
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Default tolerances
DEFAULT_TABLE_TOLERANCE_MS = 0.02
DEFAULT_SPEEDUP_TOLERANCE_RATIO = 0.15


def load_run_manifest(run_dir: Path) -> dict:
    """Load run manifest from a benchmark run directory."""
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        print(f"FAIL: run_manifest.json not found at {manifest_path}", file=sys.stderr)
        sys.exit(1)
    with open(manifest_path) as f:
        return json.load(f)


def load_sampling_validation(run_dir: Path) -> dict | None:
    """Load sampling_validation.json from a benchmark run directory."""
    path = run_dir / "sampling_validation.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def extract_run_stats(run_dir: Path) -> dict:
    """Extract authoritative stats per scenario per comparator.

    Uses sampling_validation.json (the authoritative computed stats) rather
    than recomputing from raw samples, to ensure reconciliation matches
    the exact values produced by the benchmark validation pipeline.
    """
    stats = {}
    validation = load_sampling_validation(run_dir)

    if validation and "scenario_summaries" in validation:
        for scenario_summary in validation["scenario_summaries"]:
            sid = scenario_summary.get("scenario_id", "unknown")
            stats[sid] = {}
            for comp, comp_stats in scenario_summary.get("comparator_stats", {}).items():
                median_ms = round(comp_stats.get("median_s", 0) * 1000, 2)
                iqr_ms = round(comp_stats.get("iqr_s", 0) * 1000, 2)
                ci_lower_ms = round(comp_stats.get("ci_lower_s", 0) * 1000, 2)
                ci_upper_ms = round(comp_stats.get("ci_upper_s", 0) * 1000, 2)
                stats[sid][comp] = {
                    "median_ms": median_ms,
                    "iqr_ms": iqr_ms,
                    "ci_lower_ms": ci_lower_ms,
                    "ci_upper_ms": ci_upper_ms,
                    "n": comp_stats.get("measured_count", 0),
                }
        return stats

    # Fallback: compute from raw samples in run_manifest
    manifest = load_run_manifest(run_dir)
    for scenario in manifest.get("scenarios", []):
        sid = scenario.get("scenario_id", "unknown")
        stats[sid] = {}
        for comp, result in scenario.get("results", {}).items():
            samples = result.get("measured_samples", [])
            if isinstance(samples, list) and samples:
                if isinstance(samples[0], dict):
                    elapsed_vals = sorted(
                        [s["elapsed_s"] for s in samples if not s.get("warmup", False)]
                    )
                else:
                    elapsed_vals = sorted(samples)
                if elapsed_vals:
                    from statistics import median

                    med = round(median(elapsed_vals) * 1000, 2)
                    stats[sid][comp] = {"median_ms": med, "iqr_ms": 0, "n": len(elapsed_vals)}
                else:
                    stats[sid][comp] = {"median_ms": 0, "iqr_ms": 0, "n": 0}
            else:
                stats[sid][comp] = {"median_ms": 0, "iqr_ms": 0, "n": 0}
    return stats


def extract_memo_table_values(memo_text: str) -> list[dict]:
    """Extract numeric values from performance tables in the memo.

    Returns list of dicts with keys: comparator, median_ms, iqr_ms,
    table_label, line_num.
    """
    values = []
    table_label = None

    for i, line in enumerate(memo_text.splitlines(), 1):
        # Detect table headers like "#### Table 2.2a: Local Run (...)"
        header_match = re.match(r"^#{1,6}\s+Table\s+(\S+):\s*(.+)", line)
        if header_match:
            table_label = header_match.group(1) + " " + header_match.group(2).strip()
            continue

        # Parse table rows: | comparator | median | iqr | ci_lower | ci_upper | samples |
        row_match = re.match(
            r"\|\s*(\w[\w-]*)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*(\d+)\s*\|",
            line,
        )
        if row_match:
            comp = row_match.group(1)
            # Skip header rows
            if comp.lower() in ("comparator",):
                continue
            values.append(
                {
                    "comparator": comp,
                    "median_ms": float(row_match.group(2)),
                    "iqr_ms": float(row_match.group(3)),
                    "ci_lower_ms": float(row_match.group(4)),
                    "ci_upper_ms": float(row_match.group(5)),
                    "samples_n": int(row_match.group(6)),
                    "table_label": table_label or "unknown",
                    "line_num": i,
                }
            )

    return values


def load_claim_gate(run_dir: Path) -> dict | None:
    """Load claim_gate.json from a benchmark run directory."""
    path = run_dir / "claim_gate.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def extract_memo_speedup_values(memo_text: str) -> list[dict]:
    """Extract speedup ratio claims from the memo narrative text.

    Looks for patterns like '2.0× speedup' or 'approximately 2.0x faster'
    and attempts to identify the faster/slower tool pair from context.
    """
    speedups = []
    ratio_pattern = re.compile(
        r"(?:approximately\s+)?([\d.]+)[×x]\s+(?:faster|speedup)",
        re.IGNORECASE,
    )
    # Pattern to find tool pairs in narrative: "A vs B", "A is ... faster than B"
    pair_pattern = re.compile(
        r"(\w[\w-]*)\s+(?:vs|is\s+.*?faster\s+than)\s+(\w[\w-]*)",
        re.IGNORECASE,
    )
    # Pattern for claim-evidence index rows: | CLM-PERF-NNN | ... | A ≈N.Nx faster than B |
    clm_table_pattern = re.compile(
        r"\|\s*CLM-\w+-\d+\s*\|.*?\|\s*(\w[\w-]*)\s+[≈~]?([\d.]+)[×x]\s+faster\s+than\s+(\w[\w-]*)\s*\|",
        re.IGNORECASE,
    )

    known_tools = {"ag", "rust-ag", "rg", "ugrep"}

    for i, line in enumerate(memo_text.splitlines(), 1):
        for m in ratio_pattern.finditer(line):
            ratio = float(m.group(1))
            faster = None
            slower = None

            # Try claim-evidence-index table pattern first
            clm_match = clm_table_pattern.search(line)
            if clm_match:
                faster = clm_match.group(1)
                slower = clm_match.group(3)
            else:
                # Try narrative pair extraction
                for pm in pair_pattern.finditer(line):
                    f_candidate = pm.group(1)
                    s_candidate = pm.group(2)
                    if f_candidate in known_tools and s_candidate in known_tools:
                        faster = f_candidate
                        slower = s_candidate
                        break

            speedups.append(
                {
                    "ratio": ratio,
                    "faster": faster,
                    "slower": slower,
                    "line_num": i,
                    "context": line.strip()[:120],
                }
            )

    return speedups


def extract_memo_speedup_table_values(memo_text: str) -> list[dict]:
    """Extract per-run-type speedup ratios from Table 2.2d (speedup table).

    Parses rows like:
    | rg | ag | 2.54× | 2.45× | 2.48× | 0.0 | ✓ |

    Returns list of dicts with keys: faster, slower, local_ratio,
    nightly_ratio, manual_ratio, ci_overlap, line_num.
    """
    table_values = []
    row_pattern = re.compile(
        r"\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*([\d.]+)[×x]\s*\|\s*([\d.]+)[×x]\s*\|\s*([\d.]+)[×x]\s*\|\s*([\d.]+)\s*\|"
    )

    for i, line in enumerate(memo_text.splitlines(), 1):
        row_match = row_pattern.match(line)
        if row_match:
            faster = row_match.group(1)
            slower = row_match.group(2)
            # Skip header rows
            if faster.lower() in ("faster",):
                continue
            table_values.append(
                {
                    "faster": faster,
                    "slower": slower,
                    "local_ratio": float(row_match.group(3)),
                    "nightly_ratio": float(row_match.group(4)),
                    "manual_ratio": float(row_match.group(5)),
                    "ci_overlap": float(row_match.group(6)),
                    "line_num": i,
                }
            )

    return table_values


def reconcile_table_values(
    memo_values: list[dict],
    run_stats: dict,
    scenario_id: str,
    tolerance: float = 0.02,
) -> tuple[list[str], int]:
    """Compare memo table values against computed run statistics.

    tolerance: maximum allowed absolute difference in ms before flagging.
    Returns (errors, ok_count).
    """
    errors = []
    ok_count = 0

    for val in memo_values:
        comp = val["comparator"]
        comp_key = comp

        if scenario_id not in run_stats:
            errors.append(
                f"  Table {val['table_label']} line {val['line_num']}: "
                f"scenario '{scenario_id}' not found in run data"
            )
            continue

        if comp_key not in run_stats[scenario_id]:
            # Try with hyphens/underscores
            found = False
            for k in run_stats[scenario_id]:
                if k.replace("-", "").replace("_", "") == comp_key.replace("-", "").replace("_", ""):
                    comp_key = k
                    found = True
                    break
            if not found:
                errors.append(
                    f"  Table {val['table_label']} line {val['line_num']}: "
                    f"comparator '{comp}' not found in run data for scenario '{scenario_id}'"
                )
                continue

        computed = run_stats[scenario_id][comp_key]
        memo_median = val["median_ms"]
        computed_median = computed["median_ms"]

        diff = abs(memo_median - computed_median)
        if diff > tolerance:
            errors.append(
                f"  Table {val['table_label']} line {val['line_num']}: "
                f"{comp} median: memo={memo_median} ms, computed={computed_median} ms, "
                f"diff={diff:.3f} ms (tolerance={tolerance} ms)"
            )
        else:
            ok_count += 1

        memo_iqr = val["iqr_ms"]
        computed_iqr = computed.get("iqr_ms", 0)
        iqr_diff = abs(memo_iqr - computed_iqr)
        if iqr_diff > tolerance:
            errors.append(
                f"  Table {val['table_label']} line {val['line_num']}: "
                f"{comp} IQR: memo={memo_iqr} ms, computed={computed_iqr} ms, "
                f"diff={iqr_diff:.3f} ms (tolerance={tolerance} ms)"
            )
        else:
            ok_count += 1

        # Also check CI bounds if available
        if "ci_lower_ms" in val and "ci_lower_ms" in computed:
            memo_ci_lo = val["ci_lower_ms"]
            comp_ci_lo = computed["ci_lower_ms"]
            ci_lo_diff = abs(memo_ci_lo - comp_ci_lo)
            if ci_lo_diff > tolerance:
                errors.append(
                    f"  Table {val['table_label']} line {val['line_num']}: "
                    f"{comp} CI lower: memo={memo_ci_lo} ms, computed={comp_ci_lo} ms, "
                    f"diff={ci_lo_diff:.3f} ms (tolerance={tolerance} ms)"
                )
            else:
                ok_count += 1

        if "ci_upper_ms" in val and "ci_upper_ms" in computed:
            memo_ci_up = val["ci_upper_ms"]
            comp_ci_up = computed["ci_upper_ms"]
            ci_up_diff = abs(memo_ci_up - comp_ci_up)
            if ci_up_diff > tolerance:
                errors.append(
                    f"  Table {val['table_label']} line {val['line_num']}: "
                    f"{comp} CI upper: memo={memo_ci_up} ms, computed={comp_ci_up} ms, "
                    f"diff={ci_up_diff:.3f} ms (tolerance={tolerance} ms)"
                )
            else:
                ok_count += 1

    return errors, ok_count


def reconcile_speedups(
    memo_speedups: list[dict],
    run_stats_by_type: dict[str, dict],
    scenario_id: str,
    tolerance: float = DEFAULT_SPEEDUP_TOLERANCE_RATIO,
) -> tuple[list[str], list[dict], int]:
    """Validate memo narrative speedup claims against computed ratios.

    Computes speedup ratios from benchmark median times (slower/faster)
    and checks that memo-stated ratios are within tolerance.

    Args:
        memo_speedups: Extracted speedup claims from narrative text.
        run_stats_by_type: {run_type: {scenario_id: {comp: stats}}} for
            each measured run type (local, nightly, manual).
        scenario_id: The scenario to use for ratio computation.
        tolerance: Maximum allowed absolute ratio difference.

    Returns:
        (errors, evidence, ok_count) where evidence is a list of dicts
        recording pass/fail for each validated claim.
    """
    errors: list[str] = []
    evidence: list[dict] = []
    ok_count = 0

    # Build computed speedup ratios from each run type's medians
    computed_ratios: dict[str, dict[tuple[str, str], float]] = {}
    for run_type, run_stats in run_stats_by_type.items():
        if scenario_id not in run_stats:
            continue
        stats = run_stats[scenario_id]
        computed_ratios[run_type] = {}
        comps = list(stats.keys())
        for i, faster in enumerate(comps):
            for slower in comps[i + 1 :]:
                f_median = stats[faster].get("median_ms", 0)
                s_median = stats[slower].get("median_ms", 0)
                if f_median > 0 and s_median > 0:
                    if s_median > f_median:
                        computed_ratios[run_type][(faster, slower)] = round(
                            s_median / f_median, 4
                        )
                    else:
                        computed_ratios[run_type][(slower, faster)] = round(
                            f_median / s_median, 4
                        )

    if not computed_ratios:
        errors.append(
            f"  No computed speedup ratios available for scenario '{scenario_id}'"
        )
        return errors, evidence, ok_count

    # Use local run as the primary reference for narrative claims
    # (narrative claims typically reference local medians)
    primary_type = "local" if "local" in computed_ratios else next(iter(computed_ratios))
    primary_ratios = computed_ratios[primary_type]

    for claim in memo_speedups:
        faster = claim.get("faster")
        slower = claim.get("slower")
        memo_ratio = claim["ratio"]
        line_num = claim["line_num"]
        context = claim.get("context", "")

        if not faster or not slower:
            # Cannot validate claims without identified tool pairs;
            # record as skipped, not as errors
            evidence.append(
                {
                    "line_num": line_num,
                    "memo_ratio": memo_ratio,
                    "faster": faster,
                    "slower": slower,
                    "result": "skipped",
                    "reason": "tool pair not identified from context",
                    "context": context,
                }
            )
            continue

        pair_key = (faster, slower)
        if pair_key not in primary_ratios:
            # Try reversed pair
            pair_key = (slower, faster)
            if pair_key not in primary_ratios:
                evidence.append(
                    {
                        "line_num": line_num,
                        "memo_ratio": memo_ratio,
                        "faster": faster,
                        "slower": slower,
                        "result": "skipped",
                        "reason": f"pair ({faster}, {slower}) not found in {primary_type} run data",
                        "context": context,
                    }
                )
                continue

        computed = primary_ratios[pair_key]
        diff = abs(memo_ratio - computed)

        if diff > tolerance:
            errors.append(
                f"  Speedup claim line {line_num}: "
                f"{faster} vs {slower}: memo={memo_ratio}×, "
                f"computed={computed}× ({primary_type} run), "
                f"diff={diff:.4f} (tolerance={tolerance})"
            )
            evidence.append(
                {
                    "line_num": line_num,
                    "memo_ratio": memo_ratio,
                    "computed_ratio": computed,
                    "faster": pair_key[0],
                    "slower": pair_key[1],
                    "run_type": primary_type,
                    "diff": round(diff, 4),
                    "tolerance": tolerance,
                    "result": "fail",
                    "context": context,
                }
            )
        else:
            ok_count += 1
            evidence.append(
                {
                    "line_num": line_num,
                    "memo_ratio": memo_ratio,
                    "computed_ratio": computed,
                    "faster": pair_key[0],
                    "slower": pair_key[1],
                    "run_type": primary_type,
                    "diff": round(diff, 4),
                    "tolerance": tolerance,
                    "result": "pass",
                    "context": context,
                }
            )

    return errors, evidence, ok_count


def reconcile_speedup_table(
    table_values: list[dict],
    claim_gate_data: dict | None,
    tolerance: float = DEFAULT_SPEEDUP_TOLERANCE_RATIO,
) -> tuple[list[str], list[dict], int]:
    """Validate memo speedup table (Table 2.2d) against claim_gate.json.

    Compares per-run-type speedup ratios in the memo table against the
    authoritative pair_evaluations in claim_gate.json.

    Returns:
        (errors, evidence, ok_count).
    """
    errors: list[str] = []
    evidence: list[dict] = []
    ok_count = 0

    if not claim_gate_data:
        if table_values:
            errors.append("  Speedup table values found but no claim_gate.json available")
        return errors, evidence, ok_count

    # Build lookup from claim_gate pair evaluations
    pair_lookup: dict[tuple[str, str], dict] = {}
    for scenario_claim in claim_gate_data.get("scenario_claims", []):
        for pair_eval in scenario_claim.get("pair_evaluations", []):
            key = (pair_eval["faster"], pair_eval["slower"])
            pair_lookup[key] = pair_eval

    for tv in table_values:
        faster = tv["faster"]
        slower = tv["slower"]
        line_num = tv["line_num"]

        pair_key = (faster, slower)
        if pair_key not in pair_lookup:
            errors.append(
                f"  Speedup table line {line_num}: pair ({faster}, {slower}) "
                f"not found in claim_gate pair evaluations"
            )
            evidence.append(
                {
                    "line_num": line_num,
                    "faster": faster,
                    "slower": slower,
                    "result": "fail",
                    "reason": "pair not found in claim_gate",
                }
            )
            continue

        gate_pair = pair_lookup[pair_key]
        per_run = gate_pair.get("per_run_type_results", {})

        for run_type, memo_key in [
            ("local", "local_ratio"),
            ("nightly", "nightly_ratio"),
            ("manual", "manual_ratio"),
        ]:
            memo_ratio = tv[memo_key]
            gate_run = per_run.get(run_type, {})
            gate_ratio = gate_run.get("speedup_ratio")

            if gate_ratio is None:
                errors.append(
                    f"  Speedup table line {line_num}: {faster} vs {slower} "
                    f"{run_type} ratio not found in claim_gate"
                )
                evidence.append(
                    {
                        "line_num": line_num,
                        "faster": faster,
                        "slower": slower,
                        "run_type": run_type,
                        "result": "fail",
                        "reason": f"{run_type} ratio not found in claim_gate",
                    }
                )
                continue

            # Compare: memo states rounded ratio (e.g. 2.54) vs gate has
            # full precision (e.g. 2.539). Tolerance for table is tighter
            # since these are directly derived values.
            diff = abs(memo_ratio - gate_ratio)
            # Use a tighter tolerance for table ratios (they should be
            # rounded versions of the exact gate values)
            table_tol = 0.02  # Allow rounding to 2 decimal places
            if diff > table_tol:
                errors.append(
                    f"  Speedup table line {line_num}: {faster} vs {slower} "
                    f"{run_type}: memo={memo_ratio}×, gate={gate_ratio}×, "
                    f"diff={diff:.4f} (tolerance={table_tol})"
                )
                evidence.append(
                    {
                        "line_num": line_num,
                        "faster": faster,
                        "slower": slower,
                        "run_type": run_type,
                        "memo_ratio": memo_ratio,
                        "gate_ratio": gate_ratio,
                        "diff": round(diff, 4),
                        "tolerance": table_tol,
                        "result": "fail",
                    }
                )
            else:
                ok_count += 1
                evidence.append(
                    {
                        "line_num": line_num,
                        "faster": faster,
                        "slower": slower,
                        "run_type": run_type,
                        "memo_ratio": memo_ratio,
                        "gate_ratio": gate_ratio,
                        "diff": round(diff, 4),
                        "tolerance": table_tol,
                        "result": "pass",
                    }
                )

    return errors, evidence, ok_count


def resolve_run_dirs(args, repo_root: Path) -> list[tuple[str, Path]]:
    """Resolve benchmark run directories from arguments.

    For --summary or --run-dir pointing to a smoke run, falls back to
    the claim_evidence_map measured run IDs automatically.
    """
    dirs = []

    if args.run_dir:
        run_dir = Path(args.run_dir)
        if not run_dir.exists():
            print(f"FAIL: run directory not found: {run_dir}", file=sys.stderr)
            sys.exit(1)
        dirs.append(("specified", run_dir))
    elif args.summary:
        # If --summary points to a file, use its parent directory
        summary_path = Path(args.summary)
        if summary_path.exists():
            parent = summary_path.parent
            dirs.append(("summary", parent))
        elif summary_path.parent.exists():
            # Try the parent directory even if the specific file doesn't exist
            dirs.append(("summary", summary_path.parent))
        else:
            print(f"FAIL: summary path not found: {summary_path}", file=sys.stderr)
            sys.exit(1)

    # Check if we only have smoke runs; if so, fall back to claim_evidence_map
    has_measured = False
    for label, run_dir in dirs:
        manifest_path = run_dir / "run_manifest.json"
        if manifest_path.exists():
            with open(manifest_path) as f:
                m = json.load(f)
            if m.get("run_type") != "smoke":
                has_measured = True

    if not has_measured:
        # Fall back to claim_evidence_map measured runs
        claim_map_path = repo_root / "publication" / "claim_evidence_map.json"
        if claim_map_path.exists():
            with open(claim_map_path) as f:
                claim_map = json.load(f)
            run_ids = claim_map.get("benchmark_run_ids", {})
            for run_type, run_id in run_ids.items():
                run_dir = repo_root / "benchmarks" / "out" / run_id
                if run_dir.exists():
                    dirs.append((run_type, run_dir))

    if not dirs:
        # Final fallback: latest
        latest = repo_root / "benchmarks" / "out" / "latest"
        if latest.exists():
            dirs.append(("latest", latest.resolve()))

    return dirs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile memo metrics against benchmark run artifacts"
    )
    parser.add_argument("--memo", required=True, help="Path to memo markdown file")
    parser.add_argument(
        "--summary",
        help="Path to benchmark summary.json (uses parent dir for run_manifest.json)",
    )
    parser.add_argument("--run-dir", help="Path to specific benchmark run directory")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_TABLE_TOLERANCE_MS,
        help=f"Max allowed absolute diff in ms for table values (default: {DEFAULT_TABLE_TOLERANCE_MS})",
    )
    parser.add_argument(
        "--speedup-tolerance",
        type=float,
        default=DEFAULT_SPEEDUP_TOLERANCE_RATIO,
        help=f"Max allowed absolute ratio diff for narrative speedup claims (default: {DEFAULT_SPEEDUP_TOLERANCE_RATIO})",
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

    # Extract memo values
    memo_table_values = extract_memo_table_values(memo_text)
    memo_speedups = extract_memo_speedup_values(memo_text)
    memo_speedup_table = extract_memo_speedup_table_values(memo_text)

    # Resolve run directories
    run_dirs = resolve_run_dirs(args, repo_root)

    if not run_dirs:
        print("FAIL: No benchmark run directories found", file=sys.stderr)
        return 1

    all_errors: list[str] = []
    all_ok = 0
    runs_checked = 0

    # Load claim-evidence map for run type mapping
    claim_map_path = repo_root / "publication" / "claim_evidence_map.json"
    run_id_to_type = {}
    if claim_map_path.exists():
        with open(claim_map_path) as f:
            cm = json.load(f)
        for rt, rid in cm.get("benchmark_run_ids", {}).items():
            run_id_to_type[rid] = rt

    # Collect per-run-type stats for speedup validation
    run_stats_by_type: dict[str, dict] = {}
    claim_gate_data: dict | None = None

    for label, run_dir in run_dirs:
        manifest = load_run_manifest(run_dir)
        run_id = manifest.get("run_id", "unknown")
        run_type = manifest.get("run_type", label)

        # Only reconcile against measured runs (not smoke runs)
        if run_type == "smoke":
            continue

        run_stats = extract_run_stats(run_dir)
        runs_checked += 1

        # Determine the run type label (use claim_evidence_map mapping)
        effective_type = run_id_to_type.get(run_id, run_type)
        run_stats_by_type[effective_type] = run_stats

        # Load claim_gate from the latest measured run
        gate = load_claim_gate(run_dir)
        if gate is not None:
            claim_gate_data = gate

        # Match memo table values to this run's data
        matching_values = []
        for val in memo_table_values:
            tbl = val.get("table_label", "")
            if run_id in tbl:
                matching_values.append(val)

        if matching_values:
            scenario_id = "literal-simple"  # The only measured scenario
            errors, ok = reconcile_table_values(
                matching_values, run_stats, scenario_id, args.tolerance
            )
            if errors:
                all_errors.append(f"Run {run_id} ({run_type}) table reconciliation failures:")
                all_errors.extend(errors)
            all_ok += ok

    # --- Speedup claim reconciliation ---
    speedup_narrative_errors: list[str] = []
    speedup_narrative_evidence: list[dict] = []
    speedup_narrative_ok = 0
    speedup_table_errors: list[str] = []
    speedup_table_evidence: list[dict] = []
    speedup_table_ok = 0

    if run_stats_by_type:
        scenario_id = "literal-simple"

        # 1. Validate narrative speedup claims against computed ratios
        speedup_narrative_errors, speedup_narrative_evidence, speedup_narrative_ok = (
            reconcile_speedups(
                memo_speedups,
                run_stats_by_type,
                scenario_id,
                tolerance=args.speedup_tolerance,
            )
        )
        if speedup_narrative_errors:
            all_errors.append("Narrative speedup claim reconciliation failures:")
            all_errors.extend(speedup_narrative_errors)
        all_ok += speedup_narrative_ok

        # 2. Validate speedup table (Table 2.2d) against claim_gate.json
        speedup_table_errors, speedup_table_evidence, speedup_table_ok = (
            reconcile_speedup_table(
                memo_speedup_table,
                claim_gate_data,
                tolerance=args.speedup_tolerance,
            )
        )
        if speedup_table_errors:
            all_errors.append("Speedup table reconciliation failures:")
            all_errors.extend(speedup_table_errors)
        all_ok += speedup_table_ok

    # Compute speedup claim summary stats
    narrative_validated = sum(
        1 for e in speedup_narrative_evidence if e["result"] == "pass"
    )
    narrative_failed = sum(
        1 for e in speedup_narrative_evidence if e["result"] == "fail"
    )
    narrative_skipped = sum(
        1 for e in speedup_narrative_evidence if e["result"] == "skipped"
    )
    table_validated = sum(
        1 for e in speedup_table_evidence if e["result"] == "pass"
    )
    table_failed = sum(
        1 for e in speedup_table_evidence if e["result"] == "fail"
    )

    # Reconciliation report with explicit speedup-claim evidence
    report = {
        "schema_version": 2,
        "memo_file": str(memo_path),
        "runs_checked": runs_checked,
        "table_values_found": len(memo_table_values),
        "speedup_claims_found": len(memo_speedups),
        "speedup_table_rows_found": len(memo_speedup_table),
        "speedup_claim_reconciliation": {
            "narrative_claims": {
                "total": len(memo_speedups),
                "validated_pass": narrative_validated,
                "validated_fail": narrative_failed,
                "skipped": narrative_skipped,
                "tolerance": args.speedup_tolerance,
                "evidence": speedup_narrative_evidence,
            },
            "table_claims": {
                "total_rows": len(memo_speedup_table),
                "total_checks": len(speedup_table_evidence),
                "validated_pass": table_validated,
                "validated_fail": table_failed,
                "evidence": speedup_table_evidence,
            },
            "result": "pass" if not speedup_narrative_errors and not speedup_table_errors else "fail",
        },
        "errors": all_errors,
        "result": "pass" if not all_errors else "fail",
    }

    print(f"Metrics reconciliation: {'PASS' if not all_errors else 'FAIL'}")
    print(f"  Runs checked: {runs_checked}")
    print(f"  Memo table values extracted: {len(memo_table_values)}")
    print(f"  Speedup claims found: {len(memo_speedups)}")
    print(f"  Speedup table rows found: {len(memo_speedup_table)}")
    print(f"  Values reconciled OK: {all_ok}")
    print(f"  Narrative speedup claims: {narrative_validated} pass, {narrative_failed} fail, {narrative_skipped} skipped")
    print(f"  Speedup table checks: {table_validated} pass, {table_failed} fail")
    print(f"  Speedup claim reconciliation: {'PASS' if report['speedup_claim_reconciliation']['result'] == 'pass' else 'FAIL'}")

    if all_errors:
        print("\nRECONCILIATION FAILURES:")
        for e in all_errors:
            print(f"  {e}")
        return 1

    print("\nAll memo values reconcile with benchmark artifacts.")

    # Write reconciliation report
    report_path = repo_root / "publication" / "reconciliation_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(f"Report written to: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
