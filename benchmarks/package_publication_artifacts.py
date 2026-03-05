#!/usr/bin/env python3
"""Package publication-grade benchmark artifact bundles for public scrutiny.

Produces a publication bundle containing:
  - All raw benchmark artifacts (run manifest, tools metadata, environment
    metadata, command equivalence, correctness gate, sampling validation)
  - SHA-256 checksums for every artifact
  - A complete inclusion/exclusion ledger referencing the full scenario matrix
  - A publication manifest tying everything together

VAL-BENCH-008: Raw benchmark artifacts are publishable.
VAL-CROSS-006: Scenario coverage is complete in published results.

Usage:
    python3 benchmarks/package_publication_artifacts.py --run latest
    python3 benchmarks/package_publication_artifacts.py --run-dir /path/to/run
    python3 benchmarks/package_publication_artifacts.py --run-dir /path/to/run --output-dir /path/to/pub
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_OUT = REPO_ROOT / "benchmarks" / "out"
MANIFESTS_DIR = REPO_ROOT / "manifests"
SCENARIOS_PATH = MANIFESTS_DIR / "scenarios.json"

# Raw artifacts that must be present in a benchmark run directory.
REQUIRED_RAW_ARTIFACTS = [
    "run_manifest.json",
    "tools_metadata.json",
    "environment_metadata.json",
    "command_equivalence.json",
]

# Optional artifacts that are included if present.
OPTIONAL_RAW_ARTIFACTS = [
    "correctness_gate.json",
    "sampling_validation.json",
    "claim_gate.json",
    "reproducibility_report.json",
]

# Derived artifacts produced by this script.
DERIVED_ARTIFACTS = [
    "publication_manifest.json",
    "checksums.sha256",
    "inclusion_exclusion_ledger.json",
]


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


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Inclusion/exclusion ledger
# ---------------------------------------------------------------------------


def build_inclusion_exclusion_ledger(
    run_manifest: dict[str, Any],
    scenarios_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a complete inclusion/exclusion ledger for the benchmark run.

    The ledger covers:
    1. All scenarios present in the run manifest.
    2. If a scenarios_manifest is provided, all registered scenarios —
       marking those not present in the run as excluded.

    Args:
        run_manifest: The benchmark run manifest.
        scenarios_manifest: Optional full scenarios manifest (scenarios.json)
            for coverage completeness.

    Returns:
        The inclusion/exclusion ledger dict.
    """
    run_id = run_manifest.get("run_id", "unknown")
    comparators = run_manifest.get("comparators", [])
    run_scenarios = run_manifest.get("scenarios", [])

    # Index run scenarios by ID.
    run_scenario_by_id: dict[str, dict[str, Any]] = {}
    for s in run_scenarios:
        sid = s.get("scenario_id", "unknown")
        run_scenario_by_id[sid] = s

    # Collect all scenario IDs: from run + from registered manifest.
    all_scenario_ids: list[str] = []
    registered_by_id: dict[str, dict[str, Any]] = {}

    # First, add scenarios from run manifest (preserve order).
    for s in run_scenarios:
        sid = s.get("scenario_id", "unknown")
        if sid not in all_scenario_ids:
            all_scenario_ids.append(sid)

    # Then, add scenarios from the registered manifest if provided.
    if scenarios_manifest:
        for s in scenarios_manifest.get("scenarios", []):
            sid = s["id"]
            registered_by_id[sid] = s
            if sid not in all_scenario_ids:
                all_scenario_ids.append(sid)

    # Build ledger entries.
    entries: list[dict[str, Any]] = []
    included_count = 0
    excluded_count = 0

    for sid in all_scenario_ids:
        run_data = run_scenario_by_id.get(sid)
        registered_data = registered_by_id.get(sid)

        if run_data is None:
            # Scenario is in the registered manifest but was not run.
            entry: dict[str, Any] = {
                "scenario_id": sid,
                "status": "excluded",
                "reason": "Not present in run — scenario was registered but not executed",
            }
            if registered_data:
                entry["description"] = registered_data.get("description", "")
            entries.append(entry)
            excluded_count += 1
            continue

        if run_data.get("skipped", False):
            # Scenario was skipped during the run.
            entry = {
                "scenario_id": sid,
                "status": "excluded",
                "reason": run_data.get("skip_reason", "Skipped (no reason recorded)"),
            }
            if registered_data:
                entry["description"] = registered_data.get("description", "")
            entries.append(entry)
            excluded_count += 1
            continue

        # Scenario was included and executed.
        results = run_data.get("results", {})
        comp_status: dict[str, str] = {}
        for comp in comparators:
            cell = results.get(comp)
            if cell is None:
                comp_status[comp] = "not_defined"
            elif isinstance(cell, dict) and cell.get("skipped", False):
                comp_status[comp] = f"skipped: {cell.get('reason', 'unknown')}"
            elif isinstance(cell, dict) and cell.get("error"):
                comp_status[comp] = f"error: {cell['error']}"
            elif isinstance(cell, dict) and cell.get("timed_out", False):
                comp_status[comp] = "timed_out"
            else:
                comp_status[comp] = "executed"

        entry = {
            "scenario_id": sid,
            "status": "included",
            "comparators": comp_status,
        }
        if registered_data:
            entry["description"] = registered_data.get("description", "")
        entries.append(entry)
        included_count += 1

    return {
        "schema_version": 1,
        "run_id": run_id,
        "timestamp": _now_iso(),
        "commit_sha": run_manifest.get("commit_sha", "unknown"),
        "registered_scenario_count": len(all_scenario_ids),
        "summary": {
            "total": included_count + excluded_count,
            "included": included_count,
            "excluded": excluded_count,
        },
        "scenarios": entries,
    }


