#!/usr/bin/env python3
"""Validate and collect full environment metadata for benchmark runs.

VAL-BENCH-005: Environment metadata is complete.
    Each benchmark run captures environment metadata (OS, CPU, memory,
    toolchains, commit SHA, timestamp).

Provides:
  - collect_full_environment_metadata() — gathers OS, CPU, memory, toolchains.
  - validate_env_metadata_schema() — validates a metadata dict against schema.
  - write_env_metadata_artifact() — writes metadata to a JSON file.

Usage:
    python3 benchmarks/validate_env_metadata.py --run latest
    python3 benchmarks/validate_env_metadata.py --run-dir /path/to/run/dir
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_OUT = REPO_ROOT / "benchmarks" / "out"

# ---------------------------------------------------------------------------
# Schema definition
# ---------------------------------------------------------------------------

# Required top-level fields and their expected types.
_REQUIRED_TOP_LEVEL = {
    "schema_version": int,
    "timestamp": str,
    "commit_sha": str,
    "platform": dict,
    "cpu": dict,
    "memory": dict,
    "toolchains": dict,
}

_REQUIRED_PLATFORM = {"system": str, "release": str, "machine": str, "python": str}
_REQUIRED_CPU = {"brand": str, "cores_physical": int, "cores_logical": int}
_REQUIRED_MEMORY = {"total_bytes": int, "total_human": str}
_REQUIRED_TOOLCHAINS = {"rust": str, "python": str}


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def validate_env_metadata_schema(meta: dict[str, Any]) -> list[str]:
    """Validate environment metadata against required schema.

    Returns a list of error strings. Empty list means valid.
    """
    errors: list[str] = []

    # Top-level fields.
    for field, expected_type in _REQUIRED_TOP_LEVEL.items():
        if field not in meta:
            errors.append(f"Missing required field: {field}")
        elif not isinstance(meta[field], expected_type):
            errors.append(
                f"Field '{field}' should be {expected_type.__name__}, "
                f"got {type(meta[field]).__name__}"
            )

    # Platform sub-fields.
    if "platform" in meta and isinstance(meta["platform"], dict):
        for field, expected_type in _REQUIRED_PLATFORM.items():
            if field not in meta["platform"]:
                errors.append(f"Missing platform.{field}")
            elif not isinstance(meta["platform"][field], expected_type):
                errors.append(
                    f"platform.{field} should be {expected_type.__name__}"
                )

    # CPU sub-fields.
    if "cpu" in meta and isinstance(meta["cpu"], dict):
        for field, expected_type in _REQUIRED_CPU.items():
            if field not in meta["cpu"]:
                errors.append(f"Missing cpu.{field}")
            elif not isinstance(meta["cpu"][field], expected_type):
                errors.append(f"cpu.{field} should be {expected_type.__name__}")

    # Memory sub-fields.
    if "memory" in meta and isinstance(meta["memory"], dict):
        for field, expected_type in _REQUIRED_MEMORY.items():
            if field not in meta["memory"]:
                errors.append(f"Missing memory.{field}")
            elif not isinstance(meta["memory"][field], expected_type):
                errors.append(
                    f"memory.{field} should be {expected_type.__name__}"
                )

    # Toolchains sub-fields.
    if "toolchains" in meta and isinstance(meta["toolchains"], dict):
        for field, expected_type in _REQUIRED_TOOLCHAINS.items():
            if field not in meta["toolchains"]:
                errors.append(f"Missing toolchains.{field}")
            elif not isinstance(meta["toolchains"][field], expected_type):
                errors.append(
                    f"toolchains.{field} should be {expected_type.__name__}"
                )

    return errors


# ---------------------------------------------------------------------------
# Environment metadata collection
# ---------------------------------------------------------------------------


def _run_capture(cmd: list[str], timeout: int = 10) -> str:
    """Run a command and capture the first non-empty line of output."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        output = (result.stdout or result.stderr).strip()
        for line in output.splitlines():
            if line.strip():
                return line.strip()
        return output
    except Exception as e:
        return f"error: {e}"


def _get_cpu_brand() -> str:
    """Get CPU brand string."""
    system = platform.system()
    if system == "Darwin":
        return _run_capture(["sysctl", "-n", "machdep.cpu.brand_string"])
    elif system == "Linux":
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except (FileNotFoundError, PermissionError):
            pass
        return _run_capture(["lscpu"])
    return platform.processor() or "unknown"


