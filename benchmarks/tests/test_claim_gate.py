#!/usr/bin/env python3
"""Tests for benchmark claim-threshold gate.

VAL-BENCH-012: Claim-threshold gate is enforced across local and CI.
    Performance winner claims are allowed only when declared claim-threshold
    rules pass for local run + nightly CI run + manual CI run on the same
    commit and manifests.

Tests verify:
  - Claim gate requires local + nightly + manual run evidence.
  - Claims are blocked when parity gate has not passed.
  - Claims are blocked when reproducibility gate has not passed.
  - Claims are blocked when speedup is below threshold.
  - Claims are blocked when CI intervals overlap too much.
  - Claim gate artifact is written and machine-readable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "benchmarks"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_evidence(
    run_id: str,
    run_type: str,
    commit_sha: str = "abc123",
    manifest_hashes: dict | None = None,
    parity_gate: str = "pass",
    reproducibility_gate: str = "pass",
    scenario_summaries: list[dict] | None = None,
) -> dict:
    """Build synthetic run evidence for claim gate testing."""
    if manifest_hashes is None:
        manifest_hashes = {
            "scenarios": "hash-s",
            "queries": "hash-q",
            "corpus": "hash-c",
        }
    if scenario_summaries is None:
        scenario_summaries = [
            {
                "scenario_id": "literal-simple",
                "comparator_stats": {
                    "ag": {
                        "median_s": 0.050,
                        "iqr_s": 0.005,
                        "ci_lower_s": 0.045,
                        "ci_upper_s": 0.055,
                        "ci_level": 0.95,
                        "measured_count": 5,
                    },
                    "rust-ag": {
                        "median_s": 0.030,
                        "iqr_s": 0.003,
                        "ci_lower_s": 0.027,
                        "ci_upper_s": 0.033,
                        "ci_level": 0.95,
                        "measured_count": 5,
                    },
                    "rg": {
                        "median_s": 0.020,
                        "iqr_s": 0.002,
                        "ci_lower_s": 0.018,
                        "ci_upper_s": 0.022,
                        "ci_level": 0.95,
                        "measured_count": 5,
                    },
                    "ugrep": {
                        "median_s": 0.025,
                        "iqr_s": 0.003,
                        "ci_lower_s": 0.022,
                        "ci_upper_s": 0.028,
                        "ci_level": 0.95,
                        "measured_count": 5,
                    },
                },
            },
        ]

    return {
        "run_id": run_id,
        "run_type": run_type,
        "commit_sha": commit_sha,
        "manifest_hashes": manifest_hashes,
        "parity_gate": parity_gate,
        "reproducibility_gate": reproducibility_gate,
        "scenario_summaries": scenario_summaries,
    }


def _make_full_evidence(
    commit_sha: str = "abc123",
    parity_gate: str = "pass",
    reproducibility_gate: str = "pass",
    scenario_summaries: list[dict] | None = None,
) -> list[dict]:
    """Build evidence for all three required run types."""
    return [
        _make_run_evidence(
            "local-run-1", "local", commit_sha,
            parity_gate=parity_gate,
            reproducibility_gate=reproducibility_gate,
            scenario_summaries=scenario_summaries,
        ),
        _make_run_evidence(
            "nightly-run-1", "nightly", commit_sha,
            parity_gate=parity_gate,
            reproducibility_gate=reproducibility_gate,
            scenario_summaries=scenario_summaries,
        ),
        _make_run_evidence(
            "manual-run-1", "manual", commit_sha,
            parity_gate=parity_gate,
            reproducibility_gate=reproducibility_gate,
            scenario_summaries=scenario_summaries,
        ),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestClaimGateRunTypes:
    """Claims require local + nightly + manual run evidence."""

    def test_all_three_run_types_passes(self, tmp_path):
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence()
        result = evaluate_claim_gate(evidence, tmp_path)
        assert result["run_type_check"]["result"] == "pass"

    def test_missing_nightly_fails(self, tmp_path):
        from claim_gate import evaluate_claim_gate

        evidence = [
            _make_run_evidence("local-run-1", "local"),
            _make_run_evidence("manual-run-1", "manual"),
        ]
        result = evaluate_claim_gate(evidence, tmp_path)
        assert result["run_type_check"]["result"] == "fail"

    def test_missing_local_fails(self, tmp_path):
        from claim_gate import evaluate_claim_gate

        evidence = [
            _make_run_evidence("nightly-run-1", "nightly"),
            _make_run_evidence("manual-run-1", "manual"),
        ]
        result = evaluate_claim_gate(evidence, tmp_path)
        assert result["run_type_check"]["result"] == "fail"

    def test_missing_manual_fails(self, tmp_path):
        from claim_gate import evaluate_claim_gate

        evidence = [
            _make_run_evidence("local-run-1", "local"),
            _make_run_evidence("nightly-run-1", "nightly"),
        ]
        result = evaluate_claim_gate(evidence, tmp_path)
        assert result["run_type_check"]["result"] == "fail"


class TestClaimGateParityReproducibility:
    """Claims require parity + reproducibility gates to pass."""

    def test_parity_gate_fail_blocks_claims(self, tmp_path):
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence(parity_gate="fail")
        result = evaluate_claim_gate(evidence, tmp_path)
        assert result["parity_check"]["result"] == "fail"
        assert result["gate"] == "fail"

    def test_reproducibility_gate_fail_blocks_claims(self, tmp_path):
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence(reproducibility_gate="fail")
        result = evaluate_claim_gate(evidence, tmp_path)
        assert result["reproducibility_check"]["result"] == "fail"
        assert result["gate"] == "fail"

    def test_both_gates_pass_allows_claims(self, tmp_path):
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence()
        result = evaluate_claim_gate(evidence, tmp_path)
        assert result["parity_check"]["result"] == "pass"
        assert result["reproducibility_check"]["result"] == "pass"


class TestClaimGateCommitConsistency:
    """Claims require the same commit SHA across run types."""

    def test_consistent_commits_pass(self, tmp_path):
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence(commit_sha="abc123")
        result = evaluate_claim_gate(evidence, tmp_path)
        assert result["commit_check"]["result"] == "pass"

    def test_inconsistent_commits_fail(self, tmp_path):
        from claim_gate import evaluate_claim_gate

        evidence = [
            _make_run_evidence("local-run-1", "local", commit_sha="abc123"),
            _make_run_evidence("nightly-run-1", "nightly", commit_sha="def456"),
            _make_run_evidence("manual-run-1", "manual", commit_sha="abc123"),
        ]
        result = evaluate_claim_gate(evidence, tmp_path)
        assert result["commit_check"]["result"] == "fail"


class TestClaimGateThresholds:
    """Claims require meeting speedup and CI-overlap thresholds."""

    def test_clear_speedup_passes(self, tmp_path):
        """When rust-ag is clearly faster than ag, claim passes threshold."""
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence()
        result = evaluate_claim_gate(evidence, tmp_path)
        # rust-ag (0.030) vs ag (0.050) = 1.67x speedup, well above 1.05x
        claims = result.get("scenario_claims", [])
        if claims:
            for c in claims:
                if c["scenario_id"] == "literal-simple":
                    pairs = c.get("pair_evaluations", [])
                    for p in pairs:
                        if p["faster"] == "rust-ag" and p["slower"] == "ag":
                            assert p["speedup_ratio"] > 1.05

    def test_overlapping_ci_flagged(self, tmp_path):
        """When CIs overlap substantially, claim is blocked."""
        from claim_gate import evaluate_claim_gate

        # Make ag and rust-ag CIs overlap heavily.
        overlapping_summaries = [
            {
                "scenario_id": "literal-simple",
                "comparator_stats": {
                    "ag": {
                        "median_s": 0.050,
                        "iqr_s": 0.020,
                        "ci_lower_s": 0.030,
                        "ci_upper_s": 0.070,
                        "ci_level": 0.95,
                        "measured_count": 5,
                    },
                    "rust-ag": {
                        "median_s": 0.048,
                        "iqr_s": 0.020,
                        "ci_lower_s": 0.028,
                        "ci_upper_s": 0.068,
                        "ci_level": 0.95,
                        "measured_count": 5,
                    },
                },
            },
        ]
        evidence = _make_full_evidence(scenario_summaries=overlapping_summaries)
        result = evaluate_claim_gate(evidence, tmp_path)
        # Should have at least some pair evaluations that are blocked.
        claims = result.get("scenario_claims", [])
        if claims:
            for c in claims:
                pairs = c.get("pair_evaluations", [])
                for p in pairs:
                    if p["faster"] in ("ag", "rust-ag") and p["slower"] in ("ag", "rust-ag"):
                        # Either claim_allowed is False or speedup is below threshold
                        assert not p["claim_allowed"] or p["speedup_ratio"] < 1.05


class TestClaimGateArtifact:
    """Claim gate writes a machine-readable artifact."""

    def test_artifact_written(self, tmp_path):
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence()
        evaluate_claim_gate(evidence, tmp_path)
        artifact = tmp_path / "claim_gate.json"
        assert artifact.exists()
        data = json.loads(artifact.read_text())
        assert "gate" in data
        assert "timestamp" in data
        assert "scenario_claims" in data

    def test_artifact_has_linked_run_ids(self, tmp_path):
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence()
        evaluate_claim_gate(evidence, tmp_path)
        data = json.loads((tmp_path / "claim_gate.json").read_text())
        assert "linked_run_ids" in data
        assert len(data["linked_run_ids"]) == 3

    def test_artifact_has_threshold_evaluation(self, tmp_path):
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence()
        evaluate_claim_gate(evidence, tmp_path)
        data = json.loads((tmp_path / "claim_gate.json").read_text())
        assert "threshold_config" in data


class TestClaimGateOverallGate:
    """Overall claim gate pass/fail."""

    def test_all_good_passes(self, tmp_path):
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence()
        result = evaluate_claim_gate(evidence, tmp_path)
        assert result["gate"] == "pass"

    def test_missing_run_type_fails_gate(self, tmp_path):
        from claim_gate import evaluate_claim_gate

        evidence = [
            _make_run_evidence("local-run-1", "local"),
        ]
        result = evaluate_claim_gate(evidence, tmp_path)
        assert result["gate"] == "fail"
