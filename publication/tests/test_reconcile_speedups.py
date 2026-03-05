#!/usr/bin/env python3
"""Tests for speedup claim reconciliation in reconcile_metrics.py.

Validates that:
  - Narrative speedup claims (e.g., "approximately 2.0× speedup") are
    numerically validated against benchmark-derived ratios.
  - Speedup table claims (Table 2.2d) are validated against claim_gate.json.
  - Reconciliation fails when speedup claims exceed configured tolerance.
  - reconciliation_report.json includes explicit speedup-claim pass/fail
    evidence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "publication"))

from reconcile_metrics import (
    extract_memo_speedup_table_values,
    extract_memo_speedup_values,
    reconcile_speedup_table,
    reconcile_speedups,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_run_stats(ag_ms: float, rust_ms: float, rg_ms: float, ugrep_ms: float) -> dict:
    """Build a minimal run_stats dict for the literal-simple scenario."""
    return {
        "literal-simple": {
            "ag": {"median_ms": ag_ms, "iqr_ms": 0.3, "n": 3},
            "rust-ag": {"median_ms": rust_ms, "iqr_ms": 0.2, "n": 3},
            "rg": {"median_ms": rg_ms, "iqr_ms": 0.4, "n": 3},
            "ugrep": {"median_ms": ugrep_ms, "iqr_ms": 0.1, "n": 3},
        }
    }


def _make_claim_gate(pairs: list[dict]) -> dict:
    """Build a minimal claim_gate dict with pair evaluations."""
    return {
        "scenario_claims": [
            {
                "scenario_id": "literal-simple",
                "pair_evaluations": pairs,
            }
        ]
    }


def _make_pair_eval(
    faster: str,
    slower: str,
    local_ratio: float,
    nightly_ratio: float,
    manual_ratio: float,
) -> dict:
    return {
        "faster": faster,
        "slower": slower,
        "speedup_ratio": local_ratio,
        "per_run_type_results": {
            "local": {"speedup_ratio": local_ratio, "result": "pass"},
            "nightly": {"speedup_ratio": nightly_ratio, "result": "pass"},
            "manual": {"speedup_ratio": manual_ratio, "result": "pass"},
        },
    }


# ---------------------------------------------------------------------------
# Tests: extract_memo_speedup_values
# ---------------------------------------------------------------------------


class TestExtractMemoSpeedupValues:
    def test_extracts_approximate_claims(self):
        memo = "The Rust rewrite achieved approximately 2.0× speedup."
        result = extract_memo_speedup_values(memo)
        assert len(result) == 1
        assert result[0]["ratio"] == 2.0

    def test_extracts_faster_than_pattern(self):
        memo = "rg was approximately 2.5× faster than ag."
        result = extract_memo_speedup_values(memo)
        assert len(result) == 1
        assert result[0]["ratio"] == 2.5

    def test_extracts_tool_pair_from_vs_pattern(self):
        memo = "**rust-ag vs ag**: approximately 2.0× speedup."
        result = extract_memo_speedup_values(memo)
        assert len(result) == 1
        assert result[0]["faster"] == "rust-ag"
        assert result[0]["slower"] == "ag"

    def test_extracts_tool_pair_from_is_faster_than(self):
        memo = "- **rg is 1.25× faster than rust-ag** (local median)."
        result = extract_memo_speedup_values(memo)
        assert len(result) == 1
        assert result[0]["faster"] == "rg"
        assert result[0]["slower"] == "rust-ag"

    def test_extracts_claim_evidence_table_rows(self):
        memo = "| CLM-PERF-001 | §2.2 | rust-ag ≈2.0× faster than ag |"
        result = extract_memo_speedup_values(memo)
        assert len(result) == 1
        assert result[0]["ratio"] == 2.0
        assert result[0]["faster"] == "rust-ag"
        assert result[0]["slower"] == "ag"

    def test_extracts_speedup_over_phrasing(self):
        memo = "While rust-ag achieved a 2.0× speedup over the original ag, it is"
        result = extract_memo_speedup_values(memo)
        assert len(result) == 1
        assert result[0]["ratio"] == 2.0
        assert result[0]["faster"] == "rust-ag"
        assert result[0]["slower"] == "ag"

    def test_extracts_speedup_over_simple(self):
        memo = "rg showed a 2.5× speedup over ag in this scenario."
        result = extract_memo_speedup_values(memo)
        assert len(result) == 1
        assert result[0]["ratio"] == 2.5
        assert result[0]["faster"] == "rg"
        assert result[0]["slower"] == "ag"

    def test_speedup_over_non_tool_words_no_pair(self):
        """Claims with 'speedup over' but no recognisable tool names should
        still extract the ratio but leave the pair unresolved."""
        memo = "We measured a 3.0× speedup over the baseline implementation."
        result = extract_memo_speedup_values(memo)
        assert len(result) == 1
        assert result[0]["ratio"] == 3.0
        assert result[0]["faster"] is None
        assert result[0]["slower"] is None

    def test_multiple_claims_per_line(self):
        # Shouldn't happen in practice, but test robustness
        memo = "Gains are 2.0× speedup and 3.0× speedup."
        result = extract_memo_speedup_values(memo)
        assert len(result) == 2

    def test_records_line_number(self):
        memo = "Line one.\nLine two 2.0× faster.\nLine three."
        result = extract_memo_speedup_values(memo)
        assert len(result) == 1
        assert result[0]["line_num"] == 2


# ---------------------------------------------------------------------------
# Tests: extract_memo_speedup_table_values
# ---------------------------------------------------------------------------


class TestExtractMemoSpeedupTableValues:
    def test_parses_speedup_table_row(self):
        memo = "| rg | ag | 2.54× | 2.45× | 2.48× | 0.0 | ✓ |"
        result = extract_memo_speedup_table_values(memo)
        assert len(result) == 1
        assert result[0]["faster"] == "rg"
        assert result[0]["slower"] == "ag"
        assert result[0]["local_ratio"] == 2.54
        assert result[0]["nightly_ratio"] == 2.45
        assert result[0]["manual_ratio"] == 2.48
        assert result[0]["ci_overlap"] == 0.0

    def test_skips_header_row(self):
        memo = "| Faster | Slower | Local Speedup | Nightly Speedup | Manual Speedup | CI Overlap | Claim Allowed |"
        result = extract_memo_speedup_table_values(memo)
        assert len(result) == 0

    def test_parses_multiple_rows(self):
        memo = (
            "| rg | ag | 2.54× | 2.45× | 2.48× | 0.0 | ✓ |\n"
            "| rust-ag | ag | 2.03× | 1.96× | 1.96× | 0.0 | ✓ |"
        )
        result = extract_memo_speedup_table_values(memo)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Tests: reconcile_speedups (narrative claims)
# ---------------------------------------------------------------------------


class TestReconcileSpeedups:
    def test_correct_claims_pass(self):
        """Correct narrative speedup claims should pass within tolerance."""
        # ag=19.64 ms, rust-ag=9.69 ms -> ratio ~2.027
        stats = _make_run_stats(19.64, 9.69, 7.74, 4.02)
        claims = [
            {
                "ratio": 2.0,
                "faster": "rust-ag",
                "slower": "ag",
                "line_num": 1,
                "context": "approximately 2.0× speedup",
            }
        ]
        errors, evidence, ok_count = reconcile_speedups(
            claims, {"local": stats}, "literal-simple", tolerance=0.15
        )
        assert len(errors) == 0
        assert ok_count == 1
        assert evidence[0]["result"] == "pass"
        assert evidence[0]["computed_ratio"] is not None

    def test_incorrect_claim_fails(self):
        """A speedup claim that exceeds tolerance should fail."""
        stats = _make_run_stats(19.64, 9.69, 7.74, 4.02)
        claims = [
            {
                "ratio": 5.0,  # Wildly incorrect
                "faster": "rust-ag",
                "slower": "ag",
                "line_num": 42,
                "context": "approximately 5.0× speedup",
            }
        ]
        errors, evidence, ok_count = reconcile_speedups(
            claims, {"local": stats}, "literal-simple", tolerance=0.15
        )
        assert len(errors) > 0
        assert ok_count == 0
        assert evidence[0]["result"] == "fail"
        assert "5.0" in errors[0]

    def test_borderline_claim_within_tolerance(self):
        """A claim exactly at the tolerance boundary should pass."""
        # ag=20, rust-ag=10 -> ratio 2.0
        stats = _make_run_stats(20.0, 10.0, 8.0, 4.0)
        claims = [
            {
                "ratio": 2.15,  # diff = 0.15, exactly at tolerance
                "faster": "rust-ag",
                "slower": "ag",
                "line_num": 1,
                "context": "test",
            }
        ]
        errors, evidence, ok_count = reconcile_speedups(
            claims, {"local": stats}, "literal-simple", tolerance=0.15
        )
        assert len(errors) == 0
        assert ok_count == 1

    def test_borderline_claim_exceeds_tolerance(self):
        """A claim just beyond the tolerance boundary should fail."""
        # ag=20, rust-ag=10 -> ratio 2.0
        stats = _make_run_stats(20.0, 10.0, 8.0, 4.0)
        claims = [
            {
                "ratio": 2.16,  # diff = 0.16, exceeds 0.15 tolerance
                "faster": "rust-ag",
                "slower": "ag",
                "line_num": 1,
                "context": "test",
            }
        ]
        errors, evidence, ok_count = reconcile_speedups(
            claims, {"local": stats}, "literal-simple", tolerance=0.15
        )
        assert len(errors) > 0
        assert ok_count == 0

    def test_unidentified_pair_is_failure(self):
        """Claims without identified tool pairs are treated as failures, not skipped."""
        stats = _make_run_stats(19.64, 9.69, 7.74, 4.02)
        claims = [
            {
                "ratio": 2.0,
                "faster": None,
                "slower": None,
                "line_num": 1,
                "context": "some vague claim",
            }
        ]
        errors, evidence, ok_count = reconcile_speedups(
            claims, {"local": stats}, "literal-simple", tolerance=0.15
        )
        assert len(errors) > 0
        assert ok_count == 0
        assert evidence[0]["result"] == "fail"

    def test_missing_benchmark_pair_is_failure(self):
        """Claims with pair identified but no matching benchmark data should fail."""
        stats = _make_run_stats(19.64, 9.69, 7.74, 4.02)
        claims = [
            {
                "ratio": 2.0,
                "faster": "rust-ag",
                "slower": "unknown-tool",
                "line_num": 1,
                "context": "some claim referencing unknown tool",
            }
        ]
        errors, evidence, ok_count = reconcile_speedups(
            claims, {"local": stats}, "literal-simple", tolerance=0.15
        )
        assert len(errors) > 0
        assert ok_count == 0
        assert evidence[0]["result"] == "fail"

    def test_missing_scenario_returns_error(self):
        """Missing scenario in run data should produce an error."""
        stats = {"other-scenario": {}}
        claims = [
            {
                "ratio": 2.0,
                "faster": "rust-ag",
                "slower": "ag",
                "line_num": 1,
                "context": "test",
            }
        ]
        errors, evidence, ok_count = reconcile_speedups(
            claims, {"local": stats}, "literal-simple", tolerance=0.15
        )
        assert len(errors) > 0

    def test_multiple_claims_mixed_results(self):
        """Multiple claims with mixed pass/fail results."""
        stats = _make_run_stats(19.64, 9.69, 7.74, 4.02)
        claims = [
            {
                "ratio": 2.0,
                "faster": "rust-ag",
                "slower": "ag",
                "line_num": 1,
                "context": "correct claim",
            },
            {
                "ratio": 9.0,  # Wrong
                "faster": "rg",
                "slower": "ag",
                "line_num": 2,
                "context": "incorrect claim",
            },
        ]
        errors, evidence, ok_count = reconcile_speedups(
            claims, {"local": stats}, "literal-simple", tolerance=0.15
        )
        assert ok_count == 1
        assert len(errors) > 0
        pass_evs = [e for e in evidence if e["result"] == "pass"]
        fail_evs = [e for e in evidence if e["result"] == "fail"]
        assert len(pass_evs) == 1
        assert len(fail_evs) == 1

    def test_custom_tolerance(self):
        """A tighter tolerance catches smaller diffs."""
        # ag=20, rust-ag=10 -> ratio 2.0
        stats = _make_run_stats(20.0, 10.0, 8.0, 4.0)
        claims = [
            {
                "ratio": 2.05,  # diff = 0.05
                "faster": "rust-ag",
                "slower": "ag",
                "line_num": 1,
                "context": "test",
            }
        ]
        # Passes with default tolerance (0.15)
        errors, _, ok_count = reconcile_speedups(
            claims, {"local": stats}, "literal-simple", tolerance=0.15
        )
        assert ok_count == 1
        assert len(errors) == 0

        # Fails with tight tolerance (0.01)
        errors, _, ok_count = reconcile_speedups(
            claims, {"local": stats}, "literal-simple", tolerance=0.01
        )
        assert ok_count == 0
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# Tests: reconcile_speedup_table (Table 2.2d)
# ---------------------------------------------------------------------------


class TestReconcileSpeedupTable:
    def test_correct_table_passes(self):
        """Correctly rounded speedup table values should pass."""
        gate = _make_claim_gate([
            _make_pair_eval("rg", "ag", 2.539, 2.4547, 2.4834),
        ])
        table_values = [
            {
                "faster": "rg",
                "slower": "ag",
                "local_ratio": 2.54,
                "nightly_ratio": 2.45,
                "manual_ratio": 2.48,
                "ci_overlap": 0.0,
                "line_num": 10,
            }
        ]
        errors, evidence, ok_count = reconcile_speedup_table(table_values, gate)
        assert len(errors) == 0
        assert ok_count == 3  # 3 run types checked
        assert all(e["result"] == "pass" for e in evidence)

    def test_incorrect_table_ratio_fails(self):
        """Table value that doesn't match gate ratio should fail."""
        gate = _make_claim_gate([
            _make_pair_eval("rg", "ag", 2.539, 2.4547, 2.4834),
        ])
        table_values = [
            {
                "faster": "rg",
                "slower": "ag",
                "local_ratio": 3.50,  # Wrong!
                "nightly_ratio": 2.45,
                "manual_ratio": 2.48,
                "ci_overlap": 0.0,
                "line_num": 10,
            }
        ]
        errors, evidence, ok_count = reconcile_speedup_table(table_values, gate)
        assert len(errors) > 0
        fail_evs = [e for e in evidence if e["result"] == "fail"]
        assert len(fail_evs) == 1
        assert fail_evs[0]["run_type"] == "local"

    def test_missing_pair_in_gate_fails(self):
        """Table pair not found in claim_gate should fail."""
        gate = _make_claim_gate([])  # No pairs
        table_values = [
            {
                "faster": "rg",
                "slower": "ag",
                "local_ratio": 2.54,
                "nightly_ratio": 2.45,
                "manual_ratio": 2.48,
                "ci_overlap": 0.0,
                "line_num": 10,
            }
        ]
        errors, evidence, ok_count = reconcile_speedup_table(table_values, gate)
        assert len(errors) > 0
        assert ok_count == 0

    def test_no_claim_gate_with_table_values_fails(self):
        """Table values without claim_gate.json should produce errors."""
        table_values = [
            {
                "faster": "rg",
                "slower": "ag",
                "local_ratio": 2.54,
                "nightly_ratio": 2.45,
                "manual_ratio": 2.48,
                "ci_overlap": 0.0,
                "line_num": 10,
            }
        ]
        errors, evidence, ok_count = reconcile_speedup_table(table_values, None)
        assert len(errors) > 0

    def test_no_claim_gate_no_table_values_passes(self):
        """Empty table with no claim_gate is fine."""
        errors, evidence, ok_count = reconcile_speedup_table([], None)
        assert len(errors) == 0

    def test_multiple_pairs(self):
        """Multiple pairs should all be validated."""
        gate = _make_claim_gate([
            _make_pair_eval("rg", "ag", 2.539, 2.4547, 2.4834),
            _make_pair_eval("rust-ag", "ag", 2.0272, 1.9596, 1.9624),
        ])
        table_values = [
            {
                "faster": "rg",
                "slower": "ag",
                "local_ratio": 2.54,
                "nightly_ratio": 2.45,
                "manual_ratio": 2.48,
                "ci_overlap": 0.0,
                "line_num": 10,
            },
            {
                "faster": "rust-ag",
                "slower": "ag",
                "local_ratio": 2.03,
                "nightly_ratio": 1.96,
                "manual_ratio": 1.96,
                "ci_overlap": 0.0,
                "line_num": 11,
            },
        ]
        errors, evidence, ok_count = reconcile_speedup_table(table_values, gate)
        assert len(errors) == 0
        assert ok_count == 6  # 2 pairs × 3 run types


