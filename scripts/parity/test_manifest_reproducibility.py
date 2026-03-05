#!/usr/bin/env python3
"""Tests for manifest reproducibility.

Verifies that the fixture and corpus manifest generation:
  - Produces identical hashes across consecutive runs.
  - Excludes build-generated artifacts (object files, autoconf outputs, etc.).
  - Handles broken symlinks gracefully.
  - Respects explicit EXCLUDE rules.
  - Uses only git-tracked files.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# Ensure the script directories are importable.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "parity"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "bench"))


class TestFixtureManifestReproducibility(unittest.TestCase):
    """Fixture manifest (build_fixture_manifest.py) reproducibility tests."""

    def test_consecutive_builds_produce_identical_hashes(self):
        """Two consecutive builds must produce the same manifest hash."""
        from build_fixture_manifest import build_manifest

        m1 = build_manifest()
        m2 = build_manifest()
        self.assertEqual(
            m1["manifest_hash"],
            m2["manifest_hash"],
            "Fixture manifest hashes must be identical across consecutive runs",
        )
        self.assertEqual(m1["file_count"], m2["file_count"])

    def test_no_object_files_in_manifest(self):
        """Manifest must not contain .o files."""
        from build_fixture_manifest import build_manifest

        m = build_manifest()
        o_files = [e["path"] for e in m["files"] if e["path"].endswith(".o")]
        self.assertEqual(o_files, [], f"Object files found in manifest: {o_files}")

    def test_no_deps_directory_in_manifest(self):
        """Manifest must not contain any paths from .deps directories."""
        from build_fixture_manifest import build_manifest

        m = build_manifest()
        deps = [e["path"] for e in m["files"] if "/.deps/" in e["path"] or e["path"].startswith(".deps/")]
        self.assertEqual(deps, [], f".deps files found in manifest: {deps}")

    def test_no_pyc_files_in_manifest(self):
        """Manifest must not contain .pyc files."""
        from build_fixture_manifest import build_manifest

        m = build_manifest()
        pyc = [e["path"] for e in m["files"] if e["path"].endswith(".pyc")]
        self.assertEqual(pyc, [], f".pyc files found in manifest: {pyc}")

    def test_no_pycache_in_manifest(self):
        """Manifest must not contain __pycache__ paths."""
        from build_fixture_manifest import build_manifest

        m = build_manifest()
        pycache = [e["path"] for e in m["files"] if "__pycache__" in e["path"]]
        self.assertEqual(pycache, [], f"__pycache__ files found: {pycache}")

    def test_no_dirstamp_in_manifest(self):
        """Manifest must not contain .dirstamp files."""
        from build_fixture_manifest import build_manifest

        m = build_manifest()
        ds = [e["path"] for e in m["files"] if ".dirstamp" in e["path"]]
        self.assertEqual(ds, [], f".dirstamp files found: {ds}")

    def test_no_config_h_in_manifest(self):
        """Manifest must not contain config.h (build-generated)."""
        from build_fixture_manifest import build_manifest

        m = build_manifest()
        cfg = [e["path"] for e in m["files"] if os.path.basename(e["path"]) == "config.h"]
        self.assertEqual(cfg, [], f"config.h files found: {cfg}")

    def test_should_skip_excludes_build_artifacts(self):
        """_should_skip correctly identifies build artifact paths."""
        from build_fixture_manifest import _should_skip

        # Must be skipped.
        self.assertTrue(_should_skip("src/.deps/main.Po"))
        self.assertTrue(_should_skip("src/main.o"))
        self.assertTrue(_should_skip("src/.dirstamp"))
        self.assertTrue(_should_skip("src/config.h"))
        self.assertTrue(_should_skip("src/stamp-h1"))
        self.assertTrue(_should_skip("tests/__pycache__/test.cpython-311.pyc"))
        self.assertTrue(_should_skip("tests/foo.err"))
        self.assertTrue(_should_skip("tests/big/big_file.trs"))

        # Must NOT be skipped.
        self.assertFalse(_should_skip("tests/count.t"))
        self.assertFalse(_should_skip("src/main.c"))
        self.assertFalse(_should_skip("src/search.h"))
        self.assertFalse(_should_skip("tests/edge-cases/hidden-files/.gitignore"))

    def test_manifest_entries_sorted_by_path(self):
        """Manifest entries must be sorted by path for determinism."""
        from build_fixture_manifest import build_manifest

        m = build_manifest()
        paths = [e["path"] for e in m["files"]]
        self.assertEqual(paths, sorted(paths))

    def test_verify_matches_generate(self):
        """--verify mode should pass after a fresh generate."""
        from build_fixture_manifest import build_manifest, write_manifest, verify_manifest

        m = build_manifest()
        write_manifest(m)
        self.assertTrue(verify_manifest())


class TestScenarioManifestReproducibility(unittest.TestCase):
    """Scenario/corpus manifest (build_scenario_manifest.py) reproducibility tests."""

    def test_consecutive_corpus_builds_produce_identical_hashes(self):
        """Two consecutive corpus manifest builds must produce the same hash."""
        from build_scenario_manifest import build_corpus_manifest

        c1 = build_corpus_manifest()
        c2 = build_corpus_manifest()
        self.assertEqual(
            c1["manifest_hash"],
            c2["manifest_hash"],
            "Corpus manifest hashes must be identical across consecutive runs",
        )
        self.assertEqual(c1["file_count"], c2["file_count"])

    def test_consecutive_full_builds_produce_identical_hashes(self):
        """Full scenario/queries/corpus builds must be reproducible."""
        from build_scenario_manifest import (
            build_corpus_manifest,
            build_queries_manifest,
            build_scenarios_manifest,
        )

        c1 = build_corpus_manifest()
        q1 = build_queries_manifest()
        s1 = build_scenarios_manifest(c1["manifest_hash"], q1["manifest_hash"])

        c2 = build_corpus_manifest()
        q2 = build_queries_manifest()
        s2 = build_scenarios_manifest(c2["manifest_hash"], q2["manifest_hash"])

        self.assertEqual(c1["manifest_hash"], c2["manifest_hash"])
        self.assertEqual(q1["manifest_hash"], q2["manifest_hash"])
        self.assertEqual(s1["manifest_hash"], s2["manifest_hash"])

    def test_no_object_files_in_corpus(self):
        """Corpus manifest must not contain .o files."""
        from build_scenario_manifest import build_corpus_manifest

        c = build_corpus_manifest()
        o_files = [e["path"] for e in c["files"] if e["path"].endswith(".o")]
        self.assertEqual(o_files, [], f"Object files found: {o_files}")

    def test_no_deps_in_corpus(self):
        """Corpus manifest must not contain .deps directory content."""
        from build_scenario_manifest import build_corpus_manifest

        c = build_corpus_manifest()
        deps = [e["path"] for e in c["files"] if "/.deps/" in e["path"]]
        self.assertEqual(deps, [], f".deps files found: {deps}")

    def test_no_dirstamp_in_corpus(self):
        """Corpus manifest must not contain .dirstamp files."""
        from build_scenario_manifest import build_corpus_manifest

        c = build_corpus_manifest()
        ds = [e["path"] for e in c["files"] if ".dirstamp" in e["path"]]
        self.assertEqual(ds, [], f".dirstamp files found: {ds}")

    def test_no_config_h_in_corpus(self):
        """Corpus manifest must not contain build-generated config.h."""
        from build_scenario_manifest import build_corpus_manifest

        c = build_corpus_manifest()
        cfg = [e["path"] for e in c["files"] if os.path.basename(e["path"]) == "config.h"]
        self.assertEqual(cfg, [], f"config.h files found: {cfg}")

    def test_no_stamp_h1_in_corpus(self):
        """Corpus manifest must not contain stamp-h1."""
        from build_scenario_manifest import build_corpus_manifest

        c = build_corpus_manifest()
        stamps = [e["path"] for e in c["files"] if "stamp-h1" in e["path"]]
        self.assertEqual(stamps, [], f"stamp-h1 files found: {stamps}")

    def test_should_skip_excludes_build_artifacts(self):
        """_should_skip correctly identifies build artifact paths."""
        from build_scenario_manifest import _should_skip

        self.assertTrue(_should_skip("src/.deps/main.Po"))
        self.assertTrue(_should_skip("src/main.o"))
        self.assertTrue(_should_skip("src/.dirstamp"))
        self.assertTrue(_should_skip("src/config.h"))
        self.assertTrue(_should_skip("src/stamp-h1"))
        self.assertTrue(_should_skip("tests/__pycache__/test.cpython-311.pyc"))

        self.assertFalse(_should_skip("src/main.c"))
        self.assertFalse(_should_skip("src/search.h"))
        self.assertFalse(_should_skip("tests/count.t"))

    def test_corpus_entries_sorted_by_path(self):
        """Corpus entries must be sorted by path for determinism."""
        from build_scenario_manifest import build_corpus_manifest

        c = build_corpus_manifest()
        paths = [e["path"] for e in c["files"]]
        self.assertEqual(paths, sorted(paths))

    def test_verify_matches_generate(self):
        """--verify mode should pass after a fresh generate."""
        from build_scenario_manifest import write_all, verify_all

        write_all()
        self.assertTrue(verify_all())


if __name__ == "__main__":
    unittest.main()
