#!/usr/bin/env python3
"""Tests for benchmark sampling, warmup, statistical method, order-bias,
and outlier/retry policy enforcement.

VAL-BENCH-006: Sampling and warmup policy is enforced.
VAL-BENCH-007: Statistical method is locked and reported.
VAL-BENCH-010: Order-bias controls are enforced.
VAL-BENCH-011: Outlier/retry policy is predeclared and auditable.

Tests verify:
  - Sampling policy file loads and passes schema validation.
  - Warmup iterations are enforced (min_count per cell).
  - Measured sample counts meet policy minimum.
  - Statistical method is locked and summary artifacts carry method IDs.
  - Execution schedule is interleaved-random with reproducible seed.
  - Outlier flagging follows predeclared IQR-fence policy.
  - No samples are silently dropped; filtered table has reason codes.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "benchmarks"))


# ---------------------------------------------------------------------------
# Policy file schema tests
# ---------------------------------------------------------------------------


class TestSamplingPolicySchema:
    """Verify sampling_policy.json is well-formed and complete."""

    @pytest.fixture(autouse=True)
    def load_policy(self):
        path = REPO_ROOT / "benchmarks" / "sampling_policy.json"
        assert path.exists(), "sampling_policy.json must exist"
        with open(path) as f:
            self.policy = json.load(f)

    def test_schema_version(self):
        assert self.policy["schema_version"] == 1

    def test_warmup_section_present(self):
        assert "warmup" in self.policy
        assert "default_count" in self.policy["warmup"]
        assert "min_count" in self.policy["warmup"]

    def test_sampling_section_present(self):
        assert "sampling" in self.policy
        assert "default_measured_samples" in self.policy["sampling"]
        assert "min_measured_samples" in self.policy["sampling"]

    def test_statistical_method_section_present(self):
        sm = self.policy["statistical_method"]
        assert "id" in sm
        assert "summary_metric" in sm
        assert "dispersion_metric" in sm
        assert "confidence_interval" in sm
        assert sm["confidence_interval"]["method"] == "percentile_bootstrap"
        assert sm["confidence_interval"]["level"] == 0.95

    def test_order_bias_section_present(self):
        ob = self.policy["order_bias"]
        assert "schedule" in ob
        assert ob["schedule"] == "interleaved_random"
        assert "seed_source" in ob

    def test_outlier_policy_section_present(self):
        op = self.policy["outlier_policy"]
        assert "method" in op
        assert op["method"] == "iqr_fence"
        assert "iqr_multiplier" in op
        assert "action" in op
        assert op["action"] == "flag"

    def test_claim_thresholds_section_present(self):
        ct = self.policy["claim_thresholds"]
        assert "min_speedup_ratio" in ct
        assert "required_run_types" in ct
        assert "parity_gate_required" in ct
        assert "reproducibility_gate_required" in ct

    def test_min_samples_gte_3(self):
        """Policy must require at least 3 measured samples."""
        assert self.policy["sampling"]["min_measured_samples"] >= 3

    def test_warmup_at_least_1(self):
        """Policy must require at least 1 warmup iteration."""
        assert self.policy["warmup"]["min_count"] >= 1


# ---------------------------------------------------------------------------
# validate_sampling tests (VAL-BENCH-006 / 007 / 010 / 011)
# ---------------------------------------------------------------------------


def _make_sampling_run_manifest(
    scenario_ids: list[str],
    comparators: list[str],
    samples_per_cell: int = 5,
    warmup_per_cell: int = 2,
    include_schedule: bool = True,
    schedule_seed: int | None = 42,
    outlier_flags: dict | None = None,
) -> dict:
    """Build a synthetic run manifest with sampling metadata."""
    scenarios = []
    schedule_entries = []
    iteration = 0

    for sid in scenario_ids:
        cell_results = {}
        for comp in comparators:
            raw_samples = []
            for i in range(warmup_per_cell + samples_per_cell):
                elapsed = 0.01 + i * 0.001
                raw_samples.append({
                    "iteration": i,
                    "warmup": i < warmup_per_cell,
                    "elapsed_s": round(elapsed, 6),
                })
                if include_schedule:
                    schedule_entries.append({
                        "global_iteration": iteration,
                        "scenario_id": sid,
                        "comparator": comp,
                        "warmup": i < warmup_per_cell,
                    })
                    iteration += 1

            measured = [s for s in raw_samples if not s["warmup"]]
            cell_results[comp] = {
                "command": f"{comp} pattern .",
                "exit_code": 0,
                "raw_samples": raw_samples,
                "measured_samples": measured,
                "warmup_count": warmup_per_cell,
                "measured_count": samples_per_cell,
                "stdout_hash": "abc123",
                "stdout_sorted_hash": "abc123",
                "stdout_bytes": 100,
                "stderr_excerpt": "",
                "timed_out": False,
                "error": None,
            }

            # Apply outlier flags if provided.
            if outlier_flags and (sid, comp) in outlier_flags:
                cell_results[comp]["outlier_flags"] = outlier_flags[(sid, comp)]

        scenarios.append({
            "scenario_id": sid,
            "query_id": f"q-{sid}",
            "pattern": "test",
            "corpus": ".",
            "commands": {c: f"{c} {{pattern}} {{corpus}}" for c in comparators},
            "results": cell_results,
            "skipped": False,
        })

    manifest = {
        "schema_version": 2,
        "run_id": "test-sampling-run",
        "run_type": "smoke",
        "timestamp": "2026-03-05T00:00:00+00:00",
        "commit_sha": "abc123",
        "comparators": comparators,
        "manifest_hashes": {
            "scenarios": "hash-s",
            "queries": "hash-q",
            "corpus": "hash-c",
        },
        "environment": {},
        "tools_metadata": {"comparators": {}},
        "scenario_count": len(scenarios),
        "cell_totals": {
            "total": len(scenario_ids) * len(comparators),
            "executed": len(scenario_ids) * len(comparators),
            "skipped": 0,
            "errors": 0,
        },
        "sampling_policy_hash": "",
        "scenarios": scenarios,
    }

    if include_schedule:
        manifest["execution_schedule"] = {
            "schedule": "interleaved_random",
            "seed": schedule_seed,
            "entries": schedule_entries,
        }

    return manifest


class TestValidateSamplingWarmup:
    """VAL-BENCH-006: Warmup/sample count enforcement."""

    def test_sufficient_warmup_passes(self, tmp_path):
        from validate_sampling import validate_sampling

        manifest = _make_sampling_run_manifest(
            ["s1"], ["ag", "rust-ag"], warmup_per_cell=2, samples_per_cell=5,
        )
        result = validate_sampling(manifest, tmp_path)
        assert result["warmup_check"]["result"] == "pass"

    def test_insufficient_warmup_fails(self, tmp_path):
        from validate_sampling import validate_sampling

        manifest = _make_sampling_run_manifest(
            ["s1"], ["ag", "rust-ag"], warmup_per_cell=0, samples_per_cell=5,
        )
        result = validate_sampling(manifest, tmp_path)
        assert result["warmup_check"]["result"] == "fail"

    def test_sufficient_samples_passes(self, tmp_path):
        from validate_sampling import validate_sampling

        manifest = _make_sampling_run_manifest(
            ["s1"], ["ag", "rust-ag"], warmup_per_cell=2, samples_per_cell=5,
        )
        result = validate_sampling(manifest, tmp_path)
        assert result["sample_count_check"]["result"] == "pass"

    def test_insufficient_samples_fails(self, tmp_path):
        from validate_sampling import validate_sampling

        manifest = _make_sampling_run_manifest(
            ["s1"], ["ag", "rust-ag"], warmup_per_cell=2, samples_per_cell=1,
        )
        result = validate_sampling(manifest, tmp_path)
        assert result["sample_count_check"]["result"] == "fail"


class TestValidateSamplingStatisticalMethod:
    """VAL-BENCH-007: Statistical method is locked and reported."""

    def test_method_id_in_artifact(self, tmp_path):
        from validate_sampling import validate_sampling

        manifest = _make_sampling_run_manifest(
            ["s1"], ["ag", "rust-ag"],
        )
        result = validate_sampling(manifest, tmp_path)
        assert "statistical_method" in result
        assert result["statistical_method"]["id"] == "median_iqr_ci"

    def test_summary_includes_uncertainty_intervals(self, tmp_path):
        from validate_sampling import validate_sampling

        manifest = _make_sampling_run_manifest(
            ["s1"], ["ag", "rust-ag"],
        )
        result = validate_sampling(manifest, tmp_path)
        for entry in result["scenario_summaries"]:
            for comp, stats in entry["comparator_stats"].items():
                assert "median_s" in stats
                assert "iqr_s" in stats
                assert "ci_lower_s" in stats
                assert "ci_upper_s" in stats
                assert "ci_level" in stats


class TestValidateSamplingOrderBias:
    """VAL-BENCH-010: Order-bias controls are enforced."""

    def test_schedule_present_passes(self, tmp_path):
        from validate_sampling import validate_sampling

        manifest = _make_sampling_run_manifest(
            ["s1"], ["ag", "rust-ag"], include_schedule=True,
        )
        result = validate_sampling(manifest, tmp_path)
        assert result["order_bias_check"]["result"] == "pass"

    def test_missing_schedule_fails(self, tmp_path):
        from validate_sampling import validate_sampling

        manifest = _make_sampling_run_manifest(
            ["s1"], ["ag", "rust-ag"], include_schedule=False,
        )
        result = validate_sampling(manifest, tmp_path)
        assert result["order_bias_check"]["result"] == "fail"

    def test_schedule_has_seed(self, tmp_path):
        from validate_sampling import validate_sampling

        manifest = _make_sampling_run_manifest(
            ["s1"], ["ag", "rust-ag"], include_schedule=True, schedule_seed=42,
        )
        result = validate_sampling(manifest, tmp_path)
        assert result["order_bias_check"]["seed"] is not None


class TestValidateSamplingOutlierPolicy:
    """VAL-BENCH-011: Outlier/retry policy is predeclared and auditable."""

    def test_outlier_audit_present(self, tmp_path):
        from validate_sampling import validate_sampling

        manifest = _make_sampling_run_manifest(
            ["s1"], ["ag", "rust-ag"],
        )
        result = validate_sampling(manifest, tmp_path)
        assert "outlier_audit" in result

    def test_outlier_policy_hash_recorded(self, tmp_path):
        from validate_sampling import validate_sampling

        manifest = _make_sampling_run_manifest(
            ["s1"], ["ag", "rust-ag"],
        )
        result = validate_sampling(manifest, tmp_path)
        assert result["outlier_audit"]["policy_hash"]

    def test_no_silent_drops(self, tmp_path):
        """All flagged outliers appear in the filtered table with reason codes."""
        from validate_sampling import validate_sampling

        outlier_flags = {
            ("s1", "ag"): [
                {"iteration": 4, "reason": "iqr_fence_high", "value_s": 0.099}
            ],
        }
        manifest = _make_sampling_run_manifest(
            ["s1"], ["ag", "rust-ag"],
            outlier_flags=outlier_flags,
        )
        result = validate_sampling(manifest, tmp_path)
        # The audit should record the flagged samples.
        flagged = result["outlier_audit"]["flagged_samples"]
        assert len(flagged) >= 1
        for f in flagged:
            assert "reason" in f
            assert "scenario_id" in f
            assert "comparator" in f

    def test_artifact_written(self, tmp_path):
        from validate_sampling import validate_sampling

        manifest = _make_sampling_run_manifest(
            ["s1"], ["ag", "rust-ag"],
        )
        validate_sampling(manifest, tmp_path)
        artifact = tmp_path / "sampling_validation.json"
        assert artifact.exists()


class TestValidateSamplingOverallGate:
    """Overall sampling validation gate pass/fail."""

    def test_all_good_passes(self, tmp_path):
        from validate_sampling import validate_sampling

        manifest = _make_sampling_run_manifest(
            ["s1", "s2"], ["ag", "rust-ag", "rg", "ugrep"],
            warmup_per_cell=2, samples_per_cell=5,
        )
        result = validate_sampling(manifest, tmp_path)
        assert result["gate"] == "pass"

    def test_bad_warmup_fails_gate(self, tmp_path):
        from validate_sampling import validate_sampling

        manifest = _make_sampling_run_manifest(
            ["s1"], ["ag", "rust-ag"],
            warmup_per_cell=0, samples_per_cell=5,
        )
        result = validate_sampling(manifest, tmp_path)
        assert result["gate"] == "fail"
