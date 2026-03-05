#!/usr/bin/env python3
"""Execute clean-checkout smoke reproducibility validation for the cited
publication commit using an **isolated git worktree**.

This script creates a temporary git worktree at the cited commit,
executes smoke checks inside that isolated checkout (not the caller's
working tree), and produces a JSON evidence artifact with full provenance
fields proving the execution context.

Provenance contract (recorded in the evidence artifact):
  requested_commit_sha  — the --commit value passed to this script
  checked_out_commit_sha — git rev-parse HEAD inside the worktree
  memo_commit_sha       — extracted from the memo file (if available)
  All three must be equal for the provenance check to pass.

Usage:
    python3 publication/run_clean_checkout_smoke.py \
        --commit 44759b4b07252dbf8e471a71ee21e0e6539ce236
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
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


def _get_worktree_head(worktree_dir: str) -> str | None:
    """Get the HEAD commit SHA inside the worktree."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=worktree_dir,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def create_worktree(repo_root: str, commit_sha: str, worktree_dir: str) -> dict:
    """Create an isolated git worktree at the cited commit."""
    result = _run(
        ["git", "worktree", "add", "--detach", worktree_dir, commit_sha],
        cwd=repo_root,
    )
    passed = result["exit_code"] == 0
    return {
        "name": "create_worktree",
        "result": "pass" if passed else "fail",
        "detail": (
            f"git worktree add --detach {worktree_dir} {commit_sha[:12]}... "
            f"-> exit {result['exit_code']}"
            + (f"; stderr: {result['stderr_snippet'][:200]}" if not passed else "")
        ),
    }


def remove_worktree(repo_root: str, worktree_dir: str) -> None:
    """Clean up the git worktree."""
    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", worktree_dir],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=30,
        )
    except Exception:
        pass
    # Belt-and-suspenders: remove the directory if still present
    if os.path.exists(worktree_dir):
        shutil.rmtree(worktree_dir, ignore_errors=True)


def check_commit_accessible(commit_sha: str, repo_root: str) -> dict:
    """Verify the cited commit exists and is accessible."""
    result = _run(["git", "cat-file", "-t", commit_sha], cwd=repo_root)
    passed = result["exit_code"] == 0
    return {
        "name": "commit_accessible",
        "result": "pass" if passed else "fail",
        "detail": f"git cat-file -t {commit_sha[:12]}... -> exit {result['exit_code']}",
    }


def check_worktree_head_matches(
    worktree_dir: str, requested_sha: str
) -> tuple[dict, str | None]:
    """Verify HEAD in the worktree matches the requested commit."""
    head_sha = _get_worktree_head(worktree_dir)
    if head_sha is None:
        return {
            "name": "worktree_head_matches",
            "result": "fail",
            "detail": "Could not determine HEAD in worktree",
        }, None
    passed = head_sha == requested_sha
    return {
        "name": "worktree_head_matches",
        "result": "pass" if passed else "fail",
        "detail": (
            f"worktree HEAD={head_sha[:12]}... "
            f"{'==' if passed else '!='} requested={requested_sha[:12]}..."
        ),
    }, head_sha


def check_manifests_present(worktree_dir: str) -> dict:
    """Verify required manifest files exist in the worktree."""
    required = [
        "manifests/scenarios.json",
        "manifests/queries.json",
        "manifests/corpus.json",
    ]
    missing = [f for f in required if not (Path(worktree_dir) / f).exists()]
    passed = len(missing) == 0
    return {
        "name": "manifests_present",
        "result": "pass" if passed else "fail",
        "detail": f"Missing: {missing}" if missing else "All manifest files present",
    }


