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


class TestClaimGateManifestHashConsistency:
    """Claims require identical manifest hashes across all run types."""

    def test_consistent_manifest_hashes_pass(self, tmp_path):
        from claim_gate import evaluate_claim_gate

        hashes = {"scenarios": "hash-s", "queries": "hash-q", "corpus": "hash-c"}
        evidence = [
            _make_run_evidence("local-run-1", "local", manifest_hashes=hashes),
            _make_run_evidence("nightly-run-1", "nightly", manifest_hashes=hashes),
            _make_run_evidence("manual-run-1", "manual", manifest_hashes=hashes),
        ]
        result = evaluate_claim_gate(evidence, tmp_path)
        assert result["manifest_hash_check"]["result"] == "pass"

    def test_mixed_manifest_hashes_fail(self, tmp_path):
        """Claim gate fails when manifest hashes differ across run types."""
        from claim_gate import evaluate_claim_gate

        evidence = [
            _make_run_evidence(
                "local-run-1", "local",
                manifest_hashes={"scenarios": "hash-s", "queries": "hash-q", "corpus": "hash-c"},
            ),
            _make_run_evidence(
                "nightly-run-1", "nightly",
                manifest_hashes={"scenarios": "DIFFERENT", "queries": "hash-q", "corpus": "hash-c"},
            ),
            _make_run_evidence(
                "manual-run-1", "manual",
                manifest_hashes={"scenarios": "hash-s", "queries": "hash-q", "corpus": "hash-c"},
            ),
        ]
        result = evaluate_claim_gate(evidence, tmp_path)
        assert result["manifest_hash_check"]["result"] == "fail"
        assert result["gate"] == "fail"

    def test_all_manifest_keys_differ_fail(self, tmp_path):
        """Claim gate fails when all manifest hash keys differ."""
        from claim_gate import evaluate_claim_gate

        evidence = [
            _make_run_evidence(
                "local-run-1", "local",
                manifest_hashes={"scenarios": "a", "queries": "b", "corpus": "c"},
            ),
            _make_run_evidence(
                "nightly-run-1", "nightly",
                manifest_hashes={"scenarios": "x", "queries": "y", "corpus": "z"},
            ),
            _make_run_evidence(
                "manual-run-1", "manual",
                manifest_hashes={"scenarios": "a", "queries": "b", "corpus": "c"},
            ),
        ]
        result = evaluate_claim_gate(evidence, tmp_path)
        assert result["manifest_hash_check"]["result"] == "fail"
        assert result["gate"] == "fail"

    def test_single_run_manifest_hash_passes(self, tmp_path):
        """Single run evidence trivially passes manifest consistency (no cross-check)."""
        from claim_gate import evaluate_claim_gate

        evidence = [
            _make_run_evidence("local-run-1", "local"),
        ]
        result = evaluate_claim_gate(evidence, tmp_path)
        # Single run: manifest hashes are trivially consistent
        assert result["manifest_hash_check"]["result"] == "pass"

    def test_artifact_records_manifest_hash_check(self, tmp_path):
        """Claim gate artifact includes manifest_hash_check section."""
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence()
        evaluate_claim_gate(evidence, tmp_path)
        data = json.loads((tmp_path / "claim_gate.json").read_text())
        assert "manifest_hash_check" in data
        assert data["manifest_hash_check"]["result"] == "pass"