# ---------------------------------------------------------------------------
# Tests: End-to-end reconciliation on live data
# ---------------------------------------------------------------------------


class TestEndToEndReconciliation:
    """Integration tests using actual repository data (if available)."""

    @pytest.fixture
    def repo_data_available(self):
        """Check if benchmark data is available for integration tests."""
        claim_map_path = REPO_ROOT / "publication" / "claim_evidence_map.json"
        memo_path = REPO_ROOT / "publication" / "ragas_blog_memo.md"
        if not claim_map_path.exists() or not memo_path.exists():
            pytest.skip("Repository benchmark data not available")
        return True

    def test_live_memo_speedup_extraction(self, repo_data_available):
        """Extract speedup claims from the actual memo."""
        memo_text = (REPO_ROOT / "publication" / "ragas_blog_memo.md").read_text()
        speedups = extract_memo_speedup_values(memo_text)
        assert len(speedups) > 0
        # At least some should have identified tool pairs
        paired = [s for s in speedups if s["faster"] and s["slower"]]
        assert len(paired) > 0

    def test_live_memo_speedup_table_extraction(self, repo_data_available):
        """Extract speedup table rows from the actual memo."""
        memo_text = (REPO_ROOT / "publication" / "ragas_blog_memo.md").read_text()
        table_values = extract_memo_speedup_table_values(memo_text)
        assert len(table_values) == 6  # 6 pairs in Table 2.2d

    def test_live_reconciliation_passes(self, repo_data_available):
        """Run reconciliation against actual benchmark data and verify pass."""
        memo_text = (REPO_ROOT / "publication" / "ragas_blog_memo.md").read_text()
        speedups = extract_memo_speedup_values(memo_text)

        with open(REPO_ROOT / "publication" / "claim_evidence_map.json") as f:
            claim_map = json.load(f)

        # Build run stats from each measured run
        run_stats_by_type = {}
        for run_type, run_id in claim_map.get("benchmark_run_ids", {}).items():
            run_dir = REPO_ROOT / "benchmarks" / "out" / run_id
            if not run_dir.exists():
                continue
            sv_path = run_dir / "sampling_validation.json"
            if not sv_path.exists():
                continue
            with open(sv_path) as f:
                sv = json.load(f)
            stats = {}
            for ss in sv.get("scenario_summaries", []):
                sid = ss.get("scenario_id")
                stats[sid] = {}
                for comp, cs in ss.get("comparator_stats", {}).items():
                    stats[sid][comp] = {
                        "median_ms": round(cs.get("median_s", 0) * 1000, 2),
                        "iqr_ms": round(cs.get("iqr_s", 0) * 1000, 2),
                        "n": cs.get("measured_count", 0),
                    }
            run_stats_by_type[run_type] = stats

        if not run_stats_by_type:
            pytest.skip("No measured run data found")

        errors, evidence, ok_count = reconcile_speedups(
            speedups, run_stats_by_type, "literal-simple"
        )
        assert len(errors) == 0, f"Reconciliation errors: {errors}"
        assert ok_count > 0


