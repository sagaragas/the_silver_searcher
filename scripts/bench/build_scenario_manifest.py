#!/usr/bin/env python3
"""Build deterministic benchmark scenario manifest with command matrix.

Defines a canonical set of benchmark scenarios, each with equivalent CLI
commands for all comparators (ag, rust-ag, rg, ugrep).  Emits:
  - manifests/scenarios.json   – scenario + command matrix
  - manifests/corpus.json      – corpus file inventory with hashes
  - manifests/queries.json     – query / pattern inventory with hashes

Reproducibility strategy:
    Only git-tracked files are included in the corpus manifest.  Build-
    generated artifacts (object files, autoconf outputs, dependency caches,
    etc.) are excluded via a two-layer filter:
      1. ``git ls-files`` restricts the file set to version-controlled
         content (the authoritative "clean checkout" view).
      2. An explicit EXCLUDE set catches tracked-but-generated files and
         transient outputs.
    Broken symlinks are silently skipped.

Usage:
    python3 scripts/bench/build_scenario_manifest.py          # generate
    python3 scripts/bench/build_scenario_manifest.py --verify  # verify existing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFESTS_DIR = REPO_ROOT / "manifests"
SCENARIOS_PATH = MANIFESTS_DIR / "scenarios.json"
CORPUS_PATH = MANIFESTS_DIR / "corpus.json"
QUERIES_PATH = MANIFESTS_DIR / "queries.json"

# Comparator identifiers (order matters for matrix columns).
COMPARATORS = ["ag", "rust-ag", "rg", "ugrep"]

# Corpus directories relative to REPO_ROOT.
# The existing tests directory doubles as the initial corpus.
CORPUS_DIRS = [
    "tests",
    "src",
]

# ---------------------------------------------------------------------------
# Queries (search patterns used across scenarios)
# ---------------------------------------------------------------------------

QUERIES: list[dict[str, Any]] = [
    {
        "id": "q-literal-simple",
        "type": "literal",
        "pattern": "foo",
        "description": "Simple literal match",
    },
    {
        "id": "q-literal-word",
        "type": "literal",
        "pattern": "search",
        "description": "Literal word commonly found in source",
    },
    {
        "id": "q-regex-simple",
        "type": "regex",
        "pattern": "err(or)?",
        "description": "Simple alternation regex",
    },
    {
        "id": "q-regex-class",
        "type": "regex",
        "pattern": "[A-Z][a-z]+_[a-z]+",
        "description": "Character-class word pattern",
    },
    {
        "id": "q-regex-multiline",
        "type": "regex",
        "pattern": "if.*\\n.*return",
        "description": "Multiline pattern spanning two lines",
    },
    {
        "id": "q-literal-nocase",
        "type": "literal",
        "pattern": "TODO",
        "description": "Case-insensitive literal match",
    },
    {
        "id": "q-literal-rare",
        "type": "literal",
        "pattern": "pthread_setaffinity_np",
        "description": "Rare literal found in limited files",
    },
    {
        "id": "q-regex-complex",
        "type": "regex",
        "pattern": "\\b[A-Z]{2,}_[A-Z]{2,}\\b",
        "description": "All-caps underscore identifiers",
    },
    {
        "id": "q-nomatch",
        "type": "literal",
        "pattern": "ZZZZNOTFOUNDZZZ",
        "description": "Pattern with zero matches (measures traversal overhead)",
    },
]

# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

# Each scenario defines a logical search intent.  The `commands` dict maps
# each comparator to its concrete CLI invocation.  Placeholders:
#   {corpus} – replaced with the corpus path at run time
#   {pattern} – replaced with the query pattern


def _scenario(
    sid: str,
    description: str,
    query_id: str,
    flags: dict[str, str] | None = None,
    corpus: str = ".",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a single scenario entry with comparator command matrix."""
    if flags is None:
        flags = {}

    # Default flag sets per comparator to normalise output for benchmarking.
    # ag: --nocolor --workers=1 --parallel --noaffinity
    # rust-ag: same as ag (placeholder; will use same flags)
    # rg: --no-heading --color=never
    # ugrep: --color=never

    base_flags = {
        "ag": "--nocolor --workers=1 --parallel --noaffinity",
        "rust-ag": "--nocolor --workers=1 --parallel --noaffinity",
        "rg": "--no-heading --color=never",
        "ugrep": "--color=never",
    }

    commands: dict[str, str] = {}
    for comp in COMPARATORS:
        bf = base_flags[comp]
        ef = flags.get(comp, flags.get("all", ""))
        binary = comp if comp != "rust-ag" else "rust-ag"
        commands[comp] = f"{binary} {bf} {ef} {{pattern}} {{corpus}}".strip()
        # Collapse multiple spaces.
        commands[comp] = " ".join(commands[comp].split())

    entry: dict[str, Any] = {
        "id": sid,
        "description": description,
        "query_id": query_id,
        "corpus": corpus,
        "commands": commands,
    }
    if extra:
        entry.update(extra)
    return entry


