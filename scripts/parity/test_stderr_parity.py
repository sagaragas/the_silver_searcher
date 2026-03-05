#!/usr/bin/env python3
"""Tests for stderr parity checking in the parity runner.

Verifies that:
  - Stderr is captured and normalised for both baseline and target.
  - Stderr differences contribute to the parity verdict.
  - Stderr diff artifacts are written alongside stdout diffs.
  - The summary schema v2 includes stderr_match in comparison results.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Ensure the scripts/parity directory is importable.
SCRIPTS_PARITY = Path(__file__).resolve().parent
if str(SCRIPTS_PARITY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PARITY))

import run_matrix  # noqa: E402


class TestStderrNormalisation(unittest.TestCase):
    """Verify _normalise_output handles stderr-like content."""

    def test_empty_stderr(self):
        self.assertEqual(run_matrix._normalise_output(""), "")

    def test_stderr_with_ansi(self):
        """ANSI codes are stripped before comparison."""
        raw = "\x1b[31mERR: something\x1b[0m\n"
        norm = run_matrix._normalise_output(raw)
        self.assertNotIn("\x1b", norm)
        self.assertIn("ERR: something", norm)

    def test_stderr_lines_sorted(self):
        """Lines are sorted for stable comparison."""
        raw = "ERR: z message\nERR: a message\n"
        norm = run_matrix._normalise_output(raw)
        lines = norm.strip().split("\n")
        self.assertEqual(lines, sorted(lines))


class TestStderrDiff(unittest.TestCase):
    """Verify compute_diff works for stderr content."""

    def test_identical_stderr(self):
        diff = run_matrix.compute_diff("ERR: foo\n", "ERR: foo\n")
        self.assertEqual(diff, "")

    def test_different_stderr(self):
        diff = run_matrix.compute_diff("ERR: foo\n", "ERR: bar\n")
        self.assertIn("---", diff)
        self.assertIn("+++", diff)


class TestStderrParityVerdict(unittest.TestCase):
    """Verify stderr contributes to the pass/fail parity verdict."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="parity-stderr-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_run_result(self, stdout="", stderr="", exit_code=0):
        """Create a minimal run_command-style result dict."""
        return {
            "command": "test-cmd",
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "elapsed_s": 0.01,
            "timed_out": False,
        }

    @mock.patch("run_matrix.run_command")
    @mock.patch("run_matrix._resolve_binary")
    @mock.patch("run_matrix._git_sha", return_value="abc123")
    @mock.patch("run_matrix._preflight_edge_fixtures")
    def test_stderr_match_pass(self, _pf, _sha, _resolve, mock_run):
        """When stdout, stderr, and exit code all match → parity pass."""
        _resolve.return_value = "/usr/bin/true"
        mock_run.return_value = self._make_run_result(
            stdout="match\n", stderr="", exit_code=0
        )
        summary = run_matrix.run_matrix(
            targets=["rust-ag"],
            scenario_ids=["literal-simple"],
            group=None,
            run_dir=self.tmpdir / "run1",
        )
        for sc in summary["scenarios"]:
            for tname, tres in sc.get("targets", {}).items():
                if tname == "ag":
                    continue
                self.assertEqual(tres["parity"], "pass")
                self.assertTrue(tres["stderr_match"])
                self.assertTrue(tres["output_match"])
                self.assertTrue(tres["exit_code_match"])

    @mock.patch("run_matrix.run_command")
    @mock.patch("run_matrix._resolve_binary")
    @mock.patch("run_matrix._git_sha", return_value="abc123")
    @mock.patch("run_matrix._preflight_edge_fixtures")
    def test_stderr_mismatch_fail(self, _pf, _sha, _resolve, mock_run):
        """When stderr differs but stdout and exit match → parity fail."""
        _resolve.return_value = "/usr/bin/true"
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            # First call is always baseline (ag), second is target.
            if call_count[0] % 2 == 1:
                return self._make_run_result(
                    stdout="match\n", stderr="ERR: baseline msg\n", exit_code=0
                )
            else:
                return self._make_run_result(
                    stdout="match\n", stderr="ERR: different msg\n", exit_code=0
                )

        mock_run.side_effect = side_effect
        summary = run_matrix.run_matrix(
            targets=["rust-ag"],
            scenario_ids=["literal-simple"],
            group=None,
            run_dir=self.tmpdir / "run2",
        )
        for sc in summary["scenarios"]:
            for tname, tres in sc.get("targets", {}).items():
                if tname == "ag":
                    continue
                self.assertEqual(tres["parity"], "fail")
                self.assertFalse(tres["stderr_match"])
                self.assertTrue(tres["output_match"])
                self.assertTrue(tres["exit_code_match"])

    @mock.patch("run_matrix.run_command")
    @mock.patch("run_matrix._resolve_binary")
    @mock.patch("run_matrix._git_sha", return_value="abc123")
    @mock.patch("run_matrix._preflight_edge_fixtures")
    def test_stderr_diff_artifact_written(self, _pf, _sha, _resolve, mock_run):
        """Stderr diff file is written for each target comparison."""
        _resolve.return_value = "/usr/bin/true"
        mock_run.return_value = self._make_run_result(
            stdout="match\n", stderr="", exit_code=0
        )
        run_dir = self.tmpdir / "run3"
        run_matrix.run_matrix(
            targets=["rust-ag"],
            scenario_ids=["literal-simple"],
            group=None,
            run_dir=run_dir,
        )
        # Check that stderr.diff artifact exists.
        scenario_dir = run_dir / "scenarios" / "literal-simple"
        stderr_diff = scenario_dir / "rust-ag.stderr.diff"
        self.assertTrue(
            stderr_diff.is_file(),
            f"Expected stderr diff artifact at {stderr_diff}",
        )

    @mock.patch("run_matrix.run_command")
    @mock.patch("run_matrix._resolve_binary")
    @mock.patch("run_matrix._git_sha", return_value="abc123")
    @mock.patch("run_matrix._preflight_edge_fixtures")
    def test_schema_version_is_2(self, _pf, _sha, _resolve, mock_run):
        """Summary schema version is 2 with stderr parity enforcement."""
        _resolve.return_value = "/usr/bin/true"
        mock_run.return_value = self._make_run_result(
            stdout="match\n", stderr="", exit_code=0
        )
        summary = run_matrix.run_matrix(
            targets=["rust-ag"],
            scenario_ids=["literal-simple"],
            group=None,
            run_dir=self.tmpdir / "run4",
        )
        self.assertEqual(summary["schema_version"], 2)


