#!/usr/bin/env python3
"""Build deterministic fixture manifest with stable SHA-256 checksums.

Walks the test fixtures directory and produces a JSON manifest that
records every fixture file's relative path, size, and content hash.
The manifest itself carries a top-level checksum so downstream tools
can verify corpus identity in a single comparison.

Usage:
    python3 scripts/parity/build_fixture_manifest.py          # generate
    python3 scripts/parity/build_fixture_manifest.py --verify  # verify existing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "manifests" / "fixtures.json"

# Directories that contain fixture / corpus material.
# Paths are relative to REPO_ROOT.
FIXTURE_DIRS = [
    "tests",
]

# Files to skip (build artifacts, caches, etc.)
SKIP_PATTERNS = {
    ".deps",
    ".dirstamp",
    "__pycache__",
    ".pyc",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    """Return hex SHA-256 of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _should_skip(rel: str) -> bool:
    """Return True if the relative path should be excluded."""
    parts = rel.split(os.sep)
    return any(p in SKIP_PATTERNS or p.endswith(".pyc") for p in parts)


def _collect_entries(fixture_dirs: list[str]) -> list[dict[str, Any]]:
    """Walk fixture directories and collect sorted manifest entries."""
    entries: list[dict[str, Any]] = []
    for fixture_dir in fixture_dirs:
        base = REPO_ROOT / fixture_dir
        if not base.is_dir():
            continue
        for root_str, dirs, files in os.walk(base, followlinks=False):
            root = Path(root_str)
            # Sort dirs in-place for deterministic walk order.
            dirs[:] = sorted(d for d in dirs if d not in SKIP_PATTERNS)
            for fname in sorted(files):
                fpath = root / fname
                rel = str(fpath.relative_to(REPO_ROOT))
                if _should_skip(rel):
                    continue
                # Skip broken symlinks (they can't be stat'd or hashed).
                if fpath.is_symlink() and not fpath.exists():
                    continue
                try:
                    entries.append(
                        {
                            "path": rel,
                            "size": fpath.stat().st_size,
                            "sha256": _sha256_file(fpath),
                        }
                    )
                except OSError:
                    # Skip files that can't be read (permissions, broken links, etc.)
                    continue
    # Final sort by path for deterministic output regardless of walk order.
    entries.sort(key=lambda e: e["path"])
    return entries


def _manifest_hash(entries: list[dict[str, Any]]) -> str:
    """Compute a single SHA-256 over the sorted entry list.

    This is the "manifest hash" that downstream tools compare to verify
    that the fixture corpus is identical across runs.
    """
    h = hashlib.sha256()
    for entry in entries:
        # Deterministic serialisation: path + size + sha256 separated by NUL.
        record = f"{entry['path']}\0{entry['size']}\0{entry['sha256']}\n"
        h.update(record.encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Build / Verify
# ---------------------------------------------------------------------------


def build_manifest() -> dict[str, Any]:
    """Generate the manifest dict."""
    entries = _collect_entries(FIXTURE_DIRS)
    mhash = _manifest_hash(entries)
    return {
        "schema_version": 1,
        "description": "Deterministic fixture manifest for ag baseline parity tests",
        "fixture_dirs": FIXTURE_DIRS,
        "manifest_hash": mhash,
        "file_count": len(entries),
        "files": entries,
    }


def write_manifest(manifest: dict[str, Any]) -> None:
    """Write manifest to disk with deterministic formatting."""
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=False, ensure_ascii=False)
        f.write("\n")


def verify_manifest() -> bool:
    """Regenerate manifest and compare against on-disk version.

    Returns True if they match, False otherwise.
    """
    if not MANIFEST_PATH.exists():
        print(f"FAIL: manifest not found at {MANIFEST_PATH}", file=sys.stderr)
        return False

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        existing = json.load(f)

    fresh = build_manifest()

    if existing.get("manifest_hash") != fresh["manifest_hash"]:
        print(
            f"FAIL: manifest hash mismatch\n"
            f"  on-disk:  {existing.get('manifest_hash')}\n"
            f"  freshly:  {fresh['manifest_hash']}",
            file=sys.stderr,
        )
        # Show which files differ.
        existing_by_path = {e["path"]: e for e in existing.get("files", [])}
        fresh_by_path = {e["path"]: e for e in fresh["files"]}
        all_paths = sorted(set(existing_by_path) | set(fresh_by_path))
        for p in all_paths:
            e = existing_by_path.get(p)
            fr = fresh_by_path.get(p)
            if e is None:
                print(f"  + {p} (new file)", file=sys.stderr)
            elif fr is None:
                print(f"  - {p} (removed)", file=sys.stderr)
            elif e["sha256"] != fr["sha256"]:
                print(f"  ~ {p} (content changed)", file=sys.stderr)
        return False

    print(
        f"OK: fixture manifest verified ({fresh['file_count']} files, "
        f"hash={fresh['manifest_hash'][:16]}…)"
    )
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build or verify deterministic fixture manifest."
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify existing manifest matches freshly generated one.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Override output path (default: manifests/fixtures.json).",
    )
    args = parser.parse_args()

    if args.verify:
        ok = verify_manifest()
        sys.exit(0 if ok else 1)

    manifest = build_manifest()
    if args.output:
        global MANIFEST_PATH  # noqa: PLW0603
        MANIFEST_PATH = Path(args.output)
    write_manifest(manifest)
    print(
        f"Fixture manifest written to {MANIFEST_PATH}\n"
        f"  files: {manifest['file_count']}\n"
        f"  hash:  {manifest['manifest_hash']}"
    )


if __name__ == "__main__":
    main()
