#!/usr/bin/env python3
"""Create deterministic edge-case fixture trees for parity testing.

Each fixture category lives in its own subdirectory under tests/edge-cases/.
This script is idempotent: running it multiple times produces the same result.

Categories:
  - ignore-source/   : ignore-source matrix (.gitignore, .agignore, .ignore, -U)
  - hidden-files/    : hidden file/directory behavior (default vs --hidden)
  - binary-files/    : binary detection and --search-binary
  - symlink-traversal/ : symlinks and -f / --one-device (platform-conditional)
  - large-file/      : large-file search behavior
  - zero-length-regex/ : zero-length regex safety and semantics
  - max-count/       : --max-count per-file truncation semantics

Usage:
    python3 tests/edge-cases/setup_fixtures.py
    python3 tests/edge-cases/setup_fixtures.py --verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
FIXTURES_BASE = SCRIPT_DIR

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _write(path: Path, content: str) -> None:
    _ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def _write_bytes(path: Path, data: bytes) -> None:
    _ensure_dir(path.parent)
    path.write_bytes(data)


def _git_init(directory: Path) -> None:
    """Initialize a git repo in directory if not already present."""
    git_dir = directory / ".git"
    if git_dir.exists():
        return
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=directory,
        check=True,
        capture_output=True,
    )
    # Ensure info dir exists for git exclude
    info_dir = git_dir / "info"
    info_dir.mkdir(parents=True, exist_ok=True)


def _rmtree_safe(path: Path) -> None:
    """Remove a directory tree, handling read-only files on all platforms."""
    if not path.exists():
        return

    def _onerror(func, fpath, exc_info):
        os.chmod(fpath, stat.S_IWUSR | stat.S_IRUSR)
        func(fpath)

    shutil.rmtree(path, onerror=_onerror)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def build_ignore_source(base: Path) -> None:
    """Build ignore-source matrix fixtures.

    Tests the ignore-source hierarchy in ag:
      - .gitignore (project-level VCS ignore)
      - .git/info/exclude (git local exclude)
      - .ignore (ag/rg project-level ignore, non-VCS)

    With -U flag, VCS-derived ignores (.gitignore, .git/info/exclude) are
    skipped, but .ignore rules remain active.

    Directory structure:
      ignore-source/
        .gitignore          -> ignores "git-ignored.txt"
        .ignore             -> ignores "dot-ignored.txt"
        visible.txt         -> always visible
        git-ignored.txt     -> ignored by .gitignore (VCS)
        git-excluded.txt    -> ignored by .git/info/exclude (VCS)
        dot-ignored.txt     -> ignored by .ignore (non-VCS)
        subdir/
          .gitignore        -> ignores "sub-git-ignored.txt"
          sub-visible.txt
          sub-git-ignored.txt
    """
    _rmtree_safe(base)
    _ensure_dir(base)
    _git_init(base)

    _write(base / ".gitignore", "git-ignored.txt\n")
    _write(base / ".ignore", "dot-ignored.txt\n")

    # Add git local exclude for git-excluded.txt
    git_info = base / ".git" / "info"
    git_info.mkdir(parents=True, exist_ok=True)
    _write(git_info / "exclude", "git-excluded.txt\n")

    _write(base / "visible.txt", "NEEDLE visible content\n")
    _write(base / "git-ignored.txt", "NEEDLE git-ignored content\n")
    _write(base / "git-excluded.txt", "NEEDLE git-excluded content\n")
    _write(base / "dot-ignored.txt", "NEEDLE dot-ignored content\n")

    _write(base / "subdir" / ".gitignore", "sub-git-ignored.txt\n")
    _write(base / "subdir" / "sub-visible.txt", "NEEDLE sub-visible content\n")
    _write(base / "subdir" / "sub-git-ignored.txt", "NEEDLE sub-git-ignored content\n")


def build_hidden_files(base: Path) -> None:
    """Build hidden-file fixtures.

    Directory structure:
      hidden-files/
        visible.txt
        .hidden-file.txt
        .hidden-dir/
          nested.txt
        normal-dir/
          another.txt
    """
    _rmtree_safe(base)
    _ensure_dir(base)
    _git_init(base)

    _write(base / "visible.txt", "NEEDLE visible content\n")
    _write(base / ".hidden-file.txt", "NEEDLE hidden-file content\n")
    _write(base / ".hidden-dir" / "nested.txt", "NEEDLE hidden-dir-nested content\n")
    _write(base / "normal-dir" / "another.txt", "NEEDLE normal-dir content\n")

    # Empty .gitignore to ensure git repo doesn't interfere
    _write(base / ".gitignore", "")


def build_binary_files(base: Path) -> None:
    """Build binary-file fixtures.

    Directory structure:
      binary-files/
        text-file.txt       -> plain text with matches
        binary-file.bin     -> binary content with embedded match pattern
        mixed-binary.dat    -> starts text, has NUL bytes
    """
    _rmtree_safe(base)
    _ensure_dir(base)
    _git_init(base)

    _write(base / "text-file.txt", "NEEDLE in text file\nAnother line\n")

    # Binary file: PDF-like header with embedded pattern
    binary_content = b"%PDF-1.4 binary header\x00\x01\x02\x03NEEDLE in binary\x00\xff\xfe"
    _write_bytes(base / "binary-file.bin", binary_content)

    # Mixed: starts as text, has NUL byte in middle
    mixed_content = b"NEEDLE before null\x00NEEDLE after null\n"
    _write_bytes(base / "mixed-binary.dat", mixed_content)

    _write(base / ".gitignore", "")


def build_symlink_traversal(base: Path) -> None:
    """Build symlink/device traversal fixtures.

    Directory structure:
      symlink-traversal/
        real-dir/
          real-file.txt
        link-to-dir  -> real-dir (symlink)
        link-to-file -> real-dir/real-file.txt (symlink)
        broken-link  -> nonexistent (broken symlink)

    NOTE: Platform-conditional. Symlinks may not work on all platforms.
    """
    _rmtree_safe(base)
    _ensure_dir(base)
    _git_init(base)

    _write(base / "real-dir" / "real-file.txt", "NEEDLE in real dir\n")

    # Create symlinks (may fail on Windows without developer mode)
    try:
        link_dir = base / "link-to-dir"
        if link_dir.exists() or link_dir.is_symlink():
            link_dir.unlink()
        link_dir.symlink_to("real-dir")

        link_file = base / "link-to-file"
        if link_file.exists() or link_file.is_symlink():
            link_file.unlink()
        link_file.symlink_to("real-dir/real-file.txt")

        broken_link = base / "broken-link"
        if broken_link.exists() or broken_link.is_symlink():
            broken_link.unlink()
        broken_link.symlink_to("nonexistent-target")
    except OSError as e:
        print(f"WARNING: Could not create symlinks: {e}", file=sys.stderr)

    _write(base / ".gitignore", "")


def build_large_file(base: Path) -> None:
    """Build large-file fixtures.

    Directory structure:
      large-file/
        normal.txt         -> small file with matches
        large.txt          -> ~2MB file with matches scattered through it
    """
    _rmtree_safe(base)
    _ensure_dir(base)
    _git_init(base)

    _write(base / "normal.txt", "NEEDLE in normal file\n")

    # Build a ~2MB file with matches at specific positions
    lines = []
    for i in range(40000):
        if i % 10000 == 0:
            lines.append(f"NEEDLE match at line {i}")
        else:
            lines.append(f"filler line number {i} with some padding content")
    large_content = "\n".join(lines) + "\n"
    _write(base / "large.txt", large_content)

    _write(base / ".gitignore", "")


def build_zero_length_regex(base: Path) -> None:
    """Build zero-length regex fixtures.

    Directory structure:
      zero-length-regex/
        empty.txt          -> empty file (0 bytes)
        single-line.txt    -> one line of text
        multi-line.txt     -> multiple lines
    """
    _rmtree_safe(base)
    _ensure_dir(base)
    _git_init(base)

    _write(base / "empty.txt", "")
    _write(base / "single-line.txt", "hello world\n")
    _write(base / "multi-line.txt", "line one\nline two\nline three\n")

    _write(base / ".gitignore", "")


def build_max_count(base: Path) -> None:
    """Build max-count fixtures.

    Directory structure:
      max-count/
        few-matches.txt    -> 3 matching lines
        many-matches.txt   -> 20 matching lines
        mixed.txt          -> alternating match/no-match lines
    """
    _rmtree_safe(base)
    _ensure_dir(base)
    _git_init(base)

    few_lines = "NEEDLE first\nno match here\nNEEDLE second\nstill no match\nNEEDLE third\n"
    _write(base / "few-matches.txt", few_lines)

    many_lines = ""
    for i in range(20):
        many_lines += f"NEEDLE line {i}\n"
    _write(base / "many-matches.txt", many_lines)

    mixed_lines = ""
    for i in range(10):
        mixed_lines += f"NEEDLE match {i}\n"
        mixed_lines += f"filler line {i}\n"
    _write(base / "mixed.txt", mixed_lines)

    _write(base / ".gitignore", "")


# ---------------------------------------------------------------------------
# Platform metadata
# ---------------------------------------------------------------------------


def build_platform_metadata() -> dict:
    """Generate platform applicability metadata for conditional fixtures."""
    system = platform.system()

    symlinks_supported = True
    if system == "Windows":
        # Symlinks require developer mode on Windows
        symlinks_supported = False

    # /dev/shm test for one-device (Linux-specific)
    dev_shm_available = os.path.exists("/dev/shm")

    return {
        "schema_version": 1,
        "platform": {
            "system": system,
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "fixture_applicability": {
            "ignore-source": {
                "supported": True,
                "skip_reason": None,
                "notes": "Requires git to be installed for .gitignore handling",
            },
            "hidden-files": {
                "supported": True,
                "skip_reason": None,
                "notes": "Hidden files (dot-prefix) work on all Unix-like systems",
            },
            "binary-files": {
                "supported": True,
                "skip_reason": None,
                "notes": "Binary detection is platform-independent",
            },
            "symlink-traversal": {
                "supported": symlinks_supported,
                "skip_reason": (
                    "Windows requires developer mode for symlinks"
                    if not symlinks_supported
                    else None
                ),
                "notes": (
                    "Symlink creation and traversal tests. "
                    "On Windows, requires developer mode or elevated privileges."
                ),
            },
            "one-device": {
                "supported": dev_shm_available,
                "skip_reason": (
                    "/dev/shm not available on this platform"
                    if not dev_shm_available
                    else None
                ),
                "notes": (
                    "One-device test requires /dev/shm (Linux tmpfs) to have a "
                    "cross-device mount point. macOS uses a different tmpfs layout "
                    "and may not have a suitable cross-device boundary. "
                    "This fixture is Linux-specific."
                ),
            },
            "large-file": {
                "supported": True,
                "skip_reason": None,
                "notes": "Large-file fixture is ~2MB; should work on all platforms",
            },
            "zero-length-regex": {
                "supported": True,
                "skip_reason": None,
                "notes": "Zero-length regex behavior is platform-independent",
            },
            "max-count": {
                "supported": True,
                "skip_reason": None,
                "notes": "Max-count behavior is platform-independent",
            },
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


BUILDERS = {
    "ignore-source": build_ignore_source,
    "hidden-files": build_hidden_files,
    "binary-files": build_binary_files,
    "symlink-traversal": build_symlink_traversal,
    "large-file": build_large_file,
    "zero-length-regex": build_zero_length_regex,
    "max-count": build_max_count,
}


def setup_all() -> None:
    """Build all fixture categories."""
    for name, builder in BUILDERS.items():
        target = FIXTURES_BASE / name
        print(f"  Building: {name}/ ...")
        builder(target)

    # Write platform metadata
    meta = build_platform_metadata()
    meta_path = FIXTURES_BASE / "platform_metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=False, ensure_ascii=False)
        f.write("\n")
    print(f"  Platform metadata: {meta_path}")


def verify_all() -> bool:
    """Verify all fixture categories exist and are structurally sound."""
    ok = True

    for name in BUILDERS:
        target = FIXTURES_BASE / name
        if not target.is_dir():
            print(f"FAIL: Missing fixture directory: {name}/", file=sys.stderr)
            ok = False
            continue
        # Check that at least one .txt file exists
        txt_files = list(target.glob("**/*.txt"))
        non_git_files = [f for f in txt_files if ".git" not in str(f)]
        if not non_git_files:
            print(f"FAIL: No .txt fixture files in {name}/", file=sys.stderr)
            ok = False
        else:
            print(f"  OK: {name}/ ({len(non_git_files)} fixture files)")

    # Check platform metadata
    meta_path = FIXTURES_BASE / "platform_metadata.json"
    if not meta_path.is_file():
        print("FAIL: Missing platform_metadata.json", file=sys.stderr)
        ok = False
    else:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        fa = meta.get("fixture_applicability", {})
        print(f"  OK: platform_metadata.json ({len(fa)} categories)")

    # Check symlinks specifically
    symlink_dir = FIXTURES_BASE / "symlink-traversal"
    if symlink_dir.is_dir():
        link = symlink_dir / "link-to-dir"
        if link.is_symlink():
            print("  OK: symlink-traversal/link-to-dir is a symlink")
        else:
            print("  WARN: symlink-traversal/link-to-dir is NOT a symlink")

    return ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Setup deterministic edge-case fixtures for parity testing."
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify existing fixtures instead of creating them.",
    )
    args = parser.parse_args()

    if args.verify:
        print("Verifying edge-case fixtures:")
        ok = verify_all()
        sys.exit(0 if ok else 1)

    print("Setting up edge-case fixtures:")
    setup_all()
    print("\nDone. Run with --verify to check.")


if __name__ == "__main__":
    main()