class TestStderrInValidateOutputs(unittest.TestCase):
    """Verify validate_outputs.py requires stderr artifacts for v2 runs."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="parity-val-stderr-"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_json(self, path, obj):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(obj, f)

    def _write_text(self, path, text=""):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def _build_minimal_run_dir(self, schema_version=2, include_stderr_match=True,
                                include_stderr_diff=True):
        """Build a minimal valid run directory for validation testing."""
        run_dir = self.tmpdir / "test-run"
        run_dir.mkdir(parents=True, exist_ok=True)

        # Environment.
        self._write_json(run_dir / "environment.json", {
            "timestamp": "2026-03-05T12:00:00+00:00",
            "platform": {"system": "Darwin", "release": "25.0", "machine": "arm64", "python": "3.14"},
            "commit_sha": "abc123",
            "tools": {"ag": {"path": "/usr/bin/ag", "version": "2.0"}},
            "manifest_hashes": {"scenarios": "aaa", "queries": "bbb", "corpus": "ccc"},
        })

        # Target result.
        target_result = {
            "command": "rust-ag test",
            "exit_code": 0,
            "elapsed_s": 0.01,
            "timed_out": False,
            "parity": "pass",
            "exit_code_match": True,
            "output_match": True,
            "diff_lines": 0,
        }
        if include_stderr_match:
            target_result["stderr_match"] = True
            target_result["stderr_diff_lines"] = 0

        # Summary.
        self._write_json(run_dir / "summary.json", {
            "schema_version": schema_version,
            "run_id": "test-run",
            "timestamp": "2026-03-05T12:00:00+00:00",
            "commit_sha": "abc123",
            "targets": ["rust-ag"],
            "group": "smoke",
            "scenario_count": 1,
            "manifest_hashes": {"scenarios": "aaa", "queries": "bbb", "corpus": "ccc"},
            "totals": {"pass": 1, "fail": 0, "error": 0},
            "scenarios": [{
                "scenario_id": "test-scenario",
                "query_id": "q1",
                "pattern": "test",
                "corpus": "tests/fixtures",
                "baseline": {"command": "ag test", "exit_code": 0, "elapsed_s": 0.01, "timed_out": False},
                "targets": {"rust-ag": target_result},
            }],
        })

        # Scenario artifacts.
        sc_dir = run_dir / "scenarios" / "test-scenario"
        for prefix in ["baseline"]:
            self._write_text(sc_dir / f"{prefix}.stdout", "match\n")
            self._write_text(sc_dir / f"{prefix}.stderr", "")
            self._write_text(sc_dir / f"{prefix}.norm", "match\n")
            self._write_json(sc_dir / f"{prefix}.meta.json", {
                "command": "ag test", "exit_code": 0, "elapsed_s": 0.01,
                "timed_out": False, "stdout_sha256": "aaa", "norm_sha256": "bbb",
            })
        # Target artifacts.
        self._write_text(sc_dir / "rust-ag.stdout", "match\n")
        self._write_text(sc_dir / "rust-ag.stderr", "")
        self._write_text(sc_dir / "rust-ag.norm", "match\n")
        self._write_json(sc_dir / "rust-ag.meta.json", {
            "command": "rust-ag test", "exit_code": 0, "elapsed_s": 0.01,
            "timed_out": False, "stdout_sha256": "aaa", "norm_sha256": "bbb",
        })
        self._write_text(sc_dir / "rust-ag.diff", "")
        if include_stderr_diff:
            self._write_text(sc_dir / "rust-ag.stderr.diff", "")

        return run_dir

    def test_v2_with_all_stderr_artifacts_passes(self):
        """Complete v2 run with stderr_match and stderr.diff passes validation."""
        import validate_outputs  # noqa: E402
        run_dir = self._build_minimal_run_dir(schema_version=2)
        vr = validate_outputs.validate_run(run_dir)
        self.assertTrue(vr.passed, f"Expected pass, got errors: {vr.errors}")

    def test_v2_missing_stderr_match_field_fails(self):
        """v2 run missing stderr_match in comparison result fails validation."""
        import validate_outputs  # noqa: E402
        run_dir = self._build_minimal_run_dir(
            schema_version=2, include_stderr_match=False
        )
        vr = validate_outputs.validate_run(run_dir)
        stderr_errors = [e for e in vr.errors if "stderr_match_recorded" in e]
        self.assertTrue(
            len(stderr_errors) > 0,
            f"Expected stderr_match validation error, got: {vr.errors}",
        )

    def test_v1_without_stderr_match_passes(self):
        """v1 schema runs without stderr_match still pass validation."""
        import validate_outputs  # noqa: E402
        run_dir = self._build_minimal_run_dir(
            schema_version=1, include_stderr_match=False, include_stderr_diff=False
        )
        vr = validate_outputs.validate_run(run_dir)
        stderr_errors = [e for e in vr.errors if "stderr_match_recorded" in e]
        self.assertEqual(
            len(stderr_errors), 0,
            f"v1 schema should not require stderr_match, got: {stderr_errors}",
        )

    def test_v1_without_stderr_artifacts_passes_overall(self):
        """v1 run lacking stderr.diff artifacts passes validation overall.

        Schema v1 runs were produced before stderr parity enforcement was
        added.  The validator must not require stderr diff artifacts for
        these runs so legacy run directories remain valid.
        """
        import validate_outputs  # noqa: E402
        run_dir = self._build_minimal_run_dir(
            schema_version=1, include_stderr_match=False, include_stderr_diff=False
        )
        vr = validate_outputs.validate_run(run_dir)
        self.assertTrue(
            vr.passed,
            f"v1 run without stderr artifacts should pass overall, got errors: {vr.errors}",
        )

    def test_v2_missing_stderr_diff_artifact_fails(self):
        """v2 run missing stderr.diff artifact file fails artifact check."""
        import validate_outputs  # noqa: E402
        run_dir = self._build_minimal_run_dir(
            schema_version=2, include_stderr_diff=False
        )
        vr = validate_outputs.validate_run(run_dir)
        artifact_errors = [e for e in vr.errors if "stderr.diff" in e]
        self.assertTrue(
            len(artifact_errors) > 0,
            f"Expected stderr.diff artifact error, got: {vr.errors}",
        )

    def test_v2_with_stderr_diff_passes_overall(self):
        """v2 run with all stderr artifacts passes validation overall."""
        import validate_outputs  # noqa: E402
        run_dir = self._build_minimal_run_dir(
            schema_version=2, include_stderr_match=True, include_stderr_diff=True
        )
        vr = validate_outputs.validate_run(run_dir)
        self.assertTrue(
            vr.passed,
            f"v2 run with complete stderr artifacts should pass, got errors: {vr.errors}",
        )

    def test_v3_requires_stderr_diff_artifacts(self):
        """Future schema v3+ still requires stderr diff artifacts."""
        import validate_outputs  # noqa: E402
        run_dir = self._build_minimal_run_dir(
            schema_version=3, include_stderr_match=True, include_stderr_diff=False
        )
        vr = validate_outputs.validate_run(run_dir)
        artifact_errors = [e for e in vr.errors if "stderr.diff" in e]
        self.assertTrue(
            len(artifact_errors) > 0,
            f"v3 run should require stderr.diff artifacts, got: {vr.errors}",
        )


if __name__ == "__main__":
    unittest.main()
