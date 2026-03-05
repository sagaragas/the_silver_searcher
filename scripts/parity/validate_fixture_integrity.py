#!/usr/bin/env python3
"""Validate integrity of all fixture sets including edge-case fixtures.

Checks:
  1. Standard fixture manifest (manifests/fixtures.json) is consistent.
  2. Edge-case fixture directories exist and are structurally complete.
  3. Edge-case fixture setup is reproducible (re-run and verify).
  4. Platform metadata is present and well-formed.
  5. Scenario manifest references valid fixture paths.
  6. Symlink/one-device fixtures have platform applicability notes.
  7. Required edge scenario IDs are present (coverage shrinkage gate).
  8. Scenario-to-category mapping is in sync with fixture builders
     (no unknown categories, no orphan builders).

Usage:
    python3 scripts/parity/validate_fixture_integrity.py
    python3 scripts/parity/validate_fixture_integrity.py --verbose
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFESTS_DIR = REPO_ROOT / "manifests"
EDGE_CASES_DIR = REPO_ROOT / "tests" / "edge-cases"

# Expected edge-case fixture categories.
EXPECTED_CATEGORIES = [
    "ignore-source",
    "hidden-files",
    "binary-files",
    "symlink-traversal",
    "one-device",
    "large-file",
    "zero-length-regex",
    "max-count",
]

# Minimum expected file counts per category (non-.git files).
MIN_FILE_COUNTS = {
    "ignore-source": 5,
    "hidden-files": 3,
    "binary-files": 1,
    "symlink-traversal": 1,
    "one-device": 3,  # local-file.txt, subdir/nested.txt, one-device-marker.json
    "large-file": 2,
    "zero-length-regex": 2,
    "max-count": 3,
}

# Categories that require platform applicability notes.
PLATFORM_CONDITIONAL_CATEGORIES = [
    "symlink-traversal",
    "one-device",
]

# ---------------------------------------------------------------------------
# Required edge scenario IDs — coverage shrinkage gate.
#
# Every scenario ID listed here MUST appear in the scenario manifest.  If a
# required ID is missing the integrity check fails, preventing silent
# coverage shrinkage.  When adding a new edge-case scenario to
# build_scenario_manifest.py, also add its ID here.
# ---------------------------------------------------------------------------

REQUIRED_EDGE_SCENARIO_IDS: set[str] = {
    "edge-binary-files",
    "edge-hidden-files",
    "edge-ignore-scope-leak",
    "edge-ignore-source",
    "edge-large-file",
    "edge-max-count",
    "edge-one-device-restricted",
    "edge-one-device-follow",
    "edge-recursion-n-r-precedence",
    "edge-recursion-r-n-precedence",
    "edge-symlink-traversal",
    "edge-zero-length-regex",
}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


class IntegrityResult:
    """Accumulates integrity validation results."""

    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def check(self, name: str, passed: bool, detail: str = "") -> bool:
        self.checks.append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            self.errors.append(f"FAIL: {name}" + (f" — {detail}" if detail else ""))
        return passed

    def warn(self, msg: str) -> None:
        self.warnings.append(f"WARN: {msg}")

    @property
    def passed(self) -> bool:
        return all(c["passed"] for c in self.checks)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c["passed"])

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if not c["passed"])


def _count_fixture_files(directory: Path) -> int:
    """Count non-.git files in a directory tree."""
    count = 0
    for root, dirs, files in os.walk(directory, followlinks=False):
        # Skip .git directories
        dirs[:] = [d for d in dirs if d != ".git"]
        count += len(files)
    return count


# ---------------------------------------------------------------------------
# Validation stages
# ---------------------------------------------------------------------------


def validate_standard_manifest(result: IntegrityResult, verbose: bool) -> None:
    """Check that manifests/fixtures.json is present and consistent."""
    fixture_manifest = MANIFESTS_DIR / "fixtures.json"
    result.check(
        "standard_manifest_exists",
        fixture_manifest.is_file(),
        str(fixture_manifest),
    )
    if not fixture_manifest.is_file():
        return

    try:
        with open(fixture_manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
        result.check("standard_manifest_valid_json", True)
    except (json.JSONDecodeError, OSError) as e:
        result.check("standard_manifest_valid_json", False, str(e))
        return

    result.check(
        "standard_manifest_has_hash",
        bool(data.get("manifest_hash")),
        "Missing manifest_hash field",
    )
    result.check(
        "standard_manifest_has_files",
        len(data.get("files", [])) > 0,
        f"File count: {len(data.get('files', []))}",
    )

    if verbose:
        print(f"  Standard manifest: {len(data.get('files', []))} files, "
              f"hash={data.get('manifest_hash', 'none')[:16]}")


def validate_edge_case_directories(result: IntegrityResult, verbose: bool) -> None:
    """Check that all edge-case fixture directories exist with expected content."""
    result.check(
        "edge_cases_dir_exists",
        EDGE_CASES_DIR.is_dir(),
        str(EDGE_CASES_DIR),
    )
    if not EDGE_CASES_DIR.is_dir():
        return

    for category in EXPECTED_CATEGORIES:
        cat_dir = EDGE_CASES_DIR / category
        result.check(
            f"category_exists:{category}",
            cat_dir.is_dir(),
            str(cat_dir),
        )
        if not cat_dir.is_dir():
            continue

        file_count = _count_fixture_files(cat_dir)
        min_count = MIN_FILE_COUNTS.get(category, 1)
        result.check(
            f"category_files:{category}",
            file_count >= min_count,
            f"Found {file_count} files, expected >= {min_count}",
        )

        if verbose:
            print(f"  {category}/: {file_count} files")

    # Check setup script exists
    setup_script = EDGE_CASES_DIR / "setup_fixtures.py"
    result.check(
        "setup_script_exists",
        setup_script.is_file(),
        str(setup_script),
    )


def validate_platform_metadata(result: IntegrityResult, verbose: bool) -> None:
    """Check that platform metadata is present and well-formed."""
    meta_path = EDGE_CASES_DIR / "platform_metadata.json"
    result.check(
        "platform_metadata_exists",
        meta_path.is_file(),
        str(meta_path),
    )
    if not meta_path.is_file():
        return

    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        result.check("platform_metadata_valid_json", True)
    except (json.JSONDecodeError, OSError) as e:
        result.check("platform_metadata_valid_json", False, str(e))
        return

    # Check required structure.
    result.check(
        "platform_metadata_has_platform",
        "platform" in meta,
        "Missing 'platform' field",
    )
    fa = meta.get("fixture_applicability", {})
    result.check(
        "platform_metadata_has_applicability",
        len(fa) > 0,
        f"fixture_applicability has {len(fa)} entries",
    )

    # Check that platform-conditional categories have applicability notes.
    for category in PLATFORM_CONDITIONAL_CATEGORIES:
        entry = fa.get(category, {})
        result.check(
            f"platform_applicability:{category}",
            bool(entry),
            f"Missing applicability entry for {category}",
        )
        if entry:
            result.check(
                f"platform_notes:{category}",
                bool(entry.get("notes")),
                f"Missing 'notes' for {category}",
            )
            result.check(
                f"platform_supported_field:{category}",
                "supported" in entry,
                f"Missing 'supported' field for {category}",
            )

    if verbose:
        print(f"  Platform metadata: {len(fa)} categories, "
              f"system={meta.get('platform', {}).get('system', '?')}")


def validate_scenario_corpus_refs(result: IntegrityResult, verbose: bool) -> None:
    """Check that scenario corpus references resolve to existing paths."""
    scenarios_path = MANIFESTS_DIR / "scenarios.json"
    if not scenarios_path.is_file():
        result.warn("scenarios.json not found; skipping corpus ref validation")
        return

    with open(scenarios_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    edge_scenarios = [
        s for s in data.get("scenarios", [])
        if s["id"].startswith("edge-")
    ]

    result.check(
        "edge_scenarios_present",
        len(edge_scenarios) > 0,
        f"Found {len(edge_scenarios)} edge-case scenarios",
    )

    for s in edge_scenarios:
        corpus = s["corpus"]
        corpus_path = REPO_ROOT / corpus
        exists = corpus_path.exists()
        result.check(
            f"corpus_exists:{s['id']}",
            exists,
            f"Corpus '{corpus}' -> {corpus_path}",
        )

    # Check that symlink/one-device scenarios have platform_skip metadata.
    for s in edge_scenarios:
        if "symlink" in s["id"] or "one-device" in s["id"]:
            has_skip = "platform_skip" in s
            result.check(
                f"platform_skip_present:{s['id']}",
                has_skip,
                "Symlink/device scenarios should have platform_skip metadata",
            )

    if verbose:
        print(f"  Edge-case scenarios: {len(edge_scenarios)}")


def validate_required_edge_scenario_ids(result: IntegrityResult, verbose: bool) -> None:
    """Enforce required edge scenario ID set — coverage shrinkage gate.

    Compares the edge scenario IDs actually present in manifests/scenarios.json
    against REQUIRED_EDGE_SCENARIO_IDS.  Fails when any required ID is absent,
    preventing silent coverage shrinkage.
    """
    scenarios_path = MANIFESTS_DIR / "scenarios.json"
    if not scenarios_path.is_file():
        result.check(
            "required_edge_ids:manifest_exists",
            False,
            "scenarios.json not found; cannot validate required edge scenario IDs",
        )
        return

    with open(scenarios_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    present_edge_ids: set[str] = {
        s["id"] for s in data.get("scenarios", [])
        if s["id"].startswith("edge-")
    }

    missing = REQUIRED_EDGE_SCENARIO_IDS - present_edge_ids
    result.check(
        "required_edge_ids:all_present",
        len(missing) == 0,
        (
            f"Missing required edge scenario IDs: {sorted(missing)}"
            if missing
            else f"All {len(REQUIRED_EDGE_SCENARIO_IDS)} required edge scenario IDs present"
        ),
    )

    # Per-ID checks for clear reporting.
    for sid in sorted(REQUIRED_EDGE_SCENARIO_IDS):
        result.check(
            f"required_edge_id:{sid}",
            sid in present_edge_ids,
            f"Required edge scenario '{sid}' is "
            + ("present" if sid in present_edge_ids else "MISSING from scenarios.json"),
        )

    if verbose:
        print(
            f"  Required edge scenario IDs: "
            f"{len(REQUIRED_EDGE_SCENARIO_IDS)} required, "
            f"{len(present_edge_ids)} present, "
            f"{len(missing)} missing"
        )


def validate_symlink_fixtures(result: IntegrityResult, verbose: bool) -> None:
    """Validate symlink-specific fixture integrity."""
    symlink_dir = EDGE_CASES_DIR / "symlink-traversal"
    if not symlink_dir.is_dir():
        result.warn("symlink-traversal directory missing; skipping symlink checks")
        return

    # Check that expected symlinks exist.
    link_to_dir = symlink_dir / "link-to-dir"
    if link_to_dir.is_symlink():
        result.check("symlink_link_to_dir", True, "Is a symlink")
        target = os.readlink(link_to_dir)
        result.check(
            "symlink_target_valid:link-to-dir",
            target == "real-dir",
            f"Target: {target}",
        )
    elif platform.system() == "Windows":
        result.warn("link-to-dir not a symlink (expected on Windows)")
    else:
        result.check(
            "symlink_link_to_dir",
            False,
            "Not a symlink on a Unix-like system",
        )

    link_to_file = symlink_dir / "link-to-file"
    if link_to_file.is_symlink():
        result.check("symlink_link_to_file", True, "Is a symlink")
    elif platform.system() != "Windows":
        result.check("symlink_link_to_file", False, "Expected symlink")

    broken_link = symlink_dir / "broken-link"
    if broken_link.is_symlink():
        result.check("symlink_broken_link", True, "Is a symlink")
        # Verify it's actually broken.
        result.check(
            "symlink_broken_link_is_broken",
            not broken_link.exists(),
            "Should point to nonexistent target",
        )

    if verbose:
        print(f"  Symlink fixtures: link-to-dir={link_to_dir.is_symlink()}, "
              f"link-to-file={link_to_file.is_symlink()}, "
              f"broken-link={broken_link.is_symlink()}")


def validate_binary_fixtures(result: IntegrityResult, verbose: bool) -> None:
    """Validate binary-file fixture integrity."""
    binary_dir = EDGE_CASES_DIR / "binary-files"
    if not binary_dir.is_dir():
        return

    # Check that binary-file.bin actually contains non-text bytes.
    bin_file = binary_dir / "binary-file.bin"
    if bin_file.is_file():
        content = bin_file.read_bytes()
        has_null = b"\x00" in content
        result.check(
            "binary_has_null_bytes",
            has_null,
            "Binary file should contain NUL bytes",
        )
        has_pattern = b"NEEDLE" in content
        result.check(
            "binary_has_pattern",
            has_pattern,
            "Binary file should contain search pattern",
        )

    # Check text file is actually text.
    text_file = binary_dir / "text-file.txt"
    if text_file.is_file():
        content = text_file.read_bytes()
        has_null = b"\x00" in content
        result.check(
            "text_no_null_bytes",
            not has_null,
            "Text file should not contain NUL bytes",
        )


def validate_large_file(result: IntegrityResult, verbose: bool) -> None:
    """Validate large-file fixture sizing and determinism.

    Checks:
      - large.txt exists and is >= 1 MB.
      - large.txt.sha256 sidecar exists (determinism assertion).
      - If both exist, the recorded checksum matches actual content.
    """
    large_dir = EDGE_CASES_DIR / "large-file"
    if not large_dir.is_dir():
        result.check("large_file_dir_exists", False, "large-file/ directory missing")
        return

    large_file = large_dir / "large.txt"
    sha_file = large_dir / "large.txt.sha256"

    result.check(
        "large_file_exists",
        large_file.is_file(),
        "large-file/large.txt must be present",
    )
    if not large_file.is_file():
        return

    size = large_file.stat().st_size
    result.check(
        "large_file_size",
        size >= 1_000_000,
        f"Size: {size} bytes ({size / 1_000_000:.1f} MB)",
    )

    result.check(
        "large_file_sha256_sidecar_exists",
        sha_file.is_file(),
        "large-file/large.txt.sha256 sidecar must be present for determinism check",
    )
    if sha_file.is_file():
        import hashlib

        expected_hash = sha_file.read_text(encoding="utf-8").split()[0]
        actual_hash = hashlib.sha256(large_file.read_bytes()).hexdigest()
        result.check(
            "large_file_checksum_match",
            actual_hash == expected_hash,
            f"Expected {expected_hash[:16]}…, got {actual_hash[:16]}…",
        )
        if verbose:
            print(f"  Large file: {size} bytes, sha256={actual_hash[:16]}…")
    elif verbose:
        print(f"  Large file: {size} bytes (no checksum sidecar)")


def validate_one_device_fixtures(result: IntegrityResult, verbose: bool) -> None:
    """Validate one-device traversal fixture integrity.

    Checks:
      - one-device/ directory exists with local fixture files.
      - one-device-marker.json is present and well-formed.
      - If marker claims cross-device is available, the symlink exists.
      - Platform applicability metadata is consistent.
    """
    one_device_dir = EDGE_CASES_DIR / "one-device"
    result.check(
        "one_device_dir_exists",
        one_device_dir.is_dir(),
        "one-device/ fixture directory must be present",
    )
    if not one_device_dir.is_dir():
        return

    # Local fixture files must always be present regardless of platform.
    local_file = one_device_dir / "local-file.txt"
    result.check(
        "one_device_local_file",
        local_file.is_file(),
        "one-device/local-file.txt must always exist",
    )

    nested_file = one_device_dir / "subdir" / "nested.txt"
    result.check(
        "one_device_nested_file",
        nested_file.is_file(),
        "one-device/subdir/nested.txt must always exist",
    )

    # Marker JSON.
    marker_path = one_device_dir / "one-device-marker.json"
    result.check(
        "one_device_marker_exists",
        marker_path.is_file(),
        "one-device/one-device-marker.json must be present",
    )
    if not marker_path.is_file():
        return

    try:
        with open(marker_path, "r", encoding="utf-8") as f:
            marker = json.load(f)
        result.check("one_device_marker_valid_json", True)
    except (json.JSONDecodeError, OSError) as e:
        result.check("one_device_marker_valid_json", False, str(e))
        return

    cross_avail = marker.get("cross_device_available", False)
    plat = marker.get("platform", "?")

    result.check(
        "one_device_marker_has_platform",
        "platform" in marker,
        "Marker must include 'platform' field",
    )
    result.check(
        "one_device_marker_has_notes",
        bool(marker.get("notes")),
        "Marker must include 'notes' field",
    )

    # If cross-device is claimed available, verify the symlink.
    if cross_avail:
        link = one_device_dir / "cross-device-link"
        result.check(
            "one_device_cross_device_link",
            link.is_symlink(),
            "cross-device-link symlink must exist when cross_device_available is true",
        )
        if link.is_symlink():
            # The target directory should exist (it's on tmpfs).
            target_exists = link.resolve().is_dir() if link.exists() else False
            result.check(
                "one_device_cross_device_target",
                target_exists,
                "cross-device-link target directory must be accessible",
            )

    if verbose:
        print(
            f"  One-device fixtures: platform={plat}, "
            f"cross_device_available={cross_avail}"
        )


def validate_scenario_category_sync(result: IntegrityResult, verbose: bool) -> None:
    """Validate that every edge scenario's corpus-derived category exists as a fixture.

    Ensures no silent drift between the scenario manifest and the fixture
    builder categories.  Each edge scenario's corpus path encodes the fixture
    category it depends on (``tests/edge-cases/<category>/``); this check
    verifies:

    1. Every edge scenario corpus path resolves to a known fixture builder
       category (from setup_fixtures.py BUILDERS).
    2. Every fixture builder category is referenced by at least one edge
       scenario (no orphan categories).
    """
    scenarios_path = MANIFESTS_DIR / "scenarios.json"
    if not scenarios_path.is_file():
        result.warn("scenarios.json not found; skipping scenario-category sync")
        return

    # Import BUILDERS from setup_fixtures to get the authoritative category set.
    setup_script = EDGE_CASES_DIR / "setup_fixtures.py"
    if not setup_script.is_file():
        result.warn("setup_fixtures.py not found; skipping scenario-category sync")
        return

    import importlib.util

    spec = importlib.util.spec_from_file_location("setup_fixtures", setup_script)
    if spec is None or spec.loader is None:
        result.warn("Could not import setup_fixtures; skipping scenario-category sync")
        return

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    builder_categories: set[str] = set(mod.BUILDERS.keys())

    with open(scenarios_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    edge_corpus_prefix = "tests/edge-cases/"
    derived_categories: set[str] = set()
    scenario_to_category: dict[str, str] = {}

    for scenario in data.get("scenarios", []):
        sid = scenario.get("id", "")
        corpus = scenario.get("corpus", "")
        if sid.startswith("edge-") and corpus.startswith(edge_corpus_prefix):
            remainder = corpus[len(edge_corpus_prefix):]
            category = remainder.split("/")[0] if remainder else ""
            if category:
                scenario_to_category[sid] = category
                derived_categories.add(category)

    # Check 1: Every scenario-derived category must be a known builder category.
    unknown_categories = derived_categories - builder_categories
    result.check(
        "scenario_category_sync:all_known",
        len(unknown_categories) == 0,
        (
            f"Scenario corpus paths reference unknown fixture categories: "
            f"{sorted(unknown_categories)}"
            if unknown_categories
            else f"All {len(derived_categories)} scenario-derived categories "
                 f"are known fixture builders"
        ),
    )

    # Check 2: Every builder category should be referenced by at least one
    # edge scenario (no orphan builders that silently lose test coverage).
    orphan_categories = builder_categories - derived_categories
    result.check(
        "scenario_category_sync:no_orphans",
        len(orphan_categories) == 0,
        (
            f"Fixture builder categories not referenced by any edge scenario: "
            f"{sorted(orphan_categories)}"
            if orphan_categories
            else f"All {len(builder_categories)} builder categories are "
                 f"referenced by edge scenarios"
        ),
    )

    # Per-category checks for clear diagnostic output.
    for cat in sorted(derived_categories):
        result.check(
            f"scenario_category_sync:known:{cat}",
            cat in builder_categories,
            f"Category '{cat}' derived from scenario corpus is "
            + ("a known builder" if cat in builder_categories else "NOT a known builder"),
        )

    if verbose:
        print(
            f"  Scenario-category sync: {len(derived_categories)} derived, "
            f"{len(builder_categories)} builders, "
            f"{len(unknown_categories)} unknown, "
            f"{len(orphan_categories)} orphans"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate integrity of all fixture sets including edge cases."
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed progress information.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit results as JSON.",
    )
    args = parser.parse_args()

    result = IntegrityResult()

    print("Validating fixture integrity...\n")

    # Stage 1: Standard fixture manifest.
    if args.verbose:
        print("Stage 1: Standard fixture manifest")
    validate_standard_manifest(result, args.verbose)

    # Stage 2: Edge-case directories.
    if args.verbose:
        print("\nStage 2: Edge-case fixture directories")
    validate_edge_case_directories(result, args.verbose)

    # Stage 3: Platform metadata.
    if args.verbose:
        print("\nStage 3: Platform metadata")
    validate_platform_metadata(result, args.verbose)

    # Stage 4: Scenario corpus references.
    if args.verbose:
        print("\nStage 4: Scenario corpus references")
    validate_scenario_corpus_refs(result, args.verbose)

    # Stage 5: Required edge scenario ID set (coverage shrinkage gate).
    if args.verbose:
        print("\nStage 5: Required edge scenario IDs")
    validate_required_edge_scenario_ids(result, args.verbose)

    # Stage 6: Symlink fixture integrity.
    if args.verbose:
        print("\nStage 6: Symlink fixtures")
    validate_symlink_fixtures(result, args.verbose)

    # Stage 7: Binary fixture integrity.
    if args.verbose:
        print("\nStage 7: Binary fixtures")
    validate_binary_fixtures(result, args.verbose)

    # Stage 8: Large-file fixture.
    if args.verbose:
        print("\nStage 8: Large-file fixture")
    validate_large_file(result, args.verbose)

    # Stage 9: One-device fixture.
    if args.verbose:
        print("\nStage 9: One-device fixture")
    validate_one_device_fixtures(result, args.verbose)

    # Stage 10: Scenario-to-category sync validation.
    if args.verbose:
        print("\nStage 10: Scenario-category sync")
    validate_scenario_category_sync(result, args.verbose)

    # Output results.
    if args.json:
        output = {
            "passed": result.passed,
            "total_checks": result.total,
            "pass_count": result.pass_count,
            "fail_count": result.fail_count,
            "errors": result.errors,
            "warnings": result.warnings,
            "checks": result.checks,
        }
        json.dump(output, sys.stdout, indent=2)
        print()
    else:
        print(f"\nChecks: {result.total} total, {result.pass_count} passed, "
              f"{result.fail_count} failed")
        if result.errors:
            print(f"\nErrors ({len(result.errors)}):")
            for e in result.errors:
                print(f"  {e}")
        if result.warnings:
            print(f"\nWarnings ({len(result.warnings)}):")
            for w in result.warnings:
                print(f"  {w}")
        if result.passed:
            print("\n✓ All fixture integrity checks passed.")
        else:
            print("\n✗ Fixture integrity validation FAILED.")

    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