SCENARIOS: list[dict[str, Any]] = [
    # --- Literal search scenarios ---
    _scenario(
        "literal-simple",
        "Simple literal search across repo",
        "q-literal-simple",
    ),
    _scenario(
        "literal-word",
        "Common word literal search",
        "q-literal-word",
    ),
    _scenario(
        "literal-rare",
        "Rare literal (few matches, measures traversal)",
        "q-literal-rare",
    ),
    _scenario(
        "literal-nomatch",
        "Literal with zero matches (pure traversal overhead)",
        "q-nomatch",
    ),
    # --- Regex search scenarios ---
    _scenario(
        "regex-simple",
        "Simple alternation regex search",
        "q-regex-simple",
    ),
    _scenario(
        "regex-class",
        "Character-class identifier pattern",
        "q-regex-class",
    ),
    _scenario(
        "regex-complex",
        "All-caps underscore identifiers",
        "q-regex-complex",
    ),
    # --- Case-insensitive scenarios ---
    _scenario(
        "literal-nocase",
        "Case-insensitive literal search",
        "q-literal-nocase",
        flags={
            "ag": "-i",
            "rust-ag": "-i",
            "rg": "-i",
            "ugrep": "-i",
        },
    ),
    # --- Context scenarios ---
    _scenario(
        "context-before-after",
        "Search with context lines (-B2 -A2)",
        "q-literal-simple",
        flags={
            "ag": "-B2 -A2",
            "rust-ag": "-B2 -A2",
            "rg": "-B2 -A2",
            "ugrep": "-B2 -A2",
        },
    ),
    # --- Count scenarios ---
    _scenario(
        "count-matches",
        "Count matching lines (--count)",
        "q-literal-word",
        flags={
            "ag": "--count",
            "rust-ag": "--count",
            "rg": "--count",
            "ugrep": "--count",
        },
    ),
    # --- Filename-only scenarios ---
    _scenario(
        "files-with-matches",
        "List files with matches (-l)",
        "q-literal-word",
        flags={"all": "-l"},
    ),
    # --- Source-only corpus ---
    _scenario(
        "literal-src-only",
        "Literal search restricted to src/ directory",
        "q-literal-word",
        corpus="src",
    ),
]

# ---------------------------------------------------------------------------
# Exclude rules – explicit patterns for build-generated / volatile files.
#
# These mirror the rules in build_fixture_manifest.py so both manifests
# use the same reproducibility strategy.
# ---------------------------------------------------------------------------

# Directories to exclude (matched against every path component).
EXCLUDE_DIRS: set[str] = {
    ".deps",
    "__pycache__",
    ".pytest_cache",
    ".git",
}

# File extensions to exclude.
EXCLUDE_EXTENSIONS: set[str] = {
    ".o",
    ".pyc",
    ".pyo",
    ".err",
    ".trs",
    ".log",
    ".dSYM",
    ".Po",
}