# ---------------------------------------------------------------------------
# Tests: Report persistence and failure evidence
# ---------------------------------------------------------------------------


class TestReportPersistence:
    """Tests that reconciliation_report.json is always written, even on failure."""

    @pytest.fixture
    def repo_data_available(self):
        """Check if benchmark data is available for integration tests."""
        claim_map_path = REPO_ROOT / "publication" / "claim_evidence_map.json"
        memo_path = REPO_ROOT / "publication" / "ragas_blog_memo.md"
        if not claim_map_path.exists() or not memo_path.exists():
            pytest.skip("Repository benchmark data not available")
        return True

    def test_report_written_on_pass(self, repo_data_available, tmp_path):
        """Report should be written when reconciliation passes."""
        import subprocess

        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "publication" / "reconcile_metrics.py"),
                "--memo",
                str(REPO_ROOT / "publication" / "ragas_blog_memo.md"),
                "--summary",
                str(REPO_ROOT / "benchmarks" / "out" / "latest" / "summary.json"),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        report_path = REPO_ROOT / "publication" / "reconciliation_report.json"
        assert report_path.exists(), "reconciliation_report.json should exist after pass"
        report = json.loads(report_path.read_text())
        assert "result" in report

    def test_report_written_on_fail(self, repo_data_available, tmp_path):
        """Report should be written even when reconciliation fails (e.g.,
        with --speedup-tolerance 0, so any small diff triggers failure)."""
        import subprocess

        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "publication" / "reconcile_metrics.py"),
                "--memo",
                str(REPO_ROOT / "publication" / "ragas_blog_memo.md"),
                "--summary",
                str(REPO_ROOT / "benchmarks" / "out" / "latest" / "summary.json"),
                "--speedup-tolerance",
                "0",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        # With tolerance=0, almost certainly some claims fail
        report_path = REPO_ROOT / "publication" / "reconciliation_report.json"
        assert report_path.exists(), "reconciliation_report.json should exist after fail"
        report = json.loads(report_path.read_text())
        assert report["result"] == "fail"
        assert "speedup_claim_reconciliation" in report
        # Evidence should include failure diagnostics
        sc = report["speedup_claim_reconciliation"]
        assert "narrative_claims" in sc
        assert "evidence" in sc["narrative_claims"]

    def test_fail_report_includes_speedup_failure_evidence(self, repo_data_available):
        """Failed reconciliation reports should include explicit speedup-claim
        failure evidence and diagnostics suitable for publication review."""
        import subprocess

        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "publication" / "reconcile_metrics.py"),
                "--memo",
                str(REPO_ROOT / "publication" / "ragas_blog_memo.md"),
                "--summary",
                str(REPO_ROOT / "benchmarks" / "out" / "latest" / "summary.json"),
                "--speedup-tolerance",
                "0",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        report_path = REPO_ROOT / "publication" / "reconciliation_report.json"
        assert report_path.exists()
        report = json.loads(report_path.read_text())
        if report["result"] == "fail":
            sc = report["speedup_claim_reconciliation"]
            # Check that failure evidence is diagnostic
            for ev in sc["narrative_claims"]["evidence"]:
                if ev["result"] == "fail":
                    assert "memo_ratio" in ev
                    assert "computed_ratio" in ev
                    assert "diff" in ev
                    assert "tolerance" in ev
                    assert "context" in ev