class TestClaimGatePerRunTypeThreshold:
    """Claim threshold must pass for each required run type."""

    def test_all_run_types_pass_threshold(self, tmp_path):
        """When all run types show clear speedup, per-run-type check passes."""
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence()
        result = evaluate_claim_gate(evidence, tmp_path)
        # All run types have the same clear stats; per-run-type should pass
        claims = result.get("scenario_claims", [])
        assert len(claims) > 0
        for c in claims:
            if c.get("evaluable"):
                for pe in c.get("pair_evaluations", []):
                    if pe["claim_allowed"]:
                        assert pe.get("per_run_type_pass") is True

    def test_local_passes_but_nightly_fails_blocks_claim(self, tmp_path):
        """Claim is rejected when local passes threshold but nightly fails."""
        from claim_gate import evaluate_claim_gate

        # Local: rust-ag clearly faster (0.030 vs 0.050)
        local_summaries = [
            {
                "scenario_id": "literal-simple",
                "comparator_stats": {
                    "ag": {
                        "median_s": 0.050, "iqr_s": 0.005,
                        "ci_lower_s": 0.045, "ci_upper_s": 0.055,
                        "ci_level": 0.95, "measured_count": 5,
                    },
                    "rust-ag": {
                        "median_s": 0.030, "iqr_s": 0.003,
                        "ci_lower_s": 0.027, "ci_upper_s": 0.033,
                        "ci_level": 0.95, "measured_count": 5,
                    },
                },
            },
        ]
        # Nightly: rust-ag is actually SLOWER (direction disagreement)
        nightly_summaries = [
            {
                "scenario_id": "literal-simple",
                "comparator_stats": {
                    "ag": {
                        "median_s": 0.030, "iqr_s": 0.003,
                        "ci_lower_s": 0.027, "ci_upper_s": 0.033,
                        "ci_level": 0.95, "measured_count": 5,
                    },
                    "rust-ag": {
                        "median_s": 0.050, "iqr_s": 0.005,
                        "ci_lower_s": 0.045, "ci_upper_s": 0.055,
                        "ci_level": 0.95, "measured_count": 5,
                    },
                },
            },
        ]
        # Manual: same as local (passes)
        manual_summaries = local_summaries

        evidence = [
            _make_run_evidence(
                "local-run-1", "local",
                scenario_summaries=local_summaries,
            ),
            _make_run_evidence(
                "nightly-run-1", "nightly",
                scenario_summaries=nightly_summaries,
            ),
            _make_run_evidence(
                "manual-run-1", "manual",
                scenario_summaries=manual_summaries,
            ),
        ]
        result = evaluate_claim_gate(evidence, tmp_path)
        claims = result.get("scenario_claims", [])
        assert len(claims) == 1
        sc = claims[0]
        assert sc["evaluable"]
        # The rust-ag > ag claim should be blocked due to nightly disagreement
        for pe in sc.get("pair_evaluations", []):
            if (pe["faster"] == "rust-ag" and pe["slower"] == "ag") or \
               (pe["faster"] == "ag" and pe["slower"] == "rust-ag"):
                assert not pe["claim_allowed"], \
                    "Claim should be blocked when nightly disagrees with local"

    def test_partial_threshold_pass_blocks_claim(self, tmp_path):
        """Claim is blocked when threshold passes for local but not nightly (overlap)."""
        from claim_gate import evaluate_claim_gate

        # Local: clear separation
        local_summaries = [
            {
                "scenario_id": "literal-simple",
                "comparator_stats": {
                    "ag": {
                        "median_s": 0.050, "iqr_s": 0.005,
                        "ci_lower_s": 0.045, "ci_upper_s": 0.055,
                        "ci_level": 0.95, "measured_count": 5,
                    },
                    "rust-ag": {
                        "median_s": 0.030, "iqr_s": 0.003,
                        "ci_lower_s": 0.027, "ci_upper_s": 0.033,
                        "ci_level": 0.95, "measured_count": 5,
                    },
                },
            },
        ]
        # Nightly: rust-ag is faster but CIs overlap heavily (below threshold)
        nightly_summaries = [
            {
                "scenario_id": "literal-simple",
                "comparator_stats": {
                    "ag": {
                        "median_s": 0.050, "iqr_s": 0.020,
                        "ci_lower_s": 0.030, "ci_upper_s": 0.070,
                        "ci_level": 0.95, "measured_count": 5,
                    },
                    "rust-ag": {
                        "median_s": 0.048, "iqr_s": 0.020,
                        "ci_lower_s": 0.028, "ci_upper_s": 0.068,
                        "ci_level": 0.95, "measured_count": 5,
                    },
                },
            },
        ]
        # Manual: same as local
        manual_summaries = local_summaries

        evidence = [
            _make_run_evidence(
                "local-run-1", "local",
                scenario_summaries=local_summaries,
            ),
            _make_run_evidence(
                "nightly-run-1", "nightly",
                scenario_summaries=nightly_summaries,
            ),
            _make_run_evidence(
                "manual-run-1", "manual",
                scenario_summaries=manual_summaries,
            ),
        ]
        result = evaluate_claim_gate(evidence, tmp_path)
        claims = result.get("scenario_claims", [])
        assert len(claims) == 1
        sc = claims[0]
        assert sc["evaluable"]
        for pe in sc.get("pair_evaluations", []):
            if pe["faster"] in ("ag", "rust-ag") and pe["slower"] in ("ag", "rust-ag"):
                assert not pe["claim_allowed"], \
                    "Claim should be blocked when nightly threshold check fails"
                assert pe.get("per_run_type_pass") is False

    def test_per_run_type_details_in_artifact(self, tmp_path):
        """Claim gate artifact includes per_run_type_results detail."""
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence()
        evaluate_claim_gate(evidence, tmp_path)
        data = json.loads((tmp_path / "claim_gate.json").read_text())
        claims = data.get("scenario_claims", [])
        assert len(claims) > 0
        for c in claims:
            if c.get("evaluable"):
                for pe in c.get("pair_evaluations", []):
                    assert "per_run_type_results" in pe, \
                        "Each pair evaluation must include per_run_type_results"


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

    def test_mixed_manifest_fails_gate(self, tmp_path):
        """Mixed manifests cause overall gate failure."""
        from claim_gate import evaluate_claim_gate

        evidence = [
            _make_run_evidence(
                "local-run-1", "local",
                manifest_hashes={"scenarios": "hash-s", "queries": "hash-q", "corpus": "hash-c"},
            ),
            _make_run_evidence(
                "nightly-run-1", "nightly",
                manifest_hashes={"scenarios": "DIFFERENT", "queries": "hash-q", "corpus": "hash-c"},
            ),
            _make_run_evidence(
                "manual-run-1", "manual",
                manifest_hashes={"scenarios": "hash-s", "queries": "hash-q", "corpus": "hash-c"},
            ),
        ]
        result = evaluate_claim_gate(evidence, tmp_path)
        assert result["gate"] == "fail"


