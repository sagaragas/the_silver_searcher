#!/usr/bin/env python3
"""Validate benchmark run manifests for completeness and correctness.

Checks that a run manifest:
  1. Has all required fields and valid schema.
  2. Contains no missing scenario-comparator cells (VAL-BENCH-001).
  3. Includes comparator version metadata (VAL-BENCH-002).
  4. Has command-equivalence expansion artifacts (VAL-BENCH-009).
  5. References valid manifest hashes from the scenario/query/corpus manifests.

Usage:
    python3 benchmarks/validate_manifest.py --run latest
    python3 benchmarks/validate_manifest.py --run 20260305T120000Z
    python3 benchmarks/validate_manifest.py --run-dir /path/to/run/dir
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_OUT = REPO_ROOT / "benchmarks" / "out"
MANIFESTS_DIR = REPO_ROOT / "manifests"


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_run_dir(run_id: str | None, run_dir: str | None) -> Path:
    """Resolve run directory from run ID or explicit path."""
    if run_dir:
        return Path(run_dir)
    if run_id == "latest":
        latest = BENCHMARKS_OUT / "latest"
        if latest.is_symlink():
            return latest.resolve()
        # Fallback: find most recent run directory.
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


def validate_run(run_dir: Path) -> bool:
    """Validate a benchmark run directory.

    Returns True if all checks pass, False otherwise.
    """
    ok = True
    checks_passed = 0
    checks_failed = 0

    def check(name: str, condition: bool, detail: str = ""):
        nonlocal ok, checks_passed, checks_failed
        if condition:
            checks_passed += 1
            print(f"  OK: {name}")
        else:
            checks_failed += 1
            ok = False
            msg = f"  FAIL: {name}"
            if detail:
                msg += f" — {detail}"
            print(msg)

    print(f"\nValidating run: {run_dir}")

    # --- Check run_manifest.json exists and has valid schema ---
    manifest_path = run_dir / "run_manifest.json"
    check("run_manifest.json exists", manifest_path.exists())
    if not manifest_path.exists():
        print("FATAL: Cannot proceed without run_manifest.json")
        return False

    manifest = _load_json(manifest_path)

    # Schema checks.
    required_fields = [
        "schema_version", "run_id", "run_type", "timestamp", "commit_sha",
        "comparators", "manifest_hashes", "environment", "tools_metadata",
        "scenario_count", "cell_totals", "scenarios",
    ]
    for field in required_fields:
        check(
            f"run_manifest has '{field}' field",
            field in manifest,
            f"missing field: {field}",
        )

    # --- VAL-BENCH-002: Comparator versions captured ---
    tools_meta_path = run_dir / "tools_metadata.json"
    check("tools_metadata.json exists", tools_meta_path.exists())

    if tools_meta_path.exists():
        tools_meta = _load_json(tools_meta_path)
        check(
            "tools_metadata has 'comparators' field",
            "comparators" in tools_meta,
        )
        if "comparators" in tools_meta:
            for comp in manifest.get("comparators", []):
                comp_meta = tools_meta["comparators"].get(comp, {})
                has_version = bool(comp_meta.get("version")) and comp_meta["version"] != "not found"
                check(
                    f"version captured for '{comp}'",
                    has_version,
                    f"version='{comp_meta.get('version', 'MISSING')}'",
                )
                has_path = bool(comp_meta.get("binary_path"))
                check(
                    f"binary_path captured for '{comp}'",
                    has_path,
                )

    # Embedded tools_metadata in run_manifest.
    embedded_tools = manifest.get("tools_metadata", {})
    check(
        "run_manifest embeds tools_metadata",
        bool(embedded_tools.get("comparators")),
    )

    # --- VAL-BENCH-001: No missing scenario-comparator cells ---
    # Required comparator enforcement: every comparator defined in a scenario's
    # commands dict AND listed in the run's comparators list is REQUIRED.
    # A required cell must have a valid (non-skipped, non-error) result entry.
    scenarios = manifest.get("scenarios", [])
    run_comparators = set(manifest.get("comparators", []))
    check(
        "scenario_count > 0",
        len(scenarios) > 0,
        f"found {len(scenarios)} scenarios",
    )

    missing_cells: list[str] = []
    incomplete_cells: list[str] = []
    for scenario in scenarios:
        if scenario.get("skipped"):
            continue
        sid = scenario.get("scenario_id", scenario.get("id", "?"))
        commands = scenario.get("commands", {})
        results = scenario.get("results", {})

        # Required comparators for this scenario = intersection of
        # scenario-defined commands and run-level comparators.
        required = set(commands.keys()) & run_comparators

        for comp in required:
            if comp not in results:
                missing_cells.append(f"{sid}/{comp}")
            else:
                cell = results[comp]
                # A skipped cell for a required comparator is a hard failure.
                if cell.get("skipped", False):
                    incomplete_cells.append(
                        f"{sid}/{comp} (skipped: {cell.get('reason', 'unknown')})"
                    )
                # A binary_not_found error is a hard failure.
                elif cell.get("error") == "binary_not_found":
                    incomplete_cells.append(
                        f"{sid}/{comp} (binary not found)"
                    )

    check(
        "no missing required comparator cells",
        len(missing_cells) == 0,
        f"missing: {missing_cells}" if missing_cells else "",
    )

    check(
        "no incomplete required comparator cells (skipped/error)",
        len(incomplete_cells) == 0,
        f"incomplete: {incomplete_cells}" if incomplete_cells else "",
    )

    # Check cell totals consistency.
    cell_totals = manifest.get("cell_totals", {})
    reported_executed = cell_totals.get("executed", 0)
    reported_skipped = cell_totals.get("skipped", 0)
    reported_errors = cell_totals.get("errors", 0)
    reported_total = cell_totals.get("total", 0)

    check(
        "cell totals consistent",
        reported_total == reported_executed + reported_skipped,
        f"total={reported_total}, executed={reported_executed}, skipped={reported_skipped}",
    )

    # --- VAL-BENCH-009: Command equivalence artifact ---
    equiv_path = run_dir / "command_equivalence.json"
    check("command_equivalence.json exists", equiv_path.exists())

    if equiv_path.exists():
        equiv = _load_json(equiv_path)
        check(
            "command_equivalence has scenarios",
            len(equiv.get("scenarios", [])) > 0,
        )

        # Verify no unexpanded placeholders.
        unexpanded = []
        for entry in equiv.get("scenarios", []):
            for comp, cmd in entry.get("expanded_commands", {}).items():
                if "{pattern}" in cmd or "{corpus}" in cmd:
                    unexpanded.append(f"{entry['scenario_id']}/{comp}")

        check(
            "no unexpanded placeholders in equivalence artifact",
            len(unexpanded) == 0,
            f"unexpanded: {unexpanded}" if unexpanded else "",
        )

    # --- Manifest hash references ---
    manifest_hashes = manifest.get("manifest_hashes", {})
    check(
        "manifest references scenario hash",
        bool(manifest_hashes.get("scenarios")),
    )
    check(
        "manifest references query hash",
        bool(manifest_hashes.get("queries")),
    )
    check(
        "manifest references corpus hash",
        bool(manifest_hashes.get("corpus")),
    )

    # Verify against on-disk manifests if available.
    for name, path in [
        ("scenarios", MANIFESTS_DIR / "scenarios.json"),
        ("queries", MANIFESTS_DIR / "queries.json"),
        ("corpus", MANIFESTS_DIR / "corpus.json"),
    ]:
        if path.exists():
            on_disk = _load_json(path)
            on_disk_hash = on_disk.get("manifest_hash", "")
            recorded_hash = manifest_hashes.get(name, "")
            check(
                f"{name} hash matches on-disk manifest",
                recorded_hash == on_disk_hash,
                f"recorded={recorded_hash[:16]}… vs on-disk={on_disk_hash[:16]}…"
                if recorded_hash != on_disk_hash else "",
            )

    # --- Summary ---
    total_checks = checks_passed + checks_failed
    print(f"\nValidation summary: {checks_passed}/{total_checks} checks passed")
    if checks_failed > 0:
        print(f"  {checks_failed} checks FAILED")

    return ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate benchmark run manifest for completeness and correctness."
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

    ok = validate_run(run_dir)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
