#!/usr/bin/env python3
"""Tests for manifest hash pinning and reproducibility reporting.

VAL-BENCH-003: Input corpus/query manifests are immutable.
    Benchmark runs reference corpus and query manifests with hashes;
    compared runs use identical manifest hashes.

Tests verify:
  - Run manifests embed manifest hashes for scenarios, queries, corpus.
  - Reproducibility report compares manifest hashes between two runs.
  - Mismatched hashes produce a clear failure report.
  - On-disk manifest hashes match what's recorded in run manifests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "benchmarks"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_run_manifest_with_hashes(
    run_id: str,
    hashes: dict,
) -> dict:
    """Build a minimal run manifest with specific manifest hashes."""
    return {
        "schema_version": 1,
        "run_id": run_id,
        "run_type": "smoke",
        "timestamp": "2026-03-05T00:00:00+00:00",
        "commit_sha": "abc123",
        "comparators": ["ag", "rust-ag", "rg", "ugrep"],
        "manifest_hashes": hashes,
        "environment": {},
        "tools_metadata": {"comparators": {}},
        "scenario_count": 0,
        "cell_totals": {"total": 0, "executed": 0, "skipped": 0, "errors": 0},
        "scenarios": [],
    }


# ---------------------------------------------------------------------------
# Tests: Manifest hash presence
# ---------------------------------------------------------------------------


class TestManifestHashPresence:
    """Verify that run manifests always contain manifest hashes."""

    def test_run_manifest_has_scenario_hash(self):
        """Run manifest must have a scenarios hash."""
        from harness import _load_json

        # Use the on-disk latest run if available.
        latest = REPO_ROOT / "benchmarks" / "out" / "latest" / "run_manifest.json"
        if not latest.exists():
            pytest.skip("No latest benchmark run available")
        manifest = _load_json(latest.resolve())
        assert "manifest_hashes" in manifest
        assert manifest["manifest_hashes"].get("scenarios"), "scenarios hash missing"

    def test_run_manifest_has_queries_hash(self):
        """Run manifest must have a queries hash."""
        from harness import _load_json

        latest = REPO_ROOT / "benchmarks" / "out" / "latest" / "run_manifest.json"
        if not latest.exists():
            pytest.skip("No latest benchmark run available")
        manifest = _load_json(latest.resolve())
        assert manifest["manifest_hashes"].get("queries"), "queries hash missing"

    def test_run_manifest_has_corpus_hash(self):
        """Run manifest must have a corpus hash."""
        from harness import _load_json

        latest = REPO_ROOT / "benchmarks" / "out" / "latest" / "run_manifest.json"
        if not latest.exists():
            pytest.skip("No latest benchmark run available")
        manifest = _load_json(latest.resolve())
        assert manifest["manifest_hashes"].get("corpus"), "corpus hash missing"


# ---------------------------------------------------------------------------
# Tests: Reproducibility report (compare hashes between runs)
# ---------------------------------------------------------------------------


class TestReproducibilityReport:
    """Test manifest hash comparison and reproducibility reporting."""

    def test_matching_hashes_pass(self, tmp_path):
        """Two runs with identical hashes produce a pass report."""
        from manifest_pinning import compare_manifest_hashes

        hashes = {
            "scenarios": "same-hash-s",
            "queries": "same-hash-q",
            "corpus": "same-hash-c",
        }
        run_a = _make_run_manifest_with_hashes("run-a", hashes)
        run_b = _make_run_manifest_with_hashes("run-b", hashes)
        report = compare_manifest_hashes(run_a, run_b, tmp_path)
        assert report["result"] == "pass"
        assert report["mismatches"] == []

    def test_mismatched_scenario_hash_fails(self, tmp_path):
        """Different scenario hashes produce a failure report."""
        from manifest_pinning import compare_manifest_hashes

        hashes_a = {"scenarios": "hash-1", "queries": "hash-q", "corpus": "hash-c"}
        hashes_b = {"scenarios": "hash-2", "queries": "hash-q", "corpus": "hash-c"}
        run_a = _make_run_manifest_with_hashes("run-a", hashes_a)
        run_b = _make_run_manifest_with_hashes("run-b", hashes_b)
        report = compare_manifest_hashes(run_a, run_b, tmp_path)
        assert report["result"] == "fail"
        assert any(m["manifest"] == "scenarios" for m in report["mismatches"])

    def test_mismatched_corpus_hash_fails(self, tmp_path):
        """Different corpus hashes produce a failure report."""
        from manifest_pinning import compare_manifest_hashes

        hashes_a = {"scenarios": "s", "queries": "q", "corpus": "c1"}
        hashes_b = {"scenarios": "s", "queries": "q", "corpus": "c2"}
        run_a = _make_run_manifest_with_hashes("run-a", hashes_a)
        run_b = _make_run_manifest_with_hashes("run-b", hashes_b)
        report = compare_manifest_hashes(run_a, run_b, tmp_path)
        assert report["result"] == "fail"
        assert any(m["manifest"] == "corpus" for m in report["mismatches"])

    def test_report_artifact_written(self, tmp_path):
        """Reproducibility report is written as a JSON artifact."""
        from manifest_pinning import compare_manifest_hashes

        hashes = {"scenarios": "s", "queries": "q", "corpus": "c"}
        run_a = _make_run_manifest_with_hashes("run-a", hashes)
        run_b = _make_run_manifest_with_hashes("run-b", hashes)
        compare_manifest_hashes(run_a, run_b, tmp_path)
        artifact = tmp_path / "reproducibility_report.json"
        assert artifact.exists()
        data = json.loads(artifact.read_text())
        assert "result" in data
        assert "run_a_id" in data
        assert "run_b_id" in data

    def test_all_hashes_missing_fails(self, tmp_path):
        """Empty manifest hashes in run produce failure."""
        from manifest_pinning import compare_manifest_hashes

        run_a = _make_run_manifest_with_hashes("run-a", {})
        run_b = _make_run_manifest_with_hashes("run-b", {})
        report = compare_manifest_hashes(run_a, run_b, tmp_path)
        # Both empty = structurally matching but incomplete
        assert report["result"] == "fail"


# ---------------------------------------------------------------------------
# Tests: On-disk manifest hash verification
# ---------------------------------------------------------------------------


class TestOnDiskManifestHashVerification:
    """Test that on-disk manifests match recorded hashes in benchmark runs."""

    def test_verify_on_disk_hashes_match(self, tmp_path):
        """Recorded hashes match current on-disk manifests."""
        from manifest_pinning import verify_manifest_hashes_on_disk

        latest = REPO_ROOT / "benchmarks" / "out" / "latest" / "run_manifest.json"
        if not latest.exists():
            pytest.skip("No latest benchmark run available")

        from harness import _load_json

        manifest = _load_json(latest.resolve())
        result = verify_manifest_hashes_on_disk(manifest, REPO_ROOT / "manifests")
        assert result["result"] == "pass", f"Hash mismatch: {result.get('mismatches')}"
