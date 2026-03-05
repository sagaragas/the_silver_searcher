#!/usr/bin/env python3
"""Tests for benchmark correctness gate.

VAL-BENCH-004: Correctness gate precedes performance claims.
    Scenarios used for performance claims pass output-consistency/correctness
    checks before benchmark comparison is accepted.

Tests verify:
  - Correctness gate passes when all comparator stdout hashes agree.
  - Correctness gate fails when any comparator produces divergent output.
  - Correctness gate emits a machine-readable gate artifact.
  - Skipped scenarios are tolerated.
  - Binary-not-found cells are flagged as failures.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "benchmarks"))


# ---------------------------------------------------------------------------
# Fixtures: synthetic run manifests for correctness testing
# ---------------------------------------------------------------------------


def _make_run_manifest(
    scenarios: list[dict],
    comparators: list[str] | None = None,
    manifest_hashes: dict | None = None,
) -> dict:
    """Build a minimal run manifest for gate testing."""
    return {
        "schema_version": 1,
        "run_id": "test-run",
        "run_type": "smoke",
        "timestamp": "2026-03-05T00:00:00+00:00",
        "commit_sha": "abc123",
        "comparators": comparators or ["ag", "rust-ag", "rg", "ugrep"],
        "manifest_hashes": manifest_hashes or {
            "scenarios": "hash-s",
            "queries": "hash-q",
            "corpus": "hash-c",
        },
        "environment": {
            "timestamp": "2026-03-05T00:00:00+00:00",
            "platform": {
                "system": "Darwin",
                "release": "25.3.0",
                "machine": "arm64",
                "python": "3.14.2",
            },
            "commit_sha": "abc123",
        },
        "tools_metadata": {"comparators": {}},
        "scenario_count": len(scenarios),
        "cell_totals": {"total": 0, "executed": 0, "skipped": 0, "errors": 0},
        "scenarios": scenarios,
    }


def _make_scenario_all_agree(sid: str = "literal-simple") -> dict:
    """Scenario where all comparators produce the same stdout hash."""
    common_hash = "abcdef1234567890" * 4
    return {
        "scenario_id": sid,
        "query_id": "q-literal-simple",
        "pattern": "foo",
        "corpus": ".",
        "commands": {
            "ag": "ag {pattern} {corpus}",
            "rust-ag": "rust-ag {pattern} {corpus}",
            "rg": "rg {pattern} {corpus}",
            "ugrep": "ugrep {pattern} {corpus}",
        },
        "results": {
            "ag": {
                "command": "ag foo .",
                "exit_code": 0,
                "elapsed_s": 0.01,
                "stdout_hash": common_hash,
                "stdout_sorted_hash": common_hash,
                "stdout_bytes": 100,
                "stderr_excerpt": "",
                "timed_out": False,
                "error": None,
            },
            "rust-ag": {
                "command": "rust-ag foo .",
                "exit_code": 0,
                "elapsed_s": 0.008,
                "stdout_hash": common_hash,
                "stdout_sorted_hash": common_hash,
                "stdout_bytes": 100,
                "stderr_excerpt": "",
                "timed_out": False,
                "error": None,
            },
            "rg": {
                "command": "rg foo .",
                "exit_code": 0,
                "elapsed_s": 0.005,
                "stdout_hash": common_hash,
                "stdout_sorted_hash": common_hash,
                "stdout_bytes": 100,
                "stderr_excerpt": "",
                "timed_out": False,
                "error": None,
            },
            "ugrep": {
                "command": "ugrep foo .",
                "exit_code": 0,
                "elapsed_s": 0.006,
                "stdout_hash": common_hash,
                "stdout_sorted_hash": common_hash,
                "stdout_bytes": 100,
                "stderr_excerpt": "",
                "timed_out": False,
                "error": None,
            },
        },
        "skipped": False,
    }


def _make_scenario_divergent(
    sid: str = "literal-divergent",
    divergent_comp: str = "rust-ag",
) -> dict:
    """Scenario where one parity comparator produces a different stdout hash.

    Defaults to rust-ag diverging from ag (the parity pair).
    """
    common_hash = "abcdef1234567890" * 4
    different_hash = "fedcba0987654321" * 4
    base = _make_scenario_all_agree(sid)
    base["scenario_id"] = sid
    base["results"][divergent_comp]["stdout_hash"] = different_hash
    base["results"][divergent_comp]["stdout_sorted_hash"] = different_hash
    return base


def _make_scenario_cross_tool_divergent(
    sid: str = "cross-tool-divergent",
) -> dict:
    """Scenario where ag/rust-ag agree but rg/ugrep differ (advisory only).

    This should PASS the gate since parity pair agrees.
    """
    parity_hash = "abcdef1234567890" * 4
    rg_hash = "rg_hash_different" + "0" * 48
    ugrep_hash = "ugrep_hash_different" + "0" * 44
    base = _make_scenario_all_agree(sid)
    base["scenario_id"] = sid
    base["results"]["rg"]["stdout_sorted_hash"] = rg_hash
    base["results"]["ugrep"]["stdout_sorted_hash"] = ugrep_hash
    return base


def _make_scenario_skipped(sid: str = "skipped-scenario") -> dict:
    """A fully skipped scenario."""
    return {
        "scenario_id": sid,
        "skipped": True,
        "skip_reason": "Platform skip",
    }


def _make_scenario_binary_not_found(sid: str = "missing-binary") -> dict:
    """Scenario with a binary-not-found error for one comparator."""
    base = _make_scenario_all_agree(sid)
    base["scenario_id"] = sid
    base["results"]["ugrep"] = {
        "command": "ugrep foo .",
        "exit_code": -127,
        "elapsed_s": 0,
        "stdout_hash": "",
        "stdout_bytes": 0,
        "stderr_excerpt": "Binary not found: ugrep",
        "timed_out": False,
        "error": "binary_not_found",
    }
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCorrectnessGateLogic:
    """Test correctness_gate module logic."""

    def test_all_agree_passes(self, tmp_path):
        """When all comparators agree on stdout hash, gate passes."""
        from correctness_gate import check_correctness

        manifest = _make_run_manifest([_make_scenario_all_agree()])
        result = check_correctness(manifest, tmp_path)
        assert result["gate"] == "pass"
        assert result["scenarios_checked"] == 1
        assert result["scenarios_passed"] == 1
        assert result["scenarios_failed"] == 0

    def test_divergent_output_fails(self, tmp_path):
        """When one comparator has a different stdout hash, gate fails."""
        from correctness_gate import check_correctness

        manifest = _make_run_manifest([_make_scenario_divergent()])
        result = check_correctness(manifest, tmp_path)
        assert result["gate"] == "fail"
        assert result["scenarios_failed"] == 1

    def test_skipped_scenarios_tolerated(self, tmp_path):
        """Skipped scenarios don't count as failures."""
        from correctness_gate import check_correctness

        manifest = _make_run_manifest([
            _make_scenario_all_agree(),
            _make_scenario_skipped(),
        ])
        result = check_correctness(manifest, tmp_path)
        assert result["gate"] == "pass"
        assert result["scenarios_checked"] == 1
        assert result["scenarios_skipped"] == 1

    def test_binary_not_found_fails(self, tmp_path):
        """Binary-not-found error causes scenario to fail gate."""
        from correctness_gate import check_correctness

        manifest = _make_run_manifest([_make_scenario_binary_not_found()])
        result = check_correctness(manifest, tmp_path)
        assert result["gate"] == "fail"
        assert result["scenarios_failed"] == 1

    def test_gate_artifact_written(self, tmp_path):
        """Gate writes a machine-readable artifact file."""
        from correctness_gate import check_correctness

        manifest = _make_run_manifest([_make_scenario_all_agree()])
        check_correctness(manifest, tmp_path)
        artifact = tmp_path / "correctness_gate.json"
        assert artifact.exists()
        data = json.loads(artifact.read_text())
        assert "gate" in data
        assert "timestamp" in data
        assert "scenarios" in data

    def test_mixed_pass_and_fail(self, tmp_path):
        """Mixed scenario outcomes: gate fails overall if any scenario fails."""
        from correctness_gate import check_correctness

        manifest = _make_run_manifest([
            _make_scenario_all_agree("good-scenario"),
            _make_scenario_divergent("bad-scenario"),
        ])
        result = check_correctness(manifest, tmp_path)
        assert result["gate"] == "fail"
        assert result["scenarios_passed"] == 1
        assert result["scenarios_failed"] == 1

    def test_empty_scenarios_passes_vacuously(self, tmp_path):
        """No scenarios checked means vacuous pass."""
        from correctness_gate import check_correctness

        manifest = _make_run_manifest([])
        result = check_correctness(manifest, tmp_path)
        assert result["gate"] == "pass"
        assert result["scenarios_checked"] == 0

    def test_timed_out_cell_fails(self, tmp_path):
        """A timed-out cell should fail correctness."""
        from correctness_gate import check_correctness

        scenario = _make_scenario_all_agree("timeout-scenario")
        scenario["results"]["rg"]["timed_out"] = True
        scenario["results"]["rg"]["error"] = "timeout"
        scenario["results"]["rg"]["stdout_hash"] = ""
        manifest = _make_run_manifest([scenario])
        result = check_correctness(manifest, tmp_path)
        assert result["gate"] == "fail"
        assert result["scenarios_failed"] == 1

    def test_scenario_details_in_artifact(self, tmp_path):
        """Each scenario in the gate artifact includes pass/fail detail."""
        from correctness_gate import check_correctness

        manifest = _make_run_manifest([
            _make_scenario_all_agree("s1"),
            _make_scenario_divergent("s2"),
        ])
        check_correctness(manifest, tmp_path)
        data = json.loads((tmp_path / "correctness_gate.json").read_text())
        assert len(data["scenarios"]) == 2
        for entry in data["scenarios"]:
            assert "scenario_id" in entry
            assert "result" in entry
            assert entry["result"] in ("pass", "fail")

    def test_cross_tool_divergence_is_advisory(self, tmp_path):
        """rg/ugrep stdout divergence does not fail gate when parity pair agrees."""
        from correctness_gate import check_correctness

        manifest = _make_run_manifest([_make_scenario_cross_tool_divergent()])
        result = check_correctness(manifest, tmp_path)
        assert result["gate"] == "pass"
        assert result["scenarios_passed"] == 1
        assert result["scenarios_failed"] == 0

    def test_parity_pair_recorded_in_artifact(self, tmp_path):
        """Gate artifact records the parity pair used for checking."""
        from correctness_gate import check_correctness

        manifest = _make_run_manifest([_make_scenario_all_agree()])
        check_correctness(manifest, tmp_path)
        data = json.loads((tmp_path / "correctness_gate.json").read_text())
        assert "parity_pair" in data
        assert "ag" in data["parity_pair"]
        assert "rust-ag" in data["parity_pair"]


class TestCorrectnessGateManifestHashes:
    """Test that correctness gate records manifest hashes for traceability."""

    def test_manifest_hashes_in_gate_artifact(self, tmp_path):
        """Gate artifact includes the manifest hashes from the run."""
        from correctness_gate import check_correctness

        hashes = {
            "scenarios": "hash-s-val",
            "queries": "hash-q-val",
            "corpus": "hash-c-val",
        }
        manifest = _make_run_manifest(
            [_make_scenario_all_agree()],
            manifest_hashes=hashes,
        )
        check_correctness(manifest, tmp_path)
        data = json.loads((tmp_path / "correctness_gate.json").read_text())
        assert data["manifest_hashes"] == hashes

    def test_commit_sha_in_gate_artifact(self, tmp_path):
        """Gate artifact includes the commit SHA from the run."""
        from correctness_gate import check_correctness

        manifest = _make_run_manifest([_make_scenario_all_agree()])
        check_correctness(manifest, tmp_path)
        data = json.loads((tmp_path / "correctness_gate.json").read_text())
        assert data["commit_sha"] == "abc123"