# Exact filenames to exclude (matched against the basename).
EXCLUDE_FILENAMES: set[str] = {
    ".dirstamp",
    ".DS_Store",
    "stamp-h1",
    "config.h",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_string(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _content_hash(obj: Any) -> str:
    """Deterministic hash of a JSON-serialisable object."""
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return _sha256_string(blob)


def _should_skip(rel: str) -> bool:
    """Return True if the relative path should be excluded from the manifest."""
    parts = rel.replace("\\", "/").split("/")
    basename = parts[-1]

    # Directory-component match.
    if any(p in EXCLUDE_DIRS for p in parts[:-1]):
        return True

    # Extension match.
    _, ext = os.path.splitext(basename)
    if ext in EXCLUDE_EXTENSIONS:
        return True

    # Exact filename match.
    if basename in EXCLUDE_FILENAMES:
        return True

    return False


def _git_tracked_files(directories: list[str]) -> set[str]:
    """Return the set of git-tracked relative paths under *directories*.

    Uses ``git ls-files`` so that build-generated files absent from version
    control are automatically excluded.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--"] + directories,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return set()
        return {line for line in result.stdout.splitlines() if line}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return set()


def _collect_corpus(corpus_dirs: list[str]) -> list[dict[str, Any]]:
    """Walk corpus directories and collect file entries with hashes.

    Only git-tracked files that pass the EXCLUDE rules are included.
    Broken symlinks and unreadable files are silently skipped.
    """
    tracked = _git_tracked_files(corpus_dirs)
    entries: list[dict[str, Any]] = []
    for cdir in corpus_dirs:
        base = REPO_ROOT / cdir
        if not base.is_dir():
            continue
        for root_str, dirs, files in os.walk(base, followlinks=False):
            root = Path(root_str)
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
            for fname in sorted(files):
                fpath = root / fname
                rel = str(fpath.relative_to(REPO_ROOT))
                rel_posix = rel.replace("\\", "/")
                if _should_skip(rel_posix):
                    continue
                # Only include git-tracked files.
                if tracked and rel_posix not in tracked:
                    continue
                # Skip broken symlinks.
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
                    continue
    entries.sort(key=lambda e: e["path"])
    return entries


# ---------------------------------------------------------------------------
# Build manifests
# ---------------------------------------------------------------------------


def build_corpus_manifest() -> dict[str, Any]:
    entries = _collect_corpus(CORPUS_DIRS)
    h = hashlib.sha256()
    for e in entries:
        h.update(f"{e['path']}\0{e['size']}\0{e['sha256']}\n".encode())
    return {
        "schema_version": 1,
        "description": "Corpus manifest for benchmark scenarios",
        "corpus_dirs": CORPUS_DIRS,
        "manifest_hash": h.hexdigest(),
        "file_count": len(entries),
        "files": entries,
    }


def build_queries_manifest() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "description": "Query / pattern manifest for benchmark scenarios",
        "manifest_hash": _content_hash(QUERIES),
        "query_count": len(QUERIES),
        "queries": QUERIES,
    }


def build_scenarios_manifest(
    corpus_hash: str, query_hash: str
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "description": "Benchmark scenario-command matrix for all comparators",
        "comparators": COMPARATORS,
        "corpus_manifest_hash": corpus_hash,
        "query_manifest_hash": query_hash,
        "manifest_hash": _content_hash(
            {
                "comparators": COMPARATORS,
                "corpus_hash": corpus_hash,
                "query_hash": query_hash,
                "scenarios": SCENARIOS,
            }
        ),
        "scenario_count": len(SCENARIOS),
        "scenarios": SCENARIOS,
    }


# ---------------------------------------------------------------------------
# Write / Verify
# ---------------------------------------------------------------------------


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=False, ensure_ascii=False)
        f.write("\n")


def write_all() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    corpus = build_corpus_manifest()
    queries = build_queries_manifest()
    scenarios = build_scenarios_manifest(
        corpus["manifest_hash"], queries["manifest_hash"]
    )
    _write_json(CORPUS_PATH, corpus)
    _write_json(QUERIES_PATH, queries)
    _write_json(SCENARIOS_PATH, scenarios)
    return corpus, queries, scenarios


def verify_all() -> bool:
    """Regenerate all manifests in memory and compare against on-disk."""
    ok = True
    corpus = build_corpus_manifest()
    queries = build_queries_manifest()
    scenarios = build_scenarios_manifest(
        corpus["manifest_hash"], queries["manifest_hash"]
    )

    checks = [
        ("corpus", CORPUS_PATH, corpus),
        ("queries", QUERIES_PATH, queries),
        ("scenarios", SCENARIOS_PATH, scenarios),
    ]

    for label, path, fresh in checks:
        if not path.exists():
            print(f"FAIL: {label} manifest not found at {path}", file=sys.stderr)
            ok = False
            continue
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        if existing.get("manifest_hash") != fresh["manifest_hash"]:
            print(
                f"FAIL: {label} manifest hash mismatch\n"
                f"  on-disk: {existing.get('manifest_hash')}\n"
                f"  fresh:   {fresh['manifest_hash']}",
                file=sys.stderr,
            )
            ok = False
        else:
            count_key = (
                "file_count" if "file_count" in fresh else
                "query_count" if "query_count" in fresh else
                "scenario_count"
            )
            print(
                f"OK: {label} manifest verified "
                f"({fresh[count_key]} entries, hash={fresh['manifest_hash'][:16]}…)"
            )

    return ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build or verify benchmark scenario / corpus / query manifests."
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify existing manifests match freshly generated ones.",
    )
    args = parser.parse_args()

    if args.verify:
        ok = verify_all()
        sys.exit(0 if ok else 1)

    corpus, queries, scenarios = write_all()
    print(
        f"Corpus manifest:   {CORPUS_PATH}\n"
        f"  files: {corpus['file_count']}, hash: {corpus['manifest_hash']}\n"
        f"Queries manifest:  {QUERIES_PATH}\n"
        f"  queries: {queries['query_count']}, hash: {queries['manifest_hash']}\n"
        f"Scenarios manifest: {SCENARIOS_PATH}\n"
        f"  scenarios: {scenarios['scenario_count']}, "
        f"comparators: {scenarios['comparators']}\n"
        f"  hash: {scenarios['manifest_hash']}"
    )


if __name__ == "__main__":
    main()