# ---------------------------------------------------------------------------
# Checksum generation
# ---------------------------------------------------------------------------


def generate_checksums(pub_dir: Path, artifact_names: list[str]) -> dict[str, str]:
    """Generate SHA-256 checksums for all listed artifacts.

    Args:
        pub_dir: Publication directory containing artifacts.
        artifact_names: List of artifact filenames to checksum.

    Returns:
        Dict mapping filename to SHA-256 hex digest.
    """
    checksums: dict[str, str] = {}
    for name in artifact_names:
        path = pub_dir / name
        if path.exists():
            checksums[name] = _sha256_file(path)
    return checksums


def write_checksums_file(pub_dir: Path, checksums: dict[str, str]) -> Path:
    """Write checksums.sha256 in standard format.

    Format: <hash>  <filename>
    (two-space separator, matching sha256sum output format)
    """
    out_path = pub_dir / "checksums.sha256"
    lines: list[str] = []
    for name in sorted(checksums.keys()):
        lines.append(f"{checksums[name]}  {name}")
    out_path.write_text("\n".join(lines) + "\n")
    return out_path


# ---------------------------------------------------------------------------
# Publication packaging
# ---------------------------------------------------------------------------


def package_publication_artifacts(
    run_dir: Path,
    output_dir: Path,
    scenarios_manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Package a benchmark run into a publication-grade artifact bundle.

    Args:
        run_dir: Path to the benchmark run directory.
        output_dir: Path to the publication output directory.
        scenarios_manifest_path: Optional path to scenarios.json for full
            scenario coverage in the ledger.

    Returns:
        The publication manifest dict.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load run manifest.
    run_manifest = _load_json(run_dir / "run_manifest.json")

    # --- Copy raw artifacts ---
    copied_artifacts: list[dict[str, Any]] = []

    for name in REQUIRED_RAW_ARTIFACTS:
        src = run_dir / name
        if not src.exists():
            print(f"WARNING: Required artifact missing: {name}", file=sys.stderr)
            continue
        dst = output_dir / name
        shutil.copy2(src, dst)
        copied_artifacts.append({
            "name": name,
            "type": "raw",
            "size_bytes": dst.stat().st_size,
        })

    for name in OPTIONAL_RAW_ARTIFACTS:
        src = run_dir / name
        if src.exists():
            dst = output_dir / name
            shutil.copy2(src, dst)
            copied_artifacts.append({
                "name": name,
                "type": "raw",
                "size_bytes": dst.stat().st_size,
            })

    # --- Build inclusion/exclusion ledger ---
    scenarios_manifest = None
    if scenarios_manifest_path and scenarios_manifest_path.exists():
        scenarios_manifest = _load_json(scenarios_manifest_path)
    elif SCENARIOS_PATH.exists():
        scenarios_manifest = _load_json(SCENARIOS_PATH)

    ledger = build_inclusion_exclusion_ledger(run_manifest, scenarios_manifest)
    _write_json(output_dir / "inclusion_exclusion_ledger.json", ledger)
    copied_artifacts.append({
        "name": "inclusion_exclusion_ledger.json",
        "type": "derived",
        "size_bytes": (output_dir / "inclusion_exclusion_ledger.json").stat().st_size,
    })

    # --- Generate checksums ---
    # Checksum all artifacts except the checksum file itself and the
    # publication manifest (which embeds the checksums).
    checksummable = [a["name"] for a in copied_artifacts]
    checksums = generate_checksums(output_dir, checksummable)
    write_checksums_file(output_dir, checksums)
    copied_artifacts.append({
        "name": "checksums.sha256",
        "type": "derived",
        "size_bytes": (output_dir / "checksums.sha256").stat().st_size,
    })

    # --- Build publication manifest ---
    pub_manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_manifest.get("run_id", "unknown"),
        "commit_sha": run_manifest.get("commit_sha", "unknown"),
        "timestamp": _now_iso(),
        "source_run_dir": str(run_dir),
        "manifest_hashes": run_manifest.get("manifest_hashes", {}),
        "comparators": run_manifest.get("comparators", []),
        "artifacts": copied_artifacts,
        "checksums": checksums,
        "inclusion_exclusion_ledger": {
            "summary": ledger["summary"],
            "registered_scenario_count": ledger["registered_scenario_count"],
        },
    }

    _write_json(output_dir / "publication_manifest.json", pub_manifest)

    return pub_manifest


