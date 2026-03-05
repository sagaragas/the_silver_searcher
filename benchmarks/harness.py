#!/usr/bin/env python3
"""Benchmark harness: core execution matrix and command-equivalence expansion.

Runs benchmark scenarios across multiple comparators (ag, rust-ag, rg, ugrep),
capturing timing samples, comparator version metadata, and command-equivalence
artifacts for reproducibility and publication.

Fulfills:
    VAL-BENCH-001  Comparator matrix is complete.
    VAL-BENCH-002  Comparator versions/build identifiers are captured.
    VAL-BENCH-009  Expanded commands preserve equivalent workload intent.

Usage:
    python3 benchmarks/harness.py smoke --comparators rust ag rg ugrep
    python3 benchmarks/harness.py smoke --comparators ag rg
    python3 benchmarks/harness.py run --comparators rust ag rg ugrep --scenarios literal-simple
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
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

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFESTS_DIR = REPO_ROOT / "manifests"
SCENARIOS_PATH = MANIFESTS_DIR / "scenarios.json"
QUERIES_PATH = MANIFESTS_DIR / "queries.json"
CORPUS_PATH = MANIFESTS_DIR / "corpus.json"

BENCHMARKS_OUT = REPO_ROOT / "benchmarks" / "out"

# Canonical comparator set.
ALL_COMPARATORS = ["ag", "rust-ag", "rg", "ugrep"]

# Aliases: CLI name -> internal name.
COMPARATOR_ALIASES = {
    "rust": "rust-ag",
    "baseline": "ag",
}

# Smoke scenarios: a fast representative subset.
SMOKE_SCENARIO_IDS = [
    "literal-simple",
    "literal-nomatch",
    "regex-simple",
    "count-matches",
    "files-with-matches",
    "literal-word",
    "literal-nocase",
    "context-before-after",
]

# ---------------------------------------------------------------------------
# Binary resolution
# ---------------------------------------------------------------------------


def resolve_binary(name: str) -> str | None:
    """Resolve a comparator name to an executable path."""
    if name in ("ag", "baseline"):
        local = REPO_ROOT / "ag"
        if local.is_file() and os.access(local, os.X_OK):
            return str(local)
        return shutil.which("ag")
    if name == "rust-ag":
        for candidate in [
            REPO_ROOT / "target" / "release" / "rust-ag",
            REPO_ROOT / "target" / "debug" / "rust-ag",
        ]:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        return shutil.which("rust-ag")
    return shutil.which(name)


# ---------------------------------------------------------------------------
# Version capture (VAL-BENCH-002)
# ---------------------------------------------------------------------------


def capture_comparator_version(name: str, binary_path: str) -> str:
    """Capture the full version string from a comparator binary.

    Returns the first non-empty line of --version output.
    """
    try:
        result = subprocess.run(
            [binary_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        raw = (result.stdout or result.stderr).strip()
        # Return first non-empty line.
        for line in raw.splitlines():
            if line.strip():
                return line.strip()
        return raw
    except Exception as e:
        return f"error: {e}"


def capture_comparator_version_raw(name: str, binary_path: str) -> str:
    """Capture the full raw --version output for audit purposes."""
    try:
        result = subprocess.run(
            [binary_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return (result.stdout or result.stderr).strip()
    except Exception as e:
        return f"error: {e}"


def collect_tools_metadata(comparators: list[str]) -> dict[str, Any]:
    """Collect tools metadata for all requested comparators.

    Returns a dict suitable for the tools_metadata artifact:
    {
        "comparators": {
            "ag": {"binary_path": "...", "version": "...", "version_raw": "..."},
            ...
        },
        "timestamp": "...",
        "commit_sha": "..."
    }
    """
    meta: dict[str, Any] = {
        "comparators": {},
        "timestamp": _now_iso(),
        "commit_sha": _git_sha(),
    }
    for comp in comparators:
        binary = resolve_binary(comp)
        if binary:
            meta["comparators"][comp] = {
                "binary_path": binary,
                "version": capture_comparator_version(comp, binary),
                "version_raw": capture_comparator_version_raw(comp, binary),
            }
        else:
            meta["comparators"][comp] = {
                "binary_path": None,
                "version": "not found",
                "version_raw": "not found",
            }
    return meta


# ---------------------------------------------------------------------------
# Command expansion (VAL-BENCH-009)
# ---------------------------------------------------------------------------


def expand_command(template: str, pattern: str, corpus: str) -> str:
    """Expand a command template by substituting {pattern} and {corpus}."""
    return template.replace("{pattern}", pattern).replace("{corpus}", corpus)


def tokenize_command(cmd_str: str) -> list[str]:
    """Split a command string into argv tokens, preserving backslash literals.

    Uses shlex.split(posix=False) to keep backslashes, then strips outer quotes.
    """
    tokens = shlex.split(cmd_str, posix=False)
    result: list[str] = []
    for tok in tokens:
        if len(tok) >= 2 and (
            (tok[0] == '"' and tok[-1] == '"')
            or (tok[0] == "'" and tok[-1] == "'")
        ):
            result.append(tok[1:-1])
        else:
            result.append(tok)
    return result


def build_command_equivalence(
    scenarios: list[dict[str, Any]],
    query_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build command-equivalence artifact for all scenarios.

    For each scenario, expands all comparator command templates with the
    actual pattern and corpus, producing a record showing the exact
    equivalent commands across tools.

    Returns a list of scenario equivalence entries.
    """
    entries: list[dict[str, Any]] = []
    for scenario in scenarios:
        query = query_by_id.get(scenario["query_id"])
        if not query:
            continue
        pattern = query["pattern"]
        corpus = scenario["corpus"]

        expanded: dict[str, str] = {}
        for comp, template in scenario.get("commands", {}).items():
            expanded[comp] = expand_command(template, pattern, corpus)

        entries.append({
            "scenario_id": scenario["id"],
            "query_id": scenario["query_id"],
            "pattern": pattern,
            "corpus": corpus,
            "templates": dict(scenario.get("commands", {})),
            "expanded_commands": expanded,
        })
    return entries


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=False, ensure_ascii=False)
        f.write("\n")


