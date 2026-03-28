#!/usr/bin/env python3
"""Manifest hash pinning and reproducibility reporting.

VAL-BENCH-003: Input corpus/query manifests are immutable.
    Benchmark runs reference corpus and query manifests with hashes;
    compared runs use identical manifest hashes.

Provides:
  - compare_manifest_hashes() — compare manifest hashes between two runs.
  - verify_manifest_hashes_on_disk() — verify run hashes against on-disk manifests.

Usage:
    python3 benchmarks/manifest_pinning.py --run-a latest --run-b 20260305T120000Z
    python3 benchmarks/manifest_pinning.py --verify-on-disk --run latest
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
MANIFESTS_DIR = REPO_ROOT / "manifests"

# The required manifest names that must be present and pinned.
REQUIRED_MANIFESTS = ("scenarios", "queries", "corpus")


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


def compare_manifest_hashes(
    run_a: dict[str, Any],
    run_b: dict[str, Any],
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Compare manifest hashes between two benchmark runs.

    Returns a reproducibility report with pass/fail result.

    Args:
        run_a: First run manifest dict.
        run_b: Second run manifest dict.
        output_dir: Optional directory to write the report artifact.

    Returns:
        Report dict with result, mismatches, and hash details.
    """
    hashes_a = run_a.get("manifest_hashes", {})
    hashes_b = run_b.get("manifest_hashes", {})

    mismatches: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []

    # Check that all required manifests are present.
    any_missing = False
    for name in REQUIRED_MANIFESTS:
        hash_a = hashes_a.get(name, "")
        hash_b = hashes_b.get(name, "")

        if not hash_a and not hash_b:
            any_missing = True
            mismatches.append({
                "manifest": name,
                "issue": "missing_in_both",
                "run_a_hash": hash_a,
                "run_b_hash": hash_b,
            })
            comparisons.append({
                "manifest": name,
                "match": False,
                "run_a_hash": hash_a,
                "run_b_hash": hash_b,
                "issue": "missing_in_both",
            })
        elif not hash_a:
            any_missing = True
            mismatches.append({
                "manifest": name,
                "issue": "missing_in_run_a",
                "run_a_hash": hash_a,
                "run_b_hash": hash_b,
            })
            comparisons.append({
                "manifest": name,
                "match": False,
                "run_a_hash": hash_a,
                "run_b_hash": hash_b,
                "issue": "missing_in_run_a",
            })
        elif not hash_b:
            any_missing = True
            mismatches.append({
                "manifest": name,
                "issue": "missing_in_run_b",
                "run_a_hash": hash_a,
                "run_b_hash": hash_b,
            })
            comparisons.append({
                "manifest": name,
                "match": False,
                "run_a_hash": hash_a,
                "run_b_hash": hash_b,
                "issue": "missing_in_run_b",
            })
        elif hash_a != hash_b:
            mismatches.append({
                "manifest": name,
                "issue": "hash_mismatch",
                "run_a_hash": hash_a,
                "run_b_hash": hash_b,
            })
            comparisons.append({
                "manifest": name,
                "match": False,
                "run_a_hash": hash_a,
                "run_b_hash": hash_b,
                "issue": "hash_mismatch",
            })
        else:
            comparisons.append({
                "manifest": name,
                "match": True,
                "hash": hash_a,
            })

    result = "fail" if mismatches else "pass"

    report = {
        "schema_version": 1,
        "result": result,
        "timestamp": _now_iso(),
        "run_a_id": run_a.get("run_id", "unknown"),
        "run_b_id": run_b.get("run_id", "unknown"),
        "comparisons": comparisons,
        "mismatches": mismatches,
    }

    if output_dir:
        _write_json(output_dir / "reproducibility_report.json", report)

    return report


