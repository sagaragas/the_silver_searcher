#!/usr/bin/env python3
"""Hardened latest-run resolution for benchmark infrastructure.

Provides a single canonical ``resolve_run_dir`` that every benchmark
validator/gate script should use when ``--run latest`` is specified.
The logic filters out transient temporary directories (e.g. pytest
``tmp_path``) so that ``--run latest`` is always deterministic and
trustworthy.

Design invariants:
    1. A *canonical* run directory lives directly inside BENCHMARKS_OUT
       and matches the timestamp pattern ``YYYYMMDDTHHMMSSZ``.
    2. The ``latest`` symlink is only trusted when its resolved target
       is itself a canonical run directory.
    3. The fallback scan (when the symlink is absent or untrusted)
       considers only canonical directories.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_OUT = REPO_ROOT / "benchmarks" / "out"

# Matches harness-generated run IDs like ``20260305T152433Z``.
_CANONICAL_RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z$")


def is_canonical_run_dir(path: Path, base: Path | None = None) -> bool:
    """Return True if *path* is a canonical benchmark run directory.

    A canonical run directory:
      * is an existing directory (not a symlink itself),
      * has a name matching ``YYYYMMDDTHHMMSSZ``,
      * resides directly inside the benchmark output base directory.
    """
    if base is None:
        base = BENCHMARKS_OUT
    # Reject symlinks — we want the actual directory, not an alias.
    if path.is_symlink():
        return False
    resolved_base = base.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_dir():
        return False
    if not _CANONICAL_RUN_ID_RE.match(resolved_path.name):
        return False
    # Must be a direct child of the base output directory.
    try:
        resolved_path.relative_to(resolved_base)
    except ValueError:
        return False
    if resolved_path.parent.resolve() != resolved_base:
        return False
    return True


def resolve_run_dir(
    run_id: str | None,
    run_dir: str | None = None,
    *,
    benchmarks_out: Path | None = None,
) -> Path:
    """Resolve a benchmark run directory with hardened latest-run logic.

    Parameters
    ----------
    run_id:
        Either ``"latest"`` or an explicit run ID (timestamp string).
    run_dir:
        Explicit path override — returned directly when given.
    benchmarks_out:
        Base output directory (defaults to ``BENCHMARKS_OUT``).

    Returns the resolved ``Path`` to the run directory.
    Exits with code 2 on unrecoverable resolution failure.
    """
    if benchmarks_out is None:
        benchmarks_out = BENCHMARKS_OUT

    if run_dir:
        return Path(run_dir)

    if run_id == "latest":
        latest_link = benchmarks_out / "latest"
        if latest_link.is_symlink():
            target = latest_link.resolve()
            if is_canonical_run_dir(target, base=benchmarks_out):
                return target
            # Symlink exists but points outside the canonical tree
            # (e.g. a pytest tmp_path).  Fall through to directory scan.
            print(
                f"WARNING: 'latest' symlink target is not a canonical run "
                f"directory (resolved to {target}); falling back to "
                f"directory scan.",
                file=sys.stderr,
            )

        # Fallback: find most recent canonical run directory.
        if not benchmarks_out.exists():
            print(
                "ERROR: No benchmark output directory found",
                file=sys.stderr,
            )
            sys.exit(2)

        runs = sorted(
            [
                d
                for d in benchmarks_out.iterdir()
                if d.is_dir()
                and not d.is_symlink()
                and _CANONICAL_RUN_ID_RE.match(d.name)
            ],
            key=lambda d: d.name,
            reverse=True,
        )
        if not runs:
            print("ERROR: No canonical benchmark runs found", file=sys.stderr)
            sys.exit(2)
        return runs[0]

    return benchmarks_out / run_id