def _build_env() -> dict[str, str]:
    """Build a sanitised environment for subprocess execution."""
    env = os.environ.copy()
    env["LANG"] = "C"
    env["LC_ALL"] = "C"
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    return env


def _collect_environment_metadata() -> dict[str, Any]:
    """Collect environment metadata for the run."""
    return {
        "timestamp": _now_iso(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "commit_sha": _git_sha(),
    }


# ---------------------------------------------------------------------------
# Scenario execution
# ---------------------------------------------------------------------------


def execute_scenario_cell(
    comparator: str,
    cmd_template: str,
    pattern: str,
    corpus: str,
    timeout: int = 30,
) -> dict[str, Any]:
    """Execute a single scenario-comparator cell and capture results.

    Returns a dict with command, exit_code, elapsed_s, stdout_hash, etc.
    """
    cmd_str = expand_command(cmd_template, pattern, corpus)
    parts = tokenize_command(cmd_str)

    # Resolve the binary.
    binary = resolve_binary(parts[0])
    if binary:
        parts[0] = binary

    start = time.monotonic()
    try:
        result = subprocess.run(
            parts,
            capture_output=True,
            cwd=REPO_ROOT,
            env=_build_env(),
            timeout=timeout,
        )
        elapsed = time.monotonic() - start
        stdout_bytes = result.stdout
        stderr_text = result.stderr.decode("utf-8", errors="replace")
        return {
            "command": cmd_str,
            "exit_code": result.returncode,
            "elapsed_s": round(elapsed, 6),
            "stdout_hash": hashlib.sha256(stdout_bytes).hexdigest(),
            "stdout_bytes": len(stdout_bytes),
            "stderr_excerpt": stderr_text[:500] if stderr_text else "",
            "timed_out": False,
            "error": None,
        }
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        return {
            "command": cmd_str,
            "exit_code": -1,
            "elapsed_s": round(elapsed, 6),
            "stdout_hash": "",
            "stdout_bytes": 0,
            "stderr_excerpt": f"TIMEOUT after {timeout}s",
            "timed_out": True,
            "error": "timeout",
        }
    except FileNotFoundError:
        return {
            "command": cmd_str,
            "exit_code": -127,
            "elapsed_s": 0,
            "stdout_hash": "",
            "stdout_bytes": 0,
            "stderr_excerpt": f"Binary not found: {parts[0]}",
            "timed_out": False,
            "error": "binary_not_found",
        }


# ---------------------------------------------------------------------------
# Smoke run
# ---------------------------------------------------------------------------


def run_smoke(
    comparators: list[str],
    output_dir: Path | None = None,
    scenario_ids: list[str] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """Execute a smoke benchmark run across all comparators and selected scenarios.

    Args:
        comparators: List of comparator names to run.
        output_dir: Output directory for artifacts. Defaults to benchmarks/out/<timestamp>.
        scenario_ids: Specific scenario IDs to run. Defaults to SMOKE_SCENARIO_IDS.
        timeout: Per-command timeout in seconds.

    Returns:
        The run manifest dict.
    """
    # Resolve comparator aliases.
    resolved_comparators = [
        COMPARATOR_ALIASES.get(c, c) for c in comparators
    ]

    # Validate all comparators are available.
    missing = []
    for comp in resolved_comparators:
        if resolve_binary(comp) is None:
            missing.append(comp)
    if missing:
        print(f"FATAL: Missing comparators: {missing}", file=sys.stderr)
        sys.exit(2)

    # Load manifests.
    scenarios_manifest = _load_json(SCENARIOS_PATH)
    queries_manifest = _load_json(QUERIES_PATH)
    corpus_manifest = _load_json(CORPUS_PATH)

    query_by_id = {q["id"]: q for q in queries_manifest["queries"]}

    # Select scenarios.
    all_scenarios = scenarios_manifest["scenarios"]
    if scenario_ids:
        selected = [s for s in all_scenarios if s["id"] in scenario_ids]
    else:
        selected = [s for s in all_scenarios if s["id"] in SMOKE_SCENARIO_IDS]
        # Also include any scenarios that list "smoke" in their groups.
        smoke_from_groups = [
            s for s in all_scenarios
            if "smoke" in s.get("groups", []) and s["id"] not in SMOKE_SCENARIO_IDS
        ]
        selected.extend(smoke_from_groups)
        # Deduplicate preserving order.
        seen = set()
        deduped = []
        for s in selected:
            if s["id"] not in seen:
                seen.add(s["id"])
                deduped.append(s)
        selected = deduped

    if not selected:
        print("ERROR: No scenarios selected for smoke run", file=sys.stderr)
        sys.exit(1)

    # Create output directory.
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if output_dir is None:
        output_dir = BENCHMARKS_OUT / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Update latest symlink.
    _update_latest_symlink(BENCHMARKS_OUT, output_dir)

    # Capture tools metadata (VAL-BENCH-002).
    tools_meta = collect_tools_metadata(resolved_comparators)

    # Build command equivalence (VAL-BENCH-009).
    equivalence = build_command_equivalence(selected, query_by_id)

    # Write command equivalence artifact.
    _write_json(output_dir / "command_equivalence.json", {
        "schema_version": 1,
        "description": "Command equivalence expansion for benchmark scenarios",
        "timestamp": _now_iso(),
        "scenario_count": len(equivalence),
        "scenarios": equivalence,
    })

    # Execute matrix (VAL-BENCH-001).
    scenario_results: list[dict[str, Any]] = []
    total_cells = 0
    executed_cells = 0
    skipped_cells = 0
    error_cells = 0

    print(f"\nBenchmark smoke run: {run_id}")
    print(f"  Comparators: {resolved_comparators}")
    print(f"  Scenarios: {len(selected)}")
    print()

    for scenario in selected:
        sid = scenario["id"]
        query = query_by_id.get(scenario["query_id"])
        if not query:
            print(f"  WARNING: Unknown query {scenario['query_id']} for {sid}")
            continue

        # Check platform_skip.
        platform_skip = scenario.get("platform_skip")
        if platform_skip:
            skip_condition = platform_skip.get("condition", "")
            should_skip = False
            if "Windows" in skip_condition and platform.system() == "Windows":
                should_skip = True
            elif "cross_device_available" in skip_condition:
                marker_path = (
                    REPO_ROOT / "tests" / "edge-cases" / "one-device"
                    / "one-device-marker.json"
                )
                if marker_path.is_file():
                    try:
                        with open(marker_path) as mf:
                            marker = json.load(mf)
                        should_skip = not marker.get("cross_device_available", False)
                    except (json.JSONDecodeError, OSError):
                        should_skip = True
                else:
                    should_skip = True
            if should_skip:
                scenario_results.append({
                    "scenario_id": sid,
                    "skipped": True,
                    "skip_reason": platform_skip.get("reason", "Platform skip"),
                })
                print(f"  SKIP: {sid}")
                continue

        pattern = query["pattern"]
        corpus = scenario["corpus"]
        commands = scenario.get("commands", {})

        results: dict[str, Any] = {}

        for comp in resolved_comparators:
            total_cells += 1
            template = commands.get(comp)
            if template is None:
                # This comparator is not defined for this scenario.
                skipped_cells += 1
                results[comp] = {
                    "skipped": True,
                    "reason": f"No command template for {comp}",
                }
                continue

            cell = execute_scenario_cell(
                comp, template, pattern, corpus, timeout=timeout
            )
            results[comp] = cell
            executed_cells += 1

            if cell.get("error"):
                error_cells += 1
                status = "ERR"
            else:
                status = f"ok ({cell['elapsed_s']:.3f}s)"

            print(f"  {sid}/{comp}: {status}")

        scenario_results.append({
            "scenario_id": sid,
            "query_id": scenario["query_id"],
            "pattern": pattern,
            "corpus": corpus,
            "commands": commands,
            "results": results,
            "skipped": False,
        })

    # Build run manifest.
    run_manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "run_type": "smoke",
        "timestamp": _now_iso(),
        "commit_sha": _git_sha(),
        "comparators": resolved_comparators,
        "manifest_hashes": {
            "scenarios": scenarios_manifest.get("manifest_hash", ""),
            "queries": queries_manifest.get("manifest_hash", ""),
            "corpus": corpus_manifest.get("manifest_hash", ""),
        },
        "environment": _collect_environment_metadata(),
        "tools_metadata": tools_meta,
        "scenario_count": len(scenario_results),
        "cell_totals": {
            "total": total_cells,
            "executed": executed_cells,
            "skipped": skipped_cells,
            "errors": error_cells,
        },
        "scenarios": scenario_results,
    }

    # Write run manifest.
    _write_json(output_dir / "run_manifest.json", run_manifest)

    # Write tools metadata as separate artifact.
    _write_json(output_dir / "tools_metadata.json", tools_meta)

    # Print summary.
    print(f"\nSmoke run complete: {run_id}")
    print(f"  Output: {output_dir}")
    print(f"  Cells: {executed_cells} executed, {skipped_cells} skipped, {error_cells} errors")
    print(f"  Tools metadata: {output_dir / 'tools_metadata.json'}")
    print(f"  Command equiv:  {output_dir / 'command_equivalence.json'}")

    # Print version summary.
    print(f"\n  Comparator versions:")
    for comp in resolved_comparators:
        v = tools_meta["comparators"].get(comp, {}).get("version", "unknown")
        print(f"    {comp}: {v}")

    return run_manifest


def _update_latest_symlink(out_base: Path, run_dir: Path) -> None:
    """Create or update 'latest' symlink."""
    out_base.mkdir(parents=True, exist_ok=True)
    latest = out_base / "latest"
    if latest.is_symlink() or latest.exists():
        latest.unlink()

    resolved_base = out_base.resolve()
    resolved_run = run_dir.resolve()

    try:
        rel = resolved_run.relative_to(resolved_base)
        latest.symlink_to(rel)
    except ValueError:
        rel = os.path.relpath(resolved_run, resolved_base)
        latest.symlink_to(rel)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark harness: execute scenario matrix across comparators."
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommand")

    # smoke subcommand
    smoke_parser = subparsers.add_parser("smoke", help="Run smoke benchmark suite")
    smoke_parser.add_argument(
        "--comparators",
        nargs="+",
        default=ALL_COMPARATORS,
        help="Comparators to include (default: all four).",
    )
    smoke_parser.add_argument(
        "--scenarios",
        nargs="+",
        default=None,
        help="Specific scenario IDs to run (overrides default smoke set).",
    )
    smoke_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Override output directory.",
    )
    smoke_parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Per-command timeout in seconds.",
    )

    # run subcommand (full benchmark)
    run_parser = subparsers.add_parser("run", help="Run full benchmark suite")
    run_parser.add_argument(
        "--comparators",
        nargs="+",
        default=ALL_COMPARATORS,
        help="Comparators to include.",
    )
    run_parser.add_argument(
        "--scenarios",
        nargs="+",
        default=None,
        help="Specific scenario IDs (default: all).",
    )
    run_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Override output directory.",
    )
    run_parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Per-command timeout in seconds.",
    )

    args = parser.parse_args()

    if args.subcommand is None:
        parser.print_help()
        sys.exit(1)

    if args.subcommand == "smoke":
        output_dir = Path(args.output_dir) if args.output_dir else None
        manifest = run_smoke(
            comparators=args.comparators,
            output_dir=output_dir,
            scenario_ids=args.scenarios,
            timeout=args.timeout,
        )
        # Exit with error if any cells had errors.
        if manifest["cell_totals"]["errors"] > 0:
            sys.exit(1)
        sys.exit(0)

    elif args.subcommand == "run":
        # Full run uses all scenarios from manifests.
        output_dir = Path(args.output_dir) if args.output_dir else None
        scenarios_manifest = _load_json(SCENARIOS_PATH)
        all_ids = [s["id"] for s in scenarios_manifest["scenarios"]]
        scenario_ids = args.scenarios if args.scenarios else all_ids

        manifest = run_smoke(
            comparators=args.comparators,
            output_dir=output_dir,
            scenario_ids=scenario_ids,
            timeout=args.timeout,
        )
        # Correct run_type.
        manifest["run_type"] = "full"

        # Re-write manifest with correct type.
        if output_dir:
            _write_json(output_dir / "run_manifest.json", manifest)
        else:
            # Default output dir from manifest.
            out = BENCHMARKS_OUT / manifest["run_id"]
            if out.exists():
                _write_json(out / "run_manifest.json", manifest)

        if manifest["cell_totals"]["errors"] > 0:
            sys.exit(1)
        sys.exit(0)


if __name__ == "__main__":
    main()