def verify_manifest_hashes_on_disk(
    run_manifest: dict[str, Any],
    manifests_dir: Path | None = None,
) -> dict[str, Any]:
    """Verify that run manifest hashes match current on-disk manifests.

    Args:
        run_manifest: The benchmark run manifest dict.
        manifests_dir: Path to the manifests directory. Defaults to repo manifests/.

    Returns:
        A dict with result and mismatch details.
    """
    if manifests_dir is None:
        manifests_dir = MANIFESTS_DIR

    recorded = run_manifest.get("manifest_hashes", {})
    mismatches: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []

    manifest_files = {
        "scenarios": manifests_dir / "scenarios.json",
        "queries": manifests_dir / "queries.json",
        "corpus": manifests_dir / "corpus.json",
    }

    for name, path in manifest_files.items():
        recorded_hash = recorded.get(name, "")
        if not path.exists():
            mismatches.append({
                "manifest": name,
                "issue": "file_not_found",
                "recorded_hash": recorded_hash,
                "on_disk_hash": "",
            })
            comparisons.append({
                "manifest": name,
                "match": False,
                "recorded_hash": recorded_hash,
                "on_disk_hash": "",
                "issue": "file_not_found",
            })
            continue

        on_disk = _load_json(path)
        on_disk_hash = on_disk.get("manifest_hash", "")

        if recorded_hash != on_disk_hash:
            mismatches.append({
                "manifest": name,
                "issue": "hash_mismatch",
                "recorded_hash": recorded_hash,
                "on_disk_hash": on_disk_hash,
            })
            comparisons.append({
                "manifest": name,
                "match": False,
                "recorded_hash": recorded_hash,
                "on_disk_hash": on_disk_hash,
                "issue": "hash_mismatch",
            })
        else:
            comparisons.append({
                "manifest": name,
                "match": True,
                "hash": recorded_hash,
            })

    result = "fail" if mismatches else "pass"

    return {
        "result": result,
        "comparisons": comparisons,
        "mismatches": mismatches,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def resolve_run_dir(run_id: str | None, run_dir: str | None) -> Path:
    """Resolve run directory from run ID or explicit path.

    Delegates to the hardened resolver in ``run_resolution`` which filters
    out transient temp directories when resolving ``--run latest``.
    """
    from run_resolution import resolve_run_dir as _resolve

    return _resolve(run_id, run_dir, benchmarks_out=BENCHMARKS_OUT)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manifest hash pinning and reproducibility verification."
    )
    subparsers = parser.add_subparsers(dest="subcommand")

    # compare subcommand: compare two runs.
    compare_parser = subparsers.add_parser(
        "compare", help="Compare manifest hashes between two runs"
    )
    compare_parser.add_argument("--run-a", required=True, help="First run ID")
    compare_parser.add_argument("--run-b", required=True, help="Second run ID")
    compare_parser.add_argument("--output-dir", help="Output directory for report")

    # verify subcommand: check against on-disk manifests.
    verify_parser = subparsers.add_parser(
        "verify", help="Verify run hashes against on-disk manifests"
    )
    verify_parser.add_argument(
        "--run", type=str, default="latest", help="Run ID to verify"
    )
    verify_parser.add_argument("--run-dir", type=str, help="Explicit run dir path")

    args = parser.parse_args()

    if args.subcommand == "compare":
        dir_a = resolve_run_dir(args.run_a, None)
        dir_b = resolve_run_dir(args.run_b, None)
        manifest_a = _load_json(dir_a / "run_manifest.json")
        manifest_b = _load_json(dir_b / "run_manifest.json")
        output = Path(args.output_dir) if args.output_dir else dir_b
        report = compare_manifest_hashes(manifest_a, manifest_b, output)

        print(f"\nReproducibility Report: {report['result'].upper()}")
        print(f"  Run A: {report['run_a_id']}")
        print(f"  Run B: {report['run_b_id']}")
        for comp in report["comparisons"]:
            status = "✓" if comp["match"] else "✗"
            print(f"  {status} {comp['manifest']}")
        if report["mismatches"]:
            for m in report["mismatches"]:
                print(f"    MISMATCH: {m['manifest']} — {m['issue']}")

        sys.exit(0 if report["result"] == "pass" else 1)

    elif args.subcommand == "verify":
        run_dir = resolve_run_dir(args.run, args.run_dir)
        manifest = _load_json(run_dir / "run_manifest.json")
        report = verify_manifest_hashes_on_disk(manifest)

        print(f"\nOn-Disk Manifest Verification: {report['result'].upper()}")
        for comp in report["comparisons"]:
            status = "✓" if comp["match"] else "✗"
            print(f"  {status} {comp['manifest']}")
        if report["mismatches"]:
            for m in report["mismatches"]:
                print(f"    MISMATCH: {m['manifest']} — {m['issue']}")
                print(f"      Recorded: {m.get('recorded_hash', '')[:24]}…")
                print(f"      On-disk:  {m.get('on_disk_hash', '')[:24]}…")

        sys.exit(0 if report["result"] == "pass" else 1)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