def _get_cpu_cores() -> tuple[int, int]:
    """Get (physical, logical) core counts."""
    logical = os.cpu_count() or 0
    system = platform.system()
    if system == "Darwin":
        try:
            phys = int(_run_capture(["sysctl", "-n", "hw.physicalcpu"]))
        except (ValueError, TypeError):
            phys = logical
    elif system == "Linux":
        try:
            # Count physical cores from /proc/cpuinfo
            with open("/proc/cpuinfo") as f:
                core_ids = set()
                for line in f:
                    if line.startswith("core id"):
                        core_ids.add(line.split(":", 1)[1].strip())
                phys = len(core_ids) if core_ids else logical
        except (FileNotFoundError, PermissionError):
            phys = logical
    else:
        phys = logical
    return phys, logical


def _get_total_memory() -> tuple[int, str]:
    """Get (total_bytes, human_readable) memory."""
    system = platform.system()
    total_bytes = 0
    if system == "Darwin":
        try:
            total_bytes = int(_run_capture(["sysctl", "-n", "hw.memsize"]))
        except (ValueError, TypeError):
            total_bytes = 0
    elif system == "Linux":
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        kb = int(line.split()[1])
                        total_bytes = kb * 1024
                        break
        except (FileNotFoundError, PermissionError):
            total_bytes = 0

    if total_bytes > 0:
        gib = total_bytes / (1024 ** 3)
        human = f"{gib:.1f} GiB"
    else:
        human = "unknown"

    return total_bytes, human


def _get_rust_version() -> str:
    """Get Rust compiler version string."""
    return _run_capture(["rustc", "--version"])


def _get_cargo_version() -> str:
    """Get Cargo version string."""
    return _run_capture(["cargo", "--version"])


def _git_sha() -> str:
    """Get current git HEAD SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True,
            cwd=REPO_ROOT, timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def collect_full_environment_metadata() -> dict[str, Any]:
    """Collect comprehensive environment metadata.

    Returns a dict conforming to the environment metadata schema with
    OS, CPU, memory, toolchain, commit SHA, and timestamp info.
    """
    phys_cores, logical_cores = _get_cpu_cores()
    total_bytes, total_human = _get_total_memory()

    return {
        "schema_version": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit_sha": _git_sha(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "cpu": {
            "brand": _get_cpu_brand(),
            "cores_physical": phys_cores,
            "cores_logical": logical_cores,
        },
        "memory": {
            "total_bytes": total_bytes,
            "total_human": total_human,
        },
        "toolchains": {
            "rust": _get_rust_version(),
            "cargo": _get_cargo_version(),
            "python": platform.python_version(),
        },
    }


# ---------------------------------------------------------------------------
# Artifact writing
# ---------------------------------------------------------------------------


def write_env_metadata_artifact(
    meta: dict[str, Any],
    output_dir: Path,
) -> Path:
    """Write environment metadata as a JSON artifact.

    Returns the path to the written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "environment_metadata.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=False, ensure_ascii=False)
        f.write("\n")
    return path


# ---------------------------------------------------------------------------
# CLI: validate existing run metadata
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
        description="Validate environment metadata for a benchmark run."
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

    # Check for environment_metadata.json in run directory.
    meta_path = run_dir / "environment_metadata.json"
    if not meta_path.exists():
        print(
            f"ERROR: environment_metadata.json not found in {run_dir}",
            file=sys.stderr,
        )
        sys.exit(2)

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    errors = validate_env_metadata_schema(meta)

    print(f"\nEnvironment Metadata Validation: {run_dir.name}")
    print(f"  File: {meta_path}")

    if errors:
        print(f"\n  FAIL: {len(errors)} schema error(s)")
        for err in errors:
            print(f"    - {err}")
        sys.exit(1)
    else:
        print("  OK: Schema validation passed")
        print(f"  System: {meta['platform']['system']} {meta['platform']['release']}")
        print(f"  CPU: {meta['cpu']['brand']}")
        print(f"  Cores: {meta['cpu']['cores_physical']}p / {meta['cpu']['cores_logical']}l")
        print(f"  Memory: {meta['memory']['total_human']}")
        print(f"  Rust: {meta['toolchains']['rust']}")
        print(f"  Commit: {meta['commit_sha']}")
        sys.exit(0)


if __name__ == "__main__":
    main()
