#!/usr/bin/env python3
"""Correctness gate: blocks benchmark performance claims on failing scenarios.

VAL-BENCH-004: Correctness gate precedes performance claims.
    Scenarios used for performance claims pass output-consistency/correctness
    checks before benchmark comparison is accepted.

The correctness gate checks that for each non-skipped scenario, all comparators
produce the same stdout hash.  A scenario fails if:
  - Any comparator had an error (binary_not_found, timeout, etc.).
  - Comparator stdout hashes disagree.

Usage:
    python3 benchmarks/correctness_gate.py --run latest
    python3 benchmarks/correctness_gate.py --run-dir /path/to/run/dir
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_OUT = REPO_ROOT / "benchmarks" / "out"


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


def check_correctness(
    run_manifest: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Check output consistency across comparators for each scenario.

    Correctness checking uses two tiers:
    1. **Parity check** (hard gate): The Rust rewrite ('rust-ag') must produce
       the same stdout hash as the baseline ('ag').  This is the core
       correctness gate that blocks benchmark claims.
    2. **Cross-tool check** (advisory): All comparators must execute without
       errors (no timeouts, no binary-not-found).  Stdout divergence across
       different tools (rg, ugrep) is expected (different output formats) and
       logged but does not fail the gate.

    Args:
        run_manifest: The benchmark run manifest dict.
        output_dir: Directory to write the correctness gate artifact.

    Returns:
        A dict with gate result, summary counts, and per-scenario detail.
    """
    # Parity pair whose stdout must agree.
    parity_pair = ("ag", "rust-ag")

    scenarios_checked = 0
    scenarios_passed = 0
    scenarios_failed = 0
    scenarios_skipped = 0
    scenario_details: list[dict[str, Any]] = []

    for scenario in run_manifest.get("scenarios", []):
        # Skip fully-skipped scenarios.
        if scenario.get("skipped", False):
            scenarios_skipped += 1
            continue

        sid = scenario.get("scenario_id", "unknown")
        results = scenario.get("results", {})

        if not results:
            # No comparator results at all — skip.
            scenarios_skipped += 1
            continue

        scenarios_checked += 1

        # Collect per-cell status.
        errors: list[str] = []
        stdout_hashes: dict[str, str] = {}

        for comp, cell in results.items():
            if isinstance(cell, dict):
                if cell.get("skipped", False):
                    continue
                if cell.get("error"):
                    errors.append(
                        f"{comp}: {cell['error']} — {cell.get('stderr_excerpt', '')}"
                    )
                elif cell.get("timed_out", False):
                    errors.append(f"{comp}: timed out")
                else:
                    # Use sorted hash for order-independent parity check.
                    # Multi-threaded tools may produce lines in different order.
                    stdout_hashes[comp] = cell.get(
                        "stdout_sorted_hash",
                        cell.get("stdout_hash", ""),
                    )

        # --- Parity check: ag == rust-ag ---
        parity_pass = True
        parity_detail: dict[str, Any] = {}

        pair_present = all(p in stdout_hashes for p in parity_pair)
        if pair_present:
            ag_hash = stdout_hashes[parity_pair[0]]
            rust_hash = stdout_hashes[parity_pair[1]]
            if ag_hash != rust_hash:
                parity_pass = False
                parity_detail = {
                    parity_pair[0]: ag_hash,
                    parity_pair[1]: rust_hash,
                }
        else:
            # If either parity member is missing due to error, that's a fail.
            missing = [p for p in parity_pair if p not in stdout_hashes]
            if missing:
                parity_pass = False
                parity_detail = {"missing_parity_members": missing}

        # --- Overall pass: no execution errors AND parity check passes ---
        passed = len(errors) == 0 and parity_pass

        # Cross-tool stdout divergence (informational).
        all_hashes = set(stdout_hashes.values())

        detail: dict[str, Any] = {
            "scenario_id": sid,
            "result": "pass" if passed else "fail",
            "comparators_checked": list(stdout_hashes.keys()),
            "unique_stdout_hashes": len(all_hashes),
            "parity_pass": parity_pass,
        }

        if errors:
            detail["errors"] = errors
        if not parity_pass:
            detail["parity_divergence"] = parity_detail
        if len(all_hashes) > 1:
            detail["cross_tool_hashes"] = {
                comp: h for comp, h in stdout_hashes.items()
            }

        scenario_details.append(detail)

        if passed:
            scenarios_passed += 1
        else:
            scenarios_failed += 1

    gate_result = "pass" if scenarios_failed == 0 else "fail"

    gate_artifact = {
        "schema_version": 1,
        "gate": gate_result,
        "timestamp": _now_iso(),
        "commit_sha": run_manifest.get("commit_sha", "unknown"),
        "run_id": run_manifest.get("run_id", "unknown"),
        "manifest_hashes": run_manifest.get("manifest_hashes", {}),
        "parity_pair": list(parity_pair),
        "scenarios_checked": scenarios_checked,
        "scenarios_passed": scenarios_passed,
        "scenarios_failed": scenarios_failed,
        "scenarios_skipped": scenarios_skipped,
        "scenarios": scenario_details,
    }

    # Write artifact.
    _write_json(output_dir / "correctness_gate.json", gate_artifact)

    return gate_artifact


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
        description="Correctness gate: check output consistency before performance claims."
    )
    parser.add_argument(
        "--run",
        type=str,
        default=None,
        help="Run ID or 'latest' to check.",
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
    result = check_correctness(manifest, run_dir)

    # Print summary.
    print(f"\nCorrectness Gate: {result['gate'].upper()}")
    print(f"  Run: {result['run_id']}")
    print(f"  Commit: {result['commit_sha']}")
    print(f"  Scenarios checked: {result['scenarios_checked']}")
    print(f"  Passed: {result['scenarios_passed']}")
    print(f"  Failed: {result['scenarios_failed']}")
    print(f"  Skipped: {result['scenarios_skipped']}")

    if result["scenarios_failed"] > 0:
        print("\n  Failed scenarios:")
        for detail in result["scenarios"]:
            if detail["result"] == "fail":
                print(f"    - {detail['scenario_id']}")
                if "errors" in detail:
                    for err in detail["errors"]:
                        print(f"        {err}")
                if "parity_divergence" in detail:
                    print("        Parity divergence:")
                    for comp, h in detail["parity_divergence"].items():
                        if isinstance(h, str):
                            print(f"          {comp}: {h[:16]}…")
                        else:
                            print(f"          {comp}: {h}")

    print(f"\n  Gate artifact: {run_dir / 'correctness_gate.json'}")

    sys.exit(0 if result["gate"] == "pass" else 1)


if __name__ == "__main__":
    main()