# ---------------------------------------------------------------------------
# CLI: resolve run directory
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
        description="Package publication-grade benchmark artifact bundles."
    )
    parser.add_argument(
        "--run",
        type=str,
        default=None,
        help="Run ID or 'latest' to package.",
    )
    parser.add_argument(
        "--run-dir",
        type=str,
        default=None,
        help="Explicit run directory path.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory for publication bundle. "
             "Defaults to <run_dir>/publication/.",
    )
    parser.add_argument(
        "--scenarios-manifest",
        type=str,
        default=None,
        help="Path to scenarios.json for full scenario coverage.",
    )
    args = parser.parse_args()

    if not args.run and not args.run_dir:
        args.run = "latest"

    run_dir = resolve_run_dir(args.run, args.run_dir)
    if not run_dir.exists():
        print(f"ERROR: Run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(2)

    if not (run_dir / "run_manifest.json").exists():
        print(f"ERROR: run_manifest.json not found in {run_dir}", file=sys.stderr)
        sys.exit(2)

    output_dir = Path(args.output_dir) if args.output_dir else run_dir / "publication"
    scenarios_manifest_path = Path(args.scenarios_manifest) if args.scenarios_manifest else None

    pub_manifest = package_publication_artifacts(
        run_dir, output_dir, scenarios_manifest_path
    )

    # Print summary.
    print(f"\nPublication bundle packaged:")
    print(f"  Run:     {pub_manifest['run_id']}")
    print(f"  Commit:  {pub_manifest['commit_sha']}")
    print(f"  Output:  {output_dir}")
    print(f"  Artifacts: {len(pub_manifest['artifacts'])}")

    ledger_summary = pub_manifest["inclusion_exclusion_ledger"]["summary"]
    print(f"  Scenarios: {ledger_summary['total']} total "
          f"({ledger_summary['included']} included, "
          f"{ledger_summary['excluded']} excluded)")

    print(f"\n  Checksums ({len(pub_manifest['checksums'])}):")
    for name, checksum in sorted(pub_manifest["checksums"].items()):
        print(f"    {checksum[:16]}…  {name}")

    print(f"\n  Publication manifest: {output_dir / 'publication_manifest.json'}")


if __name__ == "__main__":
    main()