# ---------------------------------------------------------------------------
# VAL-CROSS-007: Cross-run alignment evidence
# ---------------------------------------------------------------------------


def _make_multi_scenario_summaries(scenario_ids: list[str]) -> list[dict]:
    """Build scenario summaries for a given list of scenario IDs."""
    summaries = []
    for sid in scenario_ids:
        summaries.append({
            "scenario_id": sid,
            "comparator_stats": {
                "ag": {
                    "median_s": 0.050, "iqr_s": 0.005,
                    "ci_lower_s": 0.045, "ci_upper_s": 0.055,
                    "ci_level": 0.95, "measured_count": 5,
                },
                "rust-ag": {
                    "median_s": 0.030, "iqr_s": 0.003,
                    "ci_lower_s": 0.027, "ci_upper_s": 0.033,
                    "ci_level": 0.95, "measured_count": 5,
                },
                "rg": {
                    "median_s": 0.020, "iqr_s": 0.002,
                    "ci_lower_s": 0.018, "ci_upper_s": 0.022,
                    "ci_level": 0.95, "measured_count": 5,
                },
                "ugrep": {
                    "median_s": 0.025, "iqr_s": 0.003,
                    "ci_lower_s": 0.022, "ci_upper_s": 0.028,
                    "ci_level": 0.95, "measured_count": 5,
                },
            },
        })
    return summaries


