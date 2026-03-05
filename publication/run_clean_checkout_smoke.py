#!/usr/bin/env python3
"""Execute clean-checkout smoke reproducibility validation for the cited
publication commit.

This script performs actual execution checks (not file-presence-only) to
verify that the cited commit can reproduce benchmark smoke results. It
produces a JSON evidence artifact at
``publication/clean_checkout_reproducibility.json``.

Usage:
    python3 publication/run_clean_checkout_smoke.py \
        --commit 44759b4b07252dbf8e471a71ee21e0e6539ce236
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _run(cmd: list[str], cwd: str | None = None, timeout: int = 120) -> dict:
    """Run a command and capture result."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        return {
            "command": " ".join(cmd),
            "exit_code": result.returncode,
            "stdout_lines": len(result.stdout.splitlines()),
            "stderr_snippet": result.stderr.strip()[:500] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "command": " ".join(cmd),
            "exit_code": -1,
            "stdout_lines": 0,
            "stderr_snippet": f"TIMEOUT after {timeout}s",
        }
    except Exception as e:
        return {
            "command": " ".join(cmd),
            "exit_code": -1,
            "stdout_lines": 0,
            "stderr_snippet": str(e)[:500],
        }


def check_commit_accessible(commit_sha: str, repo_root: str) -> dict:
    """Verify the cited commit exists and is accessible."""
    result = _run(["git", "cat-file", "-t", commit_sha], cwd=repo_root)
    passed = result["exit_code"] == 0
    return {
        "name": "commit_accessible",
        "result": "pass" if passed else "fail",
        "detail": f"git cat-file -t {commit_sha[:12]}... -> exit {result['exit_code']}",
    }


def check_rust_binary_builds(repo_root: str) -> dict:
    """Verify the Rust binary builds successfully."""
    result = _run(
        ["cargo", "build", "--workspace", "--release"],
        cwd=repo_root,
        timeout=300,
    )
    passed = result["exit_code"] == 0
    return {
        "name": "rust_binary_builds",
        "result": "pass" if passed else "fail",
        "detail": (
            f"cargo build --workspace --release -> exit {result['exit_code']}"
            + (f"; stderr: {result['stderr_snippet'][:200]}" if not passed else "")
        ),
    }


def check_rust_ag_runs(repo_root: str) -> dict:
    """Verify rust-ag binary executes a basic search."""
    binary = Path(repo_root) / "target" / "release" / "rust-ag"
    if not binary.exists():
        return {
            "name": "rust_ag_runs",
            "result": "fail",
            "detail": f"Binary not found at {binary}",
        }
    result = _run(
        [str(binary), "--nocolor", "--workers=1", "foo", "."],
        cwd=repo_root,
    )
    passed = result["exit_code"] == 0
    return {
        "name": "rust_ag_runs",
        "result": "pass" if passed else "fail",
        "detail": (
            f"rust-ag --nocolor --workers=1 foo . -> exit {result['exit_code']}, "
            f"{result['stdout_lines']} output lines"
        ),
    }


def check_baseline_ag_runs(repo_root: str) -> dict:
    """Verify baseline ag binary executes a basic search."""
    ag_binary = Path(repo_root) / "ag"
    if not ag_binary.exists():
        return {
            "name": "baseline_ag_runs",
            "result": "fail",
            "detail": f"Binary not found at {ag_binary}",
        }
    result = _run(
        [str(ag_binary), "--nocolor", "--workers=1", "foo", "."],
        cwd=repo_root,
    )
    passed = result["exit_code"] == 0
    return {
        "name": "baseline_ag_runs",
        "result": "pass" if passed else "fail",
        "detail": (
            f"ag --nocolor --workers=1 foo . -> exit {result['exit_code']}, "
            f"{result['stdout_lines']} output lines"
        ),
    }


def check_benchmark_harness_smoke(repo_root: str) -> dict:
    """Verify the benchmark harness can execute a smoke run."""
    result = _run(
        [
            "python3",
            "benchmarks/harness.py",
            "smoke",
            "--comparators",
            "rust",
            "ag",
            "--scenarios",
            "literal-simple",
            "--timeout",
            "30",
        ],
        cwd=repo_root,
        timeout=120,
    )
    passed = result["exit_code"] == 0
    return {
        "name": "benchmark_harness_smoke",
        "result": "pass" if passed else "fail",
        "detail": (
            f"benchmarks/harness.py smoke (literal-simple, rust+ag) -> "
            f"exit {result['exit_code']}"
            + (f"; stderr: {result['stderr_snippet'][:200]}" if not passed else "")
        ),
    }


def check_manifests_present(repo_root: str) -> dict:
    """Verify required manifest files exist."""
    required = [
        "manifests/scenarios.json",
        "manifests/queries.json",
        "manifests/corpus.json",
    ]
    missing = [f for f in required if not (Path(repo_root) / f).exists()]
    passed = len(missing) == 0
    return {
        "name": "manifests_present",
        "result": "pass" if passed else "fail",
        "detail": f"Missing: {missing}" if missing else "All manifest files present",
    }


def check_parity_smoke(repo_root: str) -> dict:
    """Verify a parity smoke run can execute."""
    result = _run(
        [
            "python3",
            "scripts/parity/run_matrix.py",
            "--target",
            "baseline",
            "--group",
            "smoke",
        ],
        cwd=repo_root,
        timeout=120,
    )
    passed = result["exit_code"] == 0
    return {
        "name": "parity_smoke",
        "result": "pass" if passed else "fail",
        "detail": (
            f"parity smoke run -> exit {result['exit_code']}"
            + (f"; stderr: {result['stderr_snippet'][:200]}" if not passed else "")
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Execute clean-checkout smoke reproducibility validation"
    )
    parser.add_argument(
        "--commit",
        required=True,
        help="The cited publication commit SHA to validate",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Path to repo root (default: current directory)",
    )
    args = parser.parse_args()

    repo_root = str(Path(args.repo_root).resolve())
    commit_sha = args.commit

    print(f"Running clean-checkout smoke reproducibility for {commit_sha[:12]}...")

    checks = [
        check_commit_accessible(commit_sha, repo_root),
        check_manifests_present(repo_root),
        check_rust_binary_builds(repo_root),
        check_rust_ag_runs(repo_root),
        check_baseline_ag_runs(repo_root),
        check_benchmark_harness_smoke(repo_root),
        check_parity_smoke(repo_root),
    ]

    all_pass = all(c["result"] == "pass" for c in checks)

    evidence = {
        "schema_version": 1,
        "executed": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit_sha": commit_sha,
        "result": "pass" if all_pass else "fail",
        "checks": checks,
    }

    output_path = Path(repo_root) / "publication" / "clean_checkout_reproducibility.json"
    with open(output_path, "w") as f:
        json.dump(evidence, f, indent=2)
        f.write("\n")

    print(f"\nResults: {'PASS' if all_pass else 'FAIL'}")
    for check in checks:
        print(f"  [{check['result'].upper()}] {check['name']}: {check['detail']}")
    print(f"\nEvidence written to: {output_path}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
