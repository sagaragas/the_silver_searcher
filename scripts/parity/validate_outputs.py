#!/usr/bin/env python3
"""Validate parity-oracle run outputs.

Inspects a completed run directory and verifies:
  - All expected artifact files exist and are non-empty.
  - Manifest hashes are recorded and consistent.
  - Environment metadata is present and complete.
  - Diff artifacts are well-formed.
  - Summarises pass/fail/error counts and flags issues.

Usage:
    python3 scripts/parity/validate_outputs.py --run latest
    python3 scripts/parity/validate_outputs.py --run 20260305T120000Z
    python3 scripts/parity/validate_outputs.py --run-dir parity-artifacts/20260305T120000Z
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_BASE = REPO_ROOT / "parity-artifacts"

# Required top-level files in a run directory.
REQUIRED_RUN_FILES = ["summary.json", "environment.json"]

# Required fields in environment.json.
REQUIRED_ENV_FIELDS = ["timestamp", "platform", "commit_sha", "tools", "manifest_hashes"]

# Required fields in summary.json.
REQUIRED_SUMMARY_FIELDS = [
    "schema_version",
    "run_id",
    "timestamp",
    "commit_sha",
    "targets",
    "scenario_count",
    "manifest_hashes",
    "totals",
    "scenarios",
]

# Per-scenario required artifact extensions (for baseline).
BASELINE_EXTENSIONS = [".stdout", ".stderr", ".norm", ".meta.json"]

# Per-target required artifact extensions.
TARGET_EXTENSIONS = [".stdout", ".stderr", ".norm", ".meta.json", ".diff"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class ValidationResult:
    """Accumulates validation checks and their outcomes."""

    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def check(self, name: str, passed: bool, detail: str = "") -> bool:
        self.checks.append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            self.errors.append(f"FAIL: {name}" + (f" — {detail}" if detail else ""))
        return passed

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def passed(self) -> bool:
        return all(c["passed"] for c in self.checks)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c["passed"])

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if not c["passed"])


def resolve_run_dir(run_name: str | None, run_dir_override: str | None) -> Path:
    """Resolve the run directory from a run name or explicit path."""
    if run_dir_override:
        p = Path(run_dir_override)
        if not p.is_absolute():
            p = REPO_ROOT / p
        return p

    if run_name == "latest":
        latest = ARTIFACTS_BASE / "latest"
        if latest.is_symlink():
            return latest.resolve()
        # Fall back: find most recent directory.
        dirs = sorted(
            [d for d in ARTIFACTS_BASE.iterdir() if d.is_dir() and d.name != "latest"],
            key=lambda d: d.name,
        )
        if dirs:
            return dirs[-1]
        print("ERROR: No run directories found in parity-artifacts/", file=sys.stderr)
        sys.exit(1)

    candidate = ARTIFACTS_BASE / run_name
    if candidate.is_dir():
        return candidate

    print(f"ERROR: Run directory not found: {candidate}", file=sys.stderr)
    sys.exit(1)


def validate_run(run_dir: Path) -> ValidationResult:
    """Validate a parity run directory."""
    vr = ValidationResult()

    # Check run directory exists.
    vr.check("run_dir_exists", run_dir.is_dir(), str(run_dir))
    if not run_dir.is_dir():
        return vr

    # Check required top-level files.
    for fname in REQUIRED_RUN_FILES:
        fpath = run_dir / fname
        vr.check(
            f"file_exists:{fname}",
            fpath.is_file(),
            str(fpath),
        )

    # Validate environment.json.
    env_path = run_dir / "environment.json"
    env_data: dict[str, Any] = {}
    if env_path.is_file():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                env_data = json.load(f)
            vr.check("env_json_valid", True)
        except (json.JSONDecodeError, OSError) as e:
            vr.check("env_json_valid", False, str(e))

        for field in REQUIRED_ENV_FIELDS:
            vr.check(
                f"env_field:{field}",
                field in env_data and env_data[field],
                f"Missing or empty: {field}",
            )

        # Check manifest hashes are recorded.
        manifest_hashes = env_data.get("manifest_hashes", {})
        for mname in ["scenarios", "queries", "corpus"]:
            vr.check(
                f"manifest_hash_recorded:{mname}",
                bool(manifest_hashes.get(mname)),
                f"Missing manifest hash for {mname}",
            )

        # Check tools metadata.
        tools = env_data.get("tools", {})
        vr.check(
            "tools_metadata_present",
            len(tools) > 0,
            f"Expected at least 1 tool entry, got {len(tools)}",
        )

    # Validate summary.json.
    summary_path = run_dir / "summary.json"
    summary: dict[str, Any] = {}
    if summary_path.is_file():
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
            vr.check("summary_json_valid", True)
        except (json.JSONDecodeError, OSError) as e:
            vr.check("summary_json_valid", False, str(e))

        for field in REQUIRED_SUMMARY_FIELDS:
            vr.check(
                f"summary_field:{field}",
                field in summary,
                f"Missing field: {field}",
            )

        # Check commit SHA is recorded.
        vr.check(
            "commit_sha_recorded",
            bool(summary.get("commit_sha")),
            "Missing commit_sha in summary",
        )

        # Check scenario count consistency.
        scenarios = summary.get("scenarios", [])
        declared_count = summary.get("scenario_count", 0)
        vr.check(
            "scenario_count_consistent",
            len(scenarios) == declared_count,
            f"Declared {declared_count}, found {len(scenarios)}",
        )

        # Check totals consistency.
        totals = summary.get("totals", {})
        expected_total = totals.get("pass", 0) + totals.get("fail", 0) + totals.get("error", 0)
        actual_comparisons = 0
        for sc in scenarios:
            for tname, tres in sc.get("targets", {}).items():
                if tres.get("parity") in ("pass", "fail", "error"):
                    actual_comparisons += 1

        vr.check(
            "totals_consistent",
            expected_total == actual_comparisons,
            f"Totals sum={expected_total}, actual comparisons={actual_comparisons}",
        )

    # Validate per-scenario artifact files.
    scenarios_dir = run_dir / "scenarios"
    if scenarios_dir.is_dir():
        for sc in summary.get("scenarios", []):
            sid = sc["scenario_id"]
            sc_dir = scenarios_dir / sid

            vr.check(
                f"scenario_dir:{sid}",
                sc_dir.is_dir(),
                str(sc_dir),
            )
            if not sc_dir.is_dir():
                continue

            # Check baseline artifacts.
            for ext in BASELINE_EXTENSIONS:
                fpath = sc_dir / f"baseline{ext}"
                vr.check(
                    f"artifact:{sid}/baseline{ext}",
                    fpath.is_file(),
                    str(fpath),
                )

            # Check target artifacts.
            for tname, tres in sc.get("targets", {}).items():
                if tname == "ag":
                    continue  # ag is the baseline; no separate artifacts
                if tres.get("parity") == "skip":
                    continue

                for ext in TARGET_EXTENSIONS:
                    fpath = sc_dir / f"{tname}{ext}"
                    vr.check(
                        f"artifact:{sid}/{tname}{ext}",
                        fpath.is_file(),
                        str(fpath),
                    )

            # Validate baseline meta.json structure.
            baseline_meta_path = sc_dir / "baseline.meta.json"
            if baseline_meta_path.is_file():
                try:
                    with open(baseline_meta_path, "r", encoding="utf-8") as f:
                        bmeta = json.load(f)
                    vr.check(
                        f"baseline_meta_valid:{sid}",
                        "command" in bmeta and "exit_code" in bmeta,
                        "Missing command or exit_code in baseline meta",
                    )
                except (json.JSONDecodeError, OSError) as e:
                    vr.check(f"baseline_meta_valid:{sid}", False, str(e))

            # Validate diff artifacts are text (not binary garbage).
            for tname, tres in sc.get("targets", {}).items():
                if tname == "ag" or tres.get("parity") == "skip":
                    continue
                diff_path = sc_dir / f"{tname}.diff"
                if diff_path.is_file():
                    try:
                        content = diff_path.read_text(encoding="utf-8")
                        # An empty diff is valid (means match).
                        # A non-empty diff should have unified diff headers if there are changes.
                        if content.strip():
                            has_headers = "---" in content and "+++" in content
                            vr.check(
                                f"diff_format:{sid}/{tname}",
                                has_headers,
                                "Non-empty diff missing unified diff headers",
                            )
                        else:
                            vr.check(f"diff_format:{sid}/{tname}", True, "Empty diff (match)")
                    except UnicodeDecodeError:
                        vr.check(f"diff_format:{sid}/{tname}", False, "Binary content in diff file")
    else:
        if summary.get("scenarios"):
            vr.check("scenarios_dir_exists", False, "No scenarios/ directory found")

    return vr


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate parity-oracle run outputs.",
    )
    parser.add_argument(
        "--run",
        type=str,
        default=None,
        help="Run identifier or 'latest'. E.g. '20260305T120000Z' or 'latest'.",
    )
    parser.add_argument(
        "--run-dir",
        type=str,
        default=None,
        help="Explicit path to run directory (overrides --run).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit results as JSON instead of human-readable text.",
    )

    args = parser.parse_args()

    if not args.run and not args.run_dir:
        args.run = "latest"

    run_dir = resolve_run_dir(args.run, args.run_dir)
    print(f"Validating run: {run_dir}\n")

    vr = validate_run(run_dir)

    if args.json:
        output = {
            "run_dir": str(run_dir),
            "passed": vr.passed,
            "total_checks": vr.total,
            "pass_count": vr.pass_count,
            "fail_count": vr.fail_count,
            "errors": vr.errors,
            "warnings": vr.warnings,
            "checks": vr.checks,
        }
        json.dump(output, sys.stdout, indent=2)
        print()
    else:
        print(f"Checks: {vr.total} total, {vr.pass_count} passed, {vr.fail_count} failed")
        if vr.errors:
            print(f"\nErrors ({len(vr.errors)}):")
            for e in vr.errors:
                print(f"  {e}")
        if vr.warnings:
            print(f"\nWarnings ({len(vr.warnings)}):")
            for w in vr.warnings:
                print(f"  {w}")
        if vr.passed:
            print("\n✓ All validation checks passed.")
        else:
            print("\n✗ Validation FAILED.")

    sys.exit(0 if vr.passed else 1)


if __name__ == "__main__":
    main()