class TestClaimGateLocalVsCIComparisonReport:
    """VAL-CROSS-007: local_vs_ci_comparison_report artifact is generated."""

    def test_report_artifact_written(self, tmp_path):
        """Claim gate writes local_vs_ci_comparison_report.json."""
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence()
        evaluate_claim_gate(evidence, tmp_path)
        report_path = tmp_path / "local_vs_ci_comparison_report.json"
        assert report_path.exists(), "local_vs_ci_comparison_report.json must be generated"
        data = json.loads(report_path.read_text())
        assert "schema_version" in data
        assert "linked_runs" in data

    def test_report_links_all_run_types(self, tmp_path):
        """Report links local/nightly/manual run IDs with their run_types."""
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence()
        evaluate_claim_gate(evidence, tmp_path)
        data = json.loads((tmp_path / "local_vs_ci_comparison_report.json").read_text())
        linked_runs = data["linked_runs"]
        run_types = {r["run_type"] for r in linked_runs}
        assert run_types == {"local", "nightly", "manual"}
        # Each linked run has an ID
        for r in linked_runs:
            assert "run_id" in r
            assert "run_type" in r

    def test_report_includes_commit_and_manifest_match(self, tmp_path):
        """Report confirms commit_sha and manifest_hashes match across runs."""
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence()
        evaluate_claim_gate(evidence, tmp_path)
        data = json.loads((tmp_path / "local_vs_ci_comparison_report.json").read_text())
        assert "commit_match" in data
        assert data["commit_match"]["result"] == "pass"
        assert "manifest_match" in data
        assert data["manifest_match"]["result"] == "pass"

    def test_report_includes_schema_validity(self, tmp_path):
        """Report includes per-run schema validity check."""
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence()
        evaluate_claim_gate(evidence, tmp_path)
        data = json.loads((tmp_path / "local_vs_ci_comparison_report.json").read_text())
        assert "per_run_schema_validity" in data
        validity = data["per_run_schema_validity"]
        # One entry per evidence run
        assert len(validity) == 3
        for entry in validity:
            assert entry["result"] == "pass"

    def test_report_includes_overall_result(self, tmp_path):
        """Report has overall result field."""
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence()
        evaluate_claim_gate(evidence, tmp_path)
        data = json.loads((tmp_path / "local_vs_ci_comparison_report.json").read_text())
        assert "result" in data
        assert data["result"] == "pass"

    def test_report_fails_with_inconsistent_commits(self, tmp_path):
        """Report result is fail when commits differ."""
        from claim_gate import evaluate_claim_gate

        evidence = [
            _make_run_evidence("local-run-1", "local", commit_sha="abc123"),
            _make_run_evidence("nightly-run-1", "nightly", commit_sha="def456"),
            _make_run_evidence("manual-run-1", "manual", commit_sha="abc123"),
        ]
        evaluate_claim_gate(evidence, tmp_path)
        data = json.loads((tmp_path / "local_vs_ci_comparison_report.json").read_text())
        assert data["commit_match"]["result"] == "fail"
        assert data["result"] == "fail"

    def test_report_fails_with_inconsistent_manifests(self, tmp_path):
        """Report result is fail when manifest hashes differ."""
        from claim_gate import evaluate_claim_gate

        evidence = [
            _make_run_evidence(
                "local-run-1", "local",
                manifest_hashes={"scenarios": "a", "queries": "b", "corpus": "c"},
            ),
            _make_run_evidence(
                "nightly-run-1", "nightly",
                manifest_hashes={"scenarios": "x", "queries": "b", "corpus": "c"},
            ),
            _make_run_evidence(
                "manual-run-1", "manual",
                manifest_hashes={"scenarios": "a", "queries": "b", "corpus": "c"},
            ),
        ]
        evaluate_claim_gate(evidence, tmp_path)
        data = json.loads((tmp_path / "local_vs_ci_comparison_report.json").read_text())
        assert data["manifest_match"]["result"] == "fail"
        assert data["result"] == "fail"


