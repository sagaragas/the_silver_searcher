#!/usr/bin/env python3
"""Verify checksums of a publication artifact bundle.

Reads the publication manifest and verifies SHA-256 checksums for all
listed artifacts. Reports mismatches, missing files, and overall gate status.

VAL-BENCH-008: Raw benchmark artifacts are publishable.

Usage:
    python3 benchmarks/verify_checksums.py --manifest benchmarks/out/latest/publication/publication_manifest.json
    python3 benchmarks/verify_checksums.py --manifest /path/to/publication_manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
# Verification
# ---------------------------------------------------------------------------


def verify_checksums(manifest_path: Path) -> dict[str, Any]:
    """Verify all checksums listed in a publication manifest.

    Args:
        manifest_path: Path to the publication_manifest.json file.

    Returns:
        A verification report dict with gate status, verified/mismatched/missing
        file lists.
    """
    pub_dir = manifest_path.parent
    pub_manifest = _load_json(manifest_path)

    checksums: dict[str, str] = pub_manifest.get("checksums", {})

    verified: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for filename, expected_hash in checksums.items():
        artifact_path = pub_dir / filename
        if not artifact_path.exists():
            missing.append({
                "file": filename,
                "expected_hash": expected_hash,
            })
            continue

        actual_hash = _sha256_file(artifact_path)
        if actual_hash == expected_hash:
            verified.append({
                "file": filename,
                "hash": actual_hash,
            })
        else:
            mismatches.append({
                "file": filename,
                "expected_hash": expected_hash,
                "actual_hash": actual_hash,
            })

    # --- Checksum coverage enforcement ---
    # Every artifact listed in the manifest (except checksums.sha256 and
    # publication_manifest.json themselves) must have a checksum entry.
    # Files without checksums are "uncovered" and cause a gate failure.
    excluded_from_coverage = {"checksums.sha256", "publication_manifest.json"}
    artifacts_list: list[dict[str, Any]] = pub_manifest.get("artifacts", [])
    artifact_names = {
        a["name"]
        for a in artifacts_list
        if a.get("name") not in excluded_from_coverage
    }
    uncovered: list[dict[str, Any]] = []
    for name in sorted(artifact_names):
        if name not in checksums:
            uncovered.append({"file": name})

    gate = "pass" if not mismatches and not missing and not uncovered else "fail"

    report: dict[str, Any] = {
        "schema_version": 1,
        "gate": gate,
        "timestamp": _now_iso(),
        "manifest_path": str(manifest_path),
        "total_checked": len(checksums),
        "verified_count": len(verified),
        "mismatch_count": len(mismatches),
        "missing_count": len(missing),
        "uncovered_count": len(uncovered),
        "verified": verified,
        "mismatches": mismatches,
        "missing": missing,
        "uncovered": uncovered,
    }

    # Write verification report alongside the manifest.
    report_path = pub_dir / "checksum_verification.json"
    _write_json(report_path, report)

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify SHA-256 checksums in a publication artifact bundle."
    )
    parser.add_argument(
        "--manifest",
        type=str,
        required=True,
        help="Path to the publication_manifest.json file.",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"ERROR: Manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(2)

    result = verify_checksums(manifest_path)

    # Print summary.
    print(f"\nChecksum Verification: {result['gate'].upper()}")
    print(f"  Manifest:  {manifest_path}")
    print(f"  Checked:   {result['total_checked']}")
    print(f"  Verified:  {result['verified_count']}")
    print(f"  Mismatches: {result['mismatch_count']}")
    print(f"  Missing:   {result['missing_count']}")
    print(f"  Uncovered: {result['uncovered_count']}")

    if result["mismatches"]:
        print("\n  Mismatched files:")
        for m in result["mismatches"]:
            print(f"    {m['file']}:")
            print(f"      expected: {m['expected_hash'][:16]}…")
            print(f"      actual:   {m['actual_hash'][:16]}…")

    if result["missing"]:
        print("\n  Missing files:")
        for m in result["missing"]:
            print(f"    {m['file']}")

    if result["uncovered"]:
        print("\n  Uncovered artifacts (no checksum):")
        for u in result["uncovered"]:
            print(f"    {u['file']}")

    report_path = manifest_path.parent / "checksum_verification.json"
    print(f"\n  Verification report: {report_path}")

    sys.exit(0 if result["gate"] == "pass" else 1)


if __name__ == "__main__":
    main()
