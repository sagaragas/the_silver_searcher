#!/usr/bin/env python3
"""Parity-oracle runner: execute baseline ag and candidate command variants,
capture stdout/stderr/exit-code, and emit machine-diff artifacts.

For each scenario in the matrix, the runner:
  1. Resolves the command template (pattern, corpus) from manifests.
  2. Executes the command for the selected target(s).
  3. Captures normalised stdout, stderr, and exit code.
  4. Emits per-scenario diff artifacts comparing target vs baseline (ag).
  5. Records manifest hashes, environment metadata, and a run summary.

Usage examples:
    python3 scripts/parity/run_matrix.py --target baseline --group smoke
    python3 scripts/parity/run_matrix.py --target baseline --group all
    python3 scripts/parity/run_matrix.py --target rg --scenario literal-simple
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFESTS_DIR = REPO_ROOT / "manifests"
SCENARIOS_PATH = MANIFESTS_DIR / "scenarios.json"
QUERIES_PATH = MANIFESTS_DIR / "queries.json"
CORPUS_PATH = MANIFESTS_DIR / "corpus.json"
FIXTURES_PATH = MANIFESTS_DIR / "fixtures.json"

ARTIFACTS_BASE = REPO_ROOT / "parity-artifacts"

# Known scenario groups.  "smoke" is a small fast subset; "all" runs everything.
# Groups can be defined either here (legacy) or via "groups" field in scenarios.json.
SMOKE_SCENARIOS = [
    "literal-simple",
    "literal-nomatch",
    "regex-simple",
    "count-matches",
    "files-with-matches",
]

# Edge-case scenario IDs (also tagged via "groups" field in scenarios.json).
EDGE_CASE_PREFIX = "edge-"

# Targets that can act as the "baseline" (source-of-truth).
BASELINE_TARGETS = {"ag", "baseline"}

# Every comparator that the manifest can define.
ALL_COMPARATORS = {"ag", "rust-ag", "rg", "ugrep"}

# Convenience aliases for target names.
TARGET_ALIASES = {"baseline": "ag", "rust": "rust-ag"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=False, ensure_ascii=False)
        f.write("\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _normalise_output(text: str) -> str:
    """Normalise captured output for stable diffing.

    - Strip trailing whitespace on each line.
    - Sort lines (ag output order is non-deterministic across threads).
    - Collapse blank lines.
    - Strip ANSI escape codes if any leak through.
    """
    # Strip ANSI escapes.
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")
    text = ansi_re.sub("", text)

    lines = [l.rstrip() for l in text.splitlines()]
    lines = [l for l in lines if l]  # drop blank
    lines.sort()
    return "\n".join(lines) + ("\n" if lines else "")


def _resolve_binary(name: str) -> str | None:
    """Resolve a comparator name to an executable path."""
    if name in ("ag", "baseline"):
        # Use the locally-built ag binary.
        local = REPO_ROOT / "ag"
        if local.is_file() and os.access(local, os.X_OK):
            return str(local)
        return shutil.which("ag")
    if name == "rust-ag":
        # Try cargo target dir first (release then debug), then PATH.
        for candidate in [
            REPO_ROOT / "target" / "release" / "rust-ag",
            REPO_ROOT / "target" / "debug" / "rust-ag",
            REPO_ROOT / "rust-ag" / "target" / "release" / "rust-ag",
            REPO_ROOT / "rust-ag" / "target" / "debug" / "rust-ag",
        ]:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        return shutil.which("rust-ag")
    return shutil.which(name)


def _get_binary_version(binary_path: str) -> str:
    """Get version string from a binary."""
    try:
        result = subprocess.run(
            [binary_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return (result.stdout or result.stderr).strip().split("\n")[0]
    except Exception as e:
        return f"unknown ({e})"


def _build_env() -> dict[str, str]:
    """Build a sanitised environment for subprocess execution."""
    env = os.environ.copy()
    # Force no colour / consistent locale.
    env["LANG"] = "C"
    env["LC_ALL"] = "C"
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    return env


def _collect_environment_metadata(targets: list[str]) -> dict[str, Any]:
    """Collect environment metadata for the run."""
    meta: dict[str, Any] = {
        "timestamp": _now_iso(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "commit_sha": _git_sha(),
        "tools": {},
    }
    for target in targets:
        binary = _resolve_binary(target)
        if binary:
            meta["tools"][target] = {
                "path": binary,
                "version": _get_binary_version(binary),
            }
        else:
            meta["tools"][target] = {"path": None, "version": "not found"}
    return meta


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def run_command(
    cmd_template: str,
    pattern: str,
    corpus: str,
    cwd: Path,
    timeout: int = 60,
) -> dict[str, Any]:
    """Execute a single command and capture output."""
    cmd_str = cmd_template.replace("{pattern}", pattern).replace("{corpus}", corpus)
    parts = shlex.split(cmd_str)

    # Resolve the binary name to an actual executable path.
    binary_name = parts[0]
    resolved = _resolve_binary(binary_name)
    if resolved:
        parts[0] = resolved

    start = time.monotonic()
    try:
        result = subprocess.run(
            parts,
            capture_output=True,
            cwd=cwd,
            env=_build_env(),
            timeout=timeout,
        )
        elapsed = time.monotonic() - start
        return {
            "command": cmd_str,
            "exit_code": result.returncode,
            "stdout": result.stdout.decode("utf-8", errors="replace"),
            "stderr": result.stderr.decode("utf-8", errors="replace"),
            "elapsed_s": round(elapsed, 4),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        return {
            "command": cmd_str,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"TIMEOUT after {timeout}s",
            "elapsed_s": round(elapsed, 4),
            "timed_out": True,
        }
    except FileNotFoundError:
        return {
            "command": cmd_str,
            "exit_code": -127,
            "stdout": "",
            "stderr": f"Binary not found for command: {parts[0]}",
            "elapsed_s": 0,
            "timed_out": False,
        }


def compute_diff(baseline_text: str, target_text: str) -> str:
    """Compute a unified diff between baseline and target normalised outputs."""
    import difflib

    baseline_lines = baseline_text.splitlines(keepends=True)
    target_lines = target_text.splitlines(keepends=True)
    diff = difflib.unified_diff(
        baseline_lines,
        target_lines,
        fromfile="baseline (ag)",
        tofile="target",
        lineterm="\n",
    )
    return "".join(diff)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def run_matrix(
    targets: list[str],
    scenario_ids: list[str] | None,
    group: str | None,
    run_dir: Path | None = None,
    cmd_timeout: int = 60,
) -> dict[str, Any]:
    """Execute the parity matrix and emit artifacts.

    Returns the run summary dict.
    """
    # Ensure edge-case fixtures are set up if they'll be needed.
    edge_fixtures_dir = REPO_ROOT / "tests" / "edge-cases"
    edge_setup_script = edge_fixtures_dir / "setup_fixtures.py"
    if edge_setup_script.is_file():
        # Check if fixtures exist; if not, run setup.
        if not (edge_fixtures_dir / "ignore-source").is_dir():
            print("Setting up edge-case fixtures...")
            subprocess.run(
                [sys.executable, str(edge_setup_script)],
                cwd=REPO_ROOT,
                check=True,
            )

    # Load manifests.
    scenarios_manifest = _load_json(SCENARIOS_PATH)
    queries_manifest = _load_json(QUERIES_PATH)
    corpus_manifest = _load_json(CORPUS_PATH)

    # Also load fixture manifest if available.
    fixtures_hash = ""
    if FIXTURES_PATH.exists():
        fixtures_manifest = _load_json(FIXTURES_PATH)
        fixtures_hash = fixtures_manifest.get("manifest_hash", "")

    # Build query lookup.
    query_by_id = {q["id"]: q for q in queries_manifest["queries"]}

    # Select scenarios.
    all_scenarios = scenarios_manifest["scenarios"]
    if scenario_ids:
        selected = [s for s in all_scenarios if s["id"] in scenario_ids]
        missing = set(scenario_ids) - {s["id"] for s in selected}
        if missing:
            print(f"WARNING: Unknown scenario IDs: {missing}", file=sys.stderr)
    elif group == "smoke":
        selected = [s for s in all_scenarios if s["id"] in SMOKE_SCENARIOS]
    elif group == "edge-cases":
        # Select scenarios tagged with "edge-cases" group or matching edge-case prefix.
        selected = [
            s for s in all_scenarios
            if group in s.get("groups", []) or s["id"].startswith(EDGE_CASE_PREFIX)
        ]
    elif group == "all" or group is None:
        selected = all_scenarios
    else:
        # Try to match by group tag in scenario metadata.
        selected = [s for s in all_scenarios if group in s.get("groups", [])]
        if not selected:
            print(f"ERROR: Unknown group '{group}' — no scenarios matched", file=sys.stderr)
            sys.exit(1)

    if not selected:
        print("ERROR: No scenarios selected", file=sys.stderr)
        sys.exit(1)

    # Resolve targets.
    resolved_targets: list[str] = []
    for t in targets:
        resolved = TARGET_ALIASES.get(t, t)
        if resolved in ALL_COMPARATORS:
            resolved_targets.append(resolved)
        else:
            print(f"ERROR: Unknown target '{t}'", file=sys.stderr)
            sys.exit(1)

    # Fail fast: verify all needed binaries exist.
    # Always need ag as baseline, plus each requested target.
    needed = set(resolved_targets) | {"ag"}
    for name in sorted(needed):
        binary = _resolve_binary(name)
        if not binary:
            print(
                f"FATAL: Comparator '{name}' not found. "
                f"Cannot proceed without baseline/target.",
                file=sys.stderr,
            )
            sys.exit(2)

    # Create run directory.
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if run_dir is None:
        run_dir = ARTIFACTS_BASE / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Also maintain a 'latest' symlink.
    latest_link = ARTIFACTS_BASE / "latest"
    if latest_link.is_symlink() or latest_link.exists():
        latest_link.unlink()
    latest_link.symlink_to(run_dir.name)

    # Collect environment metadata.
    env_meta = _collect_environment_metadata(list(needed))
    env_meta["manifest_hashes"] = {
        "scenarios": scenarios_manifest.get("manifest_hash", ""),
        "queries": queries_manifest.get("manifest_hash", ""),
        "corpus": corpus_manifest.get("manifest_hash", ""),
        "fixtures": fixtures_hash,
    }
    _write_json(run_dir / "environment.json", env_meta)

    # Execute scenarios.
    results: list[dict[str, Any]] = []
    pass_count = 0
    fail_count = 0
    error_count = 0

    for scenario in selected:
        sid = scenario["id"]
        query = query_by_id.get(scenario["query_id"])
        if not query:
            print(f"WARNING: Query {scenario['query_id']} not found, skipping {sid}", file=sys.stderr)
            continue

        # Check platform_skip conditions.
        platform_skip = scenario.get("platform_skip")
        if platform_skip:
            skip_condition = platform_skip.get("condition", "")
            should_skip = False
            if skip_condition == "symlinks_unsupported":
                should_skip = platform.system() == "Windows"
            elif skip_condition == "one_device_unavailable":
                # Check the fixture marker for the authoritative answer.
                marker_path = REPO_ROOT / "tests" / "edge-cases" / "one-device" / "one-device-marker.json"
                if marker_path.is_file():
                    try:
                        with open(marker_path, "r", encoding="utf-8") as _mf:
                            _marker = json.load(_mf)
                        should_skip = not _marker.get("cross_device_available", False)
                    except (json.JSONDecodeError, OSError):
                        should_skip = True
                else:
                    # No marker → fixture not set up; skip.
                    should_skip = True
            if should_skip:
                skip_reason = platform_skip.get("reason", "Platform condition not met")
                print(f"  SKIP: {sid} — {skip_reason}")
                results.append({
                    "scenario_id": sid,
                    "query_id": scenario["query_id"],
                    "pattern": query["pattern"],
                    "corpus": scenario["corpus"],
                    "baseline": None,
                    "targets": {},
                    "skipped": True,
                    "skip_reason": skip_reason,
                })
                continue

        pattern = query["pattern"]
        corpus = scenario["corpus"]

        scenario_dir = run_dir / "scenarios" / sid
        scenario_dir.mkdir(parents=True, exist_ok=True)

        # Always run baseline (ag).
        baseline_template = scenario["commands"].get("ag")
        if not baseline_template:
            print(f"WARNING: No ag command for scenario {sid}", file=sys.stderr)
            continue

        baseline_result = run_command(baseline_template, pattern, corpus, REPO_ROOT, timeout=cmd_timeout)
        baseline_norm = _normalise_output(baseline_result["stdout"])

        # Store baseline output.
        _write_text(scenario_dir / "baseline.stdout", baseline_result["stdout"])
        _write_text(scenario_dir / "baseline.stderr", baseline_result["stderr"])
        _write_text(scenario_dir / "baseline.norm", baseline_norm)
        _write_json(scenario_dir / "baseline.meta.json", {
            "command": baseline_result["command"],
            "exit_code": baseline_result["exit_code"],
            "elapsed_s": baseline_result["elapsed_s"],
            "timed_out": baseline_result["timed_out"],
            "stdout_sha256": _sha256_bytes(baseline_result["stdout"].encode("utf-8")),
            "norm_sha256": _sha256_bytes(baseline_norm.encode("utf-8")),
        })

        # Run each non-ag target and diff against baseline.
        scenario_result: dict[str, Any] = {
            "scenario_id": sid,
            "query_id": scenario["query_id"],
            "pattern": pattern,
            "corpus": corpus,
            "baseline": {
                "command": baseline_result["command"],
                "exit_code": baseline_result["exit_code"],
                "elapsed_s": baseline_result["elapsed_s"],
                "timed_out": baseline_result["timed_out"],
            },
            "targets": {},
        }

        for target in resolved_targets:
            if target == "ag":
                # Baseline already executed; record self-comparison.
                scenario_result["targets"]["ag"] = {
                    "command": baseline_result["command"],
                    "exit_code": baseline_result["exit_code"],
                    "elapsed_s": baseline_result["elapsed_s"],
                    "timed_out": baseline_result["timed_out"],
                    "parity": "pass",
                    "diff_lines": 0,
                }
                pass_count += 1
                continue

            target_template = scenario["commands"].get(target)
            if not target_template:
                scenario_result["targets"][target] = {
                    "command": None,
                    "exit_code": None,
                    "parity": "skip",
                    "reason": f"No command template for {target} in scenario {sid}",
                }
                continue

            target_result = run_command(target_template, pattern, corpus, REPO_ROOT, timeout=cmd_timeout)
            target_norm = _normalise_output(target_result["stdout"])

            # Store target output.
            _write_text(scenario_dir / f"{target}.stdout", target_result["stdout"])
            _write_text(scenario_dir / f"{target}.stderr", target_result["stderr"])
            _write_text(scenario_dir / f"{target}.norm", target_norm)
            _write_json(scenario_dir / f"{target}.meta.json", {
                "command": target_result["command"],
                "exit_code": target_result["exit_code"],
                "elapsed_s": target_result["elapsed_s"],
                "timed_out": target_result["timed_out"],
                "stdout_sha256": _sha256_bytes(target_result["stdout"].encode("utf-8")),
                "norm_sha256": _sha256_bytes(target_norm.encode("utf-8")),
            })

            # Compute diff.
            diff_text = compute_diff(baseline_norm, target_norm)
            _write_text(scenario_dir / f"{target}.diff", diff_text)

            diff_lines = len([l for l in diff_text.splitlines() if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))])
            exit_match = baseline_result["exit_code"] == target_result["exit_code"]
            output_match = baseline_norm == target_norm

            if target_result["exit_code"] == -127:
                parity = "error"
                error_count += 1
            elif target_result["timed_out"]:
                parity = "error"
                error_count += 1
            elif output_match and exit_match:
                parity = "pass"
                pass_count += 1
            else:
                parity = "fail"
                fail_count += 1

            scenario_result["targets"][target] = {
                "command": target_result["command"],
                "exit_code": target_result["exit_code"],
                "elapsed_s": target_result["elapsed_s"],
                "timed_out": target_result["timed_out"],
                "parity": parity,
                "exit_code_match": exit_match,
                "output_match": output_match,
                "diff_lines": diff_lines,
            }

        results.append(scenario_result)

    # Write run summary.
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "timestamp": _now_iso(),
        "commit_sha": _git_sha(),
        "targets": resolved_targets,
        "group": group or "all",
        "scenario_count": len(results),
        "manifest_hashes": env_meta["manifest_hashes"],
        "totals": {
            "pass": pass_count,
            "fail": fail_count,
            "error": error_count,
        },
        "scenarios": results,
    }
    _write_json(run_dir / "summary.json", summary)

    # Print human-readable summary.
    total = pass_count + fail_count + error_count
    print(f"\nParity run complete: {run_id}")
    print(f"  Artifacts: {run_dir}")
    print(f"  Scenarios: {len(results)}")
    print(f"  Comparisons: {total} (pass={pass_count}, fail={fail_count}, error={error_count})")
    print(f"  Manifest hashes:")
    for k, v in env_meta["manifest_hashes"].items():
        print(f"    {k}: {v[:16]}…" if v else f"    {k}: (none)")

    if fail_count > 0 or error_count > 0:
        print(f"\n  FAILURES/ERRORS:")
        for r in results:
            for tname, tres in r.get("targets", {}).items():
                if tres.get("parity") in ("fail", "error"):
                    print(f"    {r['scenario_id']}/{tname}: {tres['parity']} "
                          f"(exit_match={tres.get('exit_code_match')}, "
                          f"output_match={tres.get('output_match')}, "
                          f"diff_lines={tres.get('diff_lines')})")

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parity-oracle runner for baseline ag vs candidate commands.",
    )
    parser.add_argument(
        "--target",
        type=str,
        required=True,
        help="Comparator target(s), comma-separated. E.g. 'baseline', 'rg', 'rust-ag,rg'.",
    )
    parser.add_argument(
        "--group",
        type=str,
        default=None,
        help="Scenario group to run: 'smoke', 'all'. Default is all.",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default=None,
        help="Specific scenario ID(s), comma-separated. Overrides --group.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Per-command timeout in seconds (default: 60).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Override output directory for run artifacts.",
    )

    args = parser.parse_args()

    targets = [t.strip() for t in args.target.split(",") if t.strip()]
    scenario_ids = (
        [s.strip() for s in args.scenario.split(",") if s.strip()]
        if args.scenario
        else None
    )
    run_dir = Path(args.output_dir) if args.output_dir else None

    summary = run_matrix(
        targets, scenario_ids, args.group, run_dir, cmd_timeout=args.timeout
    )

    # Exit code: 0 if all pass, 1 if any fail, 2 if errors.
    if summary["totals"]["error"] > 0:
        sys.exit(2)
    if summary["totals"]["fail"] > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