class TestClaimGateRunManifestSetEqualityDiffReport:
    """VAL-CROSS-007: run_manifest_set_equality_diff_report artifact."""

    def test_diff_report_artifact_written(self, tmp_path):
        """Claim gate writes run_manifest_set_equality_diff_report.json."""
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence()
        evaluate_claim_gate(evidence, tmp_path)
        report_path = tmp_path / "run_manifest_set_equality_diff_report.json"
        assert report_path.exists(), \
            "run_manifest_set_equality_diff_report.json must be generated"
        data = json.loads(report_path.read_text())
        assert "schema_version" in data

    def test_identical_scenario_sets_pass(self, tmp_path):
        """When all runs have the same scenario sets, diff is empty."""
        from claim_gate import evaluate_claim_gate

        scenarios = ["literal-simple", "regex-simple"]
        summaries = _make_multi_scenario_summaries(scenarios)
        evidence = [
            _make_run_evidence(
                "local-1", "local", scenario_summaries=summaries,
            ),
            _make_run_evidence(
                "nightly-1", "nightly", scenario_summaries=summaries,
            ),
            _make_run_evidence(
                "manual-1", "manual", scenario_summaries=summaries,
            ),
        ]
        evaluate_claim_gate(evidence, tmp_path)
        data = json.loads(
            (tmp_path / "run_manifest_set_equality_diff_report.json").read_text()
        )
        assert data["result"] == "pass"
        assert data["missing_scenarios"] == []
        assert data["extra_scenarios"] == []

    def test_missing_scenario_in_one_run_fails(self, tmp_path):
        """When one run has fewer scenarios, diff reports missing."""
        from claim_gate import evaluate_claim_gate

        full_summaries = _make_multi_scenario_summaries(
            ["literal-simple", "regex-simple"]
        )
        partial_summaries = _make_multi_scenario_summaries(["literal-simple"])

        evidence = [
            _make_run_evidence(
                "local-1", "local", scenario_summaries=full_summaries,
            ),
            _make_run_evidence(
                "nightly-1", "nightly", scenario_summaries=partial_summaries,
            ),
            _make_run_evidence(
                "manual-1", "manual", scenario_summaries=full_summaries,
            ),
        ]
        evaluate_claim_gate(evidence, tmp_path)
        data = json.loads(
            (tmp_path / "run_manifest_set_equality_diff_report.json").read_text()
        )
        assert data["result"] == "fail"
        assert len(data["missing_scenarios"]) > 0

    def test_extra_scenario_in_one_run_fails(self, tmp_path):
        """When one run has extra scenarios, diff reports extras."""
        from claim_gate import evaluate_claim_gate

        base_summaries = _make_multi_scenario_summaries(["literal-simple"])
        extra_summaries = _make_multi_scenario_summaries(
            ["literal-simple", "regex-simple"]
        )

        evidence = [
            _make_run_evidence(
                "local-1", "local", scenario_summaries=base_summaries,
            ),
            _make_run_evidence(
                "nightly-1", "nightly", scenario_summaries=extra_summaries,
            ),
            _make_run_evidence(
                "manual-1", "manual", scenario_summaries=base_summaries,
            ),
        ]
        evaluate_claim_gate(evidence, tmp_path)
        data = json.loads(
            (tmp_path / "run_manifest_set_equality_diff_report.json").read_text()
        )
        assert data["result"] == "fail"
        assert len(data["extra_scenarios"]) > 0

    def test_diff_report_includes_per_run_sets(self, tmp_path):
        """Report includes scenario set per run_type for debugging."""
        from claim_gate import evaluate_claim_gate

        scenarios = ["literal-simple"]
        summaries = _make_multi_scenario_summaries(scenarios)
        evidence = [
            _make_run_evidence(
                "local-1", "local", scenario_summaries=summaries,
            ),
            _make_run_evidence(
                "nightly-1", "nightly", scenario_summaries=summaries,
            ),
            _make_run_evidence(
                "manual-1", "manual", scenario_summaries=summaries,
            ),
        ]
        evaluate_claim_gate(evidence, tmp_path)
        data = json.loads(
            (tmp_path / "run_manifest_set_equality_diff_report.json").read_text()
        )
        assert "per_run_type_scenarios" in data
        assert "local" in data["per_run_type_scenarios"]
        assert "nightly" in data["per_run_type_scenarios"]
        assert "manual" in data["per_run_type_scenarios"]

    def test_set_equality_failure_fails_overall_gate(self, tmp_path):
        """When scenario sets differ, overall claim gate fails."""
        from claim_gate import evaluate_claim_gate

        full_summaries = _make_multi_scenario_summaries(
            ["literal-simple", "regex-simple"]
        )
        partial_summaries = _make_multi_scenario_summaries(["literal-simple"])

        evidence = [
            _make_run_evidence(
                "local-1", "local", scenario_summaries=full_summaries,
            ),
            _make_run_evidence(
                "nightly-1", "nightly", scenario_summaries=partial_summaries,
            ),
            _make_run_evidence(
                "manual-1", "manual", scenario_summaries=full_summaries,
            ),
        ]
        result = evaluate_claim_gate(evidence, tmp_path)
        assert result["gate"] == "fail"
        assert result["set_equality_check"]["result"] == "fail"