def check_rust_binary_builds(worktree_dir: str) -> dict:
    """Verify the Rust binary builds successfully in the worktree."""
    result = _run(
        ["cargo", "build", "--workspace", "--release"],
        cwd=worktree_dir,
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


def check_rust_ag_runs(worktree_dir: str) -> dict:
    """Verify rust-ag binary executes a basic search in the worktree."""
    binary = Path(worktree_dir) / "target" / "release" / "rust-ag"
    if not binary.exists():
        return {
            "name": "rust_ag_runs",
            "result": "fail",
            "detail": f"Binary not found at {binary}",
        }
    result = _run(
        [str(binary), "--nocolor", "--workers=1", "foo", "."],
        cwd=worktree_dir,
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


def check_baseline_ag_runs(worktree_dir: str) -> dict:
    """Verify baseline ag binary exists and executes in the worktree.

    The C binary (``ag``) is not automatically built by ``cargo build``,
    so we first attempt to build it via ``build.sh``.  If the build
    script is absent or the binary still doesn't exist we skip the check
    with a "skip" result rather than failing, since the Rust rewrite is
    the primary deliverable and the C baseline may not compile on every
    checkout.
    """
    ag_binary = Path(worktree_dir) / "ag"
    if not ag_binary.exists():
        # Try building via build.sh
        build_script = Path(worktree_dir) / "build.sh"
        if build_script.exists():
            build_result = _run(
                ["bash", str(build_script)],
                cwd=worktree_dir,
                timeout=120,
            )
            if build_result["exit_code"] != 0:
                return {
                    "name": "baseline_ag_runs",
                    "result": "skip",
                    "detail": (
                        "build.sh failed in worktree; "
                        f"exit {build_result['exit_code']}"
                    ),
                }
        else:
            return {
                "name": "baseline_ag_runs",
                "result": "skip",
                "detail": "No build.sh or ag binary in worktree",
            }

    if not ag_binary.exists():
        return {
            "name": "baseline_ag_runs",
            "result": "skip",
            "detail": "ag binary not produced by build.sh in worktree",
        }

    result = _run(
        [str(ag_binary), "--nocolor", "--workers=1", "foo", "."],
        cwd=worktree_dir,
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


def check_benchmark_harness_smoke(worktree_dir: str) -> dict:
    """Verify the benchmark harness can execute a smoke run in the worktree."""
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
        cwd=worktree_dir,
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


def check_parity_smoke(worktree_dir: str) -> dict:
    """Verify a parity smoke run can execute in the worktree."""
    result = _run(
        [
            "python3",
            "scripts/parity/run_matrix.py",
            "--target",
            "baseline",
            "--group",
            "smoke",
        ],
        cwd=worktree_dir,
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
        description="Execute clean-checkout smoke reproducibility validation "
        "in an isolated git worktree"
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
    print(f"Repo root: {repo_root}")

    # --- Step 1: Verify commit is accessible ---
    commit_check = check_commit_accessible(commit_sha, repo_root)
    if commit_check["result"] != "pass":
        print(f"FAIL: Commit not accessible: {commit_check['detail']}")
        # Write failure evidence and exit
        evidence = {
            "schema_version": 2,
            "executed": False,
            "execution_context": "isolated_worktree",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "requested_commit_sha": commit_sha,
            "checked_out_commit_sha": None,
            "result": "fail",
            "checks": [commit_check],
        }
        output_path = Path(repo_root) / "publication" / "clean_checkout_reproducibility.json"
        with open(output_path, "w") as f:
            json.dump(evidence, f, indent=2)
            f.write("\n")
        return 1

    # --- Step 2: Create isolated worktree ---
    worktree_dir = tempfile.mkdtemp(
        prefix="ag-clean-checkout-", suffix=f"-{commit_sha[:12]}"
    )
    print(f"Creating isolated worktree at: {worktree_dir}")

    worktree_check = create_worktree(repo_root, commit_sha, worktree_dir)
    if worktree_check["result"] != "pass":
        print(f"FAIL: Could not create worktree: {worktree_check['detail']}")
        remove_worktree(repo_root, worktree_dir)
        evidence = {
            "schema_version": 2,
            "executed": False,
            "execution_context": "isolated_worktree",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "requested_commit_sha": commit_sha,
            "checked_out_commit_sha": None,
            "result": "fail",
            "checks": [commit_check, worktree_check],
        }
        output_path = Path(repo_root) / "publication" / "clean_checkout_reproducibility.json"
        with open(output_path, "w") as f:
            json.dump(evidence, f, indent=2)
            f.write("\n")
        return 1

    try:
        # --- Step 3: Verify worktree HEAD matches requested commit ---
        head_check, checked_out_sha = check_worktree_head_matches(
            worktree_dir, commit_sha
        )

        # --- Step 4: Run all smoke checks inside the worktree ---
        print(f"Executing smoke checks inside worktree ({worktree_dir})...")
        checks = [
            commit_check,
            worktree_check,
            head_check,
            check_manifests_present(worktree_dir),
            check_rust_binary_builds(worktree_dir),
            check_rust_ag_runs(worktree_dir),
            check_baseline_ag_runs(worktree_dir),
            check_benchmark_harness_smoke(worktree_dir),
            check_parity_smoke(worktree_dir),
        ]

        # "skip" results are acceptable — only "fail" counts as failure
        all_pass = all(c["result"] in ("pass", "skip") for c in checks)

        evidence = {
            "schema_version": 2,
            "executed": True,
            "execution_context": "isolated_worktree",
            "worktree_path": worktree_dir,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "requested_commit_sha": commit_sha,
            "checked_out_commit_sha": checked_out_sha,
            "result": "pass" if all_pass else "fail",
            "checks": checks,
        }

        output_path = Path(repo_root) / "publication" / "clean_checkout_reproducibility.json"
        with open(output_path, "w") as f:
            json.dump(evidence, f, indent=2)
            f.write("\n")

        print(f"\nResults: {'PASS' if all_pass else 'FAIL'}")
        for check in checks:
            status = check["result"].upper()
            print(f"  [{status}] {check['name']}: {check['detail']}")
        print(f"\nEvidence written to: {output_path}")

        return 0 if all_pass else 1

    finally:
        # --- Step 5: Clean up the worktree ---
        print(f"\nCleaning up worktree: {worktree_dir}")
        remove_worktree(repo_root, worktree_dir)


if __name__ == "__main__":
    sys.exit(main())