class TestClaimGateCrossRunAlignmentIntegration:
    """Integration tests for cross-run alignment (VAL-CROSS-007)."""

    def test_full_alignment_pass(self, tmp_path):
        """All alignment checks pass with identical evidence."""
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence()
        result = evaluate_claim_gate(evidence, tmp_path)
        assert result["gate"] == "pass"
        assert result["set_equality_check"]["result"] == "pass"

        # Both artifacts exist
        assert (tmp_path / "local_vs_ci_comparison_report.json").exists()
        assert (tmp_path / "run_manifest_set_equality_diff_report.json").exists()

        # Both artifacts have pass result
        ci_report = json.loads(
            (tmp_path / "local_vs_ci_comparison_report.json").read_text()
        )
        assert ci_report["result"] == "pass"

        diff_report = json.loads(
            (tmp_path / "run_manifest_set_equality_diff_report.json").read_text()
        )
        assert diff_report["result"] == "pass"

    def test_schema_validity_checked_per_run(self, tmp_path):
        """Each run's evidence is schema-validated in the comparison report."""
        from claim_gate import evaluate_claim_gate

        # Evidence with missing fields should flag schema issues
        bad_evidence = [
            {
                "run_id": "local-1",
                "run_type": "local",
                "commit_sha": "abc123",
                "manifest_hashes": {"scenarios": "a", "queries": "b", "corpus": "c"},
                "parity_gate": "pass",
                "reproducibility_gate": "pass",
                "scenario_summaries": [],
            },
            {
                "run_id": "nightly-1",
                "run_type": "nightly",
                "commit_sha": "abc123",
                "manifest_hashes": {"scenarios": "a", "queries": "b", "corpus": "c"},
                "parity_gate": "pass",
                "reproducibility_gate": "pass",
                "scenario_summaries": [],
            },
            {
                "run_id": "manual-1",
                "run_type": "manual",
                "commit_sha": "abc123",
                "manifest_hashes": {"scenarios": "a", "queries": "b", "corpus": "c"},
                "parity_gate": "pass",
                "reproducibility_gate": "pass",
                "scenario_summaries": [],
            },
        ]
        evaluate_claim_gate(bad_evidence, tmp_path)
        data = json.loads(
            (tmp_path / "local_vs_ci_comparison_report.json").read_text()
        )
        # Schema validity is checked; no scenarios is still valid schema
        assert "per_run_schema_validity" in data

    def test_claim_gate_report_has_set_equality_check(self, tmp_path):
        """Main claim gate report includes set_equality_check section."""
        from claim_gate import evaluate_claim_gate

        evidence = _make_full_evidence()
        result = evaluate_claim_gate(evidence, tmp_path)
        assert "set_equality_check" in result
        assert result["set_equality_check"]["result"] == "pass"

    def test_single_run_alignment_passes_trivially(self, tmp_path):
        """Single-run evidence trivially passes alignment checks."""
        from claim_gate import evaluate_claim_gate

        evidence = [_make_run_evidence("local-1", "local")]
        result = evaluate_claim_gate(evidence, tmp_path)
        # Set equality is trivially pass for single run
        assert result["set_equality_check"]["result"] == "pass"
        # Artifacts still generated
        assert (tmp_path / "local_vs_ci_comparison_report.json").exists()
        assert (tmp_path / "run_manifest_set_equality_diff_report.json").exists()


# ---------------------------------------------------------------------------
# Cross-run evidence linking (_find_linked_runs)
# ---------------------------------------------------------------------------


def _create_run_dir(
    base: Path,
    run_id: str,
    run_type: str,
    commit_sha: str = "abc123",
    manifest_hashes: dict | None = None,
) -> Path:
    """Create a synthetic benchmark run directory with a run_manifest.json."""
    if manifest_hashes is None:
        manifest_hashes = {
            "scenarios": "hash-s",
            "queries": "hash-q",
            "corpus": "hash-c",
        }
    run_dir = base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 2,
        "run_id": run_id,
        "run_type": run_type,
        "commit_sha": commit_sha,
        "manifest_hashes": manifest_hashes,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    return run_dir


class TestFindLinkedRuns:
    """Tests for _find_linked_runs cross-run evidence selection."""

    def test_finds_all_three_run_types(self, tmp_path):
        """Links exactly one run per required run_type matching commit + manifests."""
        from claim_gate import _find_linked_runs

        _create_run_dir(tmp_path, "run-local", "local")
        _create_run_dir(tmp_path, "run-nightly", "nightly")
        _create_run_dir(tmp_path, "run-manual", "manual")

        seed_dir = tmp_path / "run-local"
        linked = _find_linked_runs(seed_dir, tmp_path)
        run_types = {e["run_type"] for e in linked}
        assert run_types == {"local", "nightly", "manual"}
        assert len(linked) == 3

    def test_selects_exactly_one_per_run_type(self, tmp_path):
        """When multiple runs of the same type exist, selects exactly one (most recent)."""
        from claim_gate import _find_linked_runs

        _create_run_dir(tmp_path, "20260305T100000Z", "local")
        _create_run_dir(tmp_path, "20260305T110000Z", "local")
        _create_run_dir(tmp_path, "20260305T120000Z", "nightly")
        _create_run_dir(tmp_path, "20260305T130000Z", "manual")

        seed_dir = tmp_path / "20260305T110000Z"
        linked = _find_linked_runs(seed_dir, tmp_path)
        run_types = [e["run_type"] for e in linked]
        assert sorted(run_types) == ["local", "manual", "nightly"]
        # The local run should be the more recent one (the seed)
        local_entries = [e for e in linked if e["run_type"] == "local"]
        assert len(local_entries) == 1
        assert local_entries[0]["run_id"] == "20260305T110000Z"

    def test_filters_by_commit_sha(self, tmp_path):
        """Only links runs with matching commit_sha."""
        from claim_gate import _find_linked_runs

        _create_run_dir(tmp_path, "run-local", "local", commit_sha="abc123")
        _create_run_dir(tmp_path, "run-nightly", "nightly", commit_sha="abc123")
        _create_run_dir(tmp_path, "run-manual", "manual", commit_sha="DIFFERENT")

        seed_dir = tmp_path / "run-local"
        linked = _find_linked_runs(seed_dir, tmp_path)
        run_types = {e["run_type"] for e in linked}
        # manual has different commit, so only local + nightly
        assert "manual" not in run_types
        assert "local" in run_types
        assert "nightly" in run_types

    def test_filters_by_manifest_hashes(self, tmp_path):
        """Only links runs with matching manifest_hashes."""
        from claim_gate import _find_linked_runs

        hashes_a = {"scenarios": "a", "queries": "b", "corpus": "c"}
        hashes_b = {"scenarios": "x", "queries": "b", "corpus": "c"}

        _create_run_dir(tmp_path, "run-local", "local", manifest_hashes=hashes_a)
        _create_run_dir(tmp_path, "run-nightly", "nightly", manifest_hashes=hashes_a)
        _create_run_dir(tmp_path, "run-manual", "manual", manifest_hashes=hashes_b)

        seed_dir = tmp_path / "run-local"
        linked = _find_linked_runs(seed_dir, tmp_path)
        run_types = {e["run_type"] for e in linked}
        # manual has different hashes, so excluded
        assert "manual" not in run_types

    def test_returns_only_seed_when_no_matches(self, tmp_path):
        """When no other runs match, returns only the seed run evidence."""
        from claim_gate import _find_linked_runs

        _create_run_dir(tmp_path, "run-local", "local", commit_sha="abc123")
        _create_run_dir(tmp_path, "run-nightly", "nightly", commit_sha="DIFF")
        _create_run_dir(tmp_path, "run-manual", "manual", commit_sha="OTHER")

        seed_dir = tmp_path / "run-local"
        linked = _find_linked_runs(seed_dir, tmp_path)
        assert len(linked) == 1
        assert linked[0]["run_type"] == "local"

    def test_skips_directories_without_manifest(self, tmp_path):
        """Directories without run_manifest.json are silently skipped."""
        from claim_gate import _find_linked_runs

        _create_run_dir(tmp_path, "run-local", "local")
        _create_run_dir(tmp_path, "run-nightly", "nightly")
        # Create empty directory (no manifest)
        (tmp_path / "no-manifest-dir").mkdir()

        seed_dir = tmp_path / "run-local"
        linked = _find_linked_runs(seed_dir, tmp_path)
        # Should not crash; should find the two valid runs
        run_ids = {e["run_id"] for e in linked}
        assert "no-manifest-dir" not in run_ids

    def test_prefers_most_recent_run_per_type(self, tmp_path):
        """When multiple matching runs of same type exist, picks the most recent."""
        from claim_gate import _find_linked_runs

        # Older local run
        _create_run_dir(tmp_path, "20260305T100000Z", "local")
        # Newer local run (seed)
        _create_run_dir(tmp_path, "20260305T120000Z", "local")
        _create_run_dir(tmp_path, "20260305T110000Z", "nightly")
        _create_run_dir(tmp_path, "20260305T130000Z", "manual")

        seed_dir = tmp_path / "20260305T120000Z"
        linked = _find_linked_runs(seed_dir, tmp_path)
        local_entries = [e for e in linked if e["run_type"] == "local"]
        assert len(local_entries) == 1
        # Should pick the most recent (seed itself or later)
        assert local_entries[0]["run_id"] == "20260305T120000Z"


class TestClaimGateCLILinksMultipleRuns:
    """Integration: claim_gate.py --run <id> links runs from run output dir."""

    def test_main_links_three_run_types(self, tmp_path):
        """When invoked with --run, links matching runs across run_types."""
        from claim_gate import load_run_evidence, _find_linked_runs, evaluate_claim_gate

        # Create three runs with same commit/manifests
        _create_run_dir(tmp_path, "run-local", "local")
        _create_run_dir(tmp_path, "run-nightly", "nightly")
        _create_run_dir(tmp_path, "run-manual", "manual")

        seed_dir = tmp_path / "run-local"
        linked = _find_linked_runs(seed_dir, tmp_path)
        assert len(linked) == 3

        # Evaluate on the linked evidence
        result = evaluate_claim_gate(linked, tmp_path)
        assert result["run_type_check"]["result"] == "pass"
        assert len(result["linked_run_ids"]) == 3
