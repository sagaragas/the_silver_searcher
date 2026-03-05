#!/usr/bin/env python3
"""Tests for required edge scenario ID enforcement (coverage shrinkage gate).

Verifies that:
  - validate_fixture_integrity.py detects missing required edge scenario IDs.
  - build_scenario_manifest.py --verify detects missing required edge scenario IDs.
  - All required IDs are actually present in the current SCENARIOS list.
  - Required set stays in sync across both validators.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure the script directories are importable.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "parity"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "bench"))


class TestRequiredEdgeScenarioIDsIntegrity(unittest.TestCase):
    """Verify the REQUIRED_EDGE_SCENARIO_IDS constant is consistent."""

    def test_integrity_validator_required_ids_match_scenario_manifest(self):
        """REQUIRED_EDGE_SCENARIO_IDS in validate_fixture_integrity.py must
        match the edge scenario IDs actually defined in SCENARIOS."""
        from validate_fixture_integrity import REQUIRED_EDGE_SCENARIO_IDS
        from build_scenario_manifest import SCENARIOS

        present = {s["id"] for s in SCENARIOS if s["id"].startswith("edge-")}
        self.assertEqual(
            REQUIRED_EDGE_SCENARIO_IDS,
            present,
            "REQUIRED_EDGE_SCENARIO_IDS in validate_fixture_integrity.py "
            "does not match edge scenarios in build_scenario_manifest.SCENARIOS",
        )

    def test_scenario_manifest_required_ids_match_scenario_list(self):
        """REQUIRED_EDGE_SCENARIO_IDS in build_scenario_manifest.py must
        match the edge scenario IDs actually defined in SCENARIOS."""
        from build_scenario_manifest import REQUIRED_EDGE_SCENARIO_IDS, SCENARIOS

        present = {s["id"] for s in SCENARIOS if s["id"].startswith("edge-")}
        self.assertEqual(
            REQUIRED_EDGE_SCENARIO_IDS,
            present,
            "REQUIRED_EDGE_SCENARIO_IDS in build_scenario_manifest.py "
            "does not match the edge scenarios defined in SCENARIOS",
        )

    def test_both_validators_share_same_required_set(self):
        """Both validators must enforce the same required set."""
        from validate_fixture_integrity import (
            REQUIRED_EDGE_SCENARIO_IDS as INTEGRITY_SET,
        )
        from build_scenario_manifest import (
            REQUIRED_EDGE_SCENARIO_IDS as MANIFEST_SET,
        )

        self.assertEqual(
            INTEGRITY_SET,
            MANIFEST_SET,
            "REQUIRED_EDGE_SCENARIO_IDS must be identical in "
            "validate_fixture_integrity.py and build_scenario_manifest.py",
        )


class TestIntegrityValidatorDetectsMissing(unittest.TestCase):
    """Verify validate_fixture_integrity catches missing required IDs."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ag-reqid-test-"))
        self.scenarios_path = self.tmpdir / "scenarios.json"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_scenarios(self, scenario_ids: list[str]) -> None:
        """Write a minimal scenarios.json with the given edge scenario IDs."""
        data = {
            "schema_version": 1,
            "scenarios": [
                {"id": sid, "corpus": ".", "commands": {}}
                for sid in scenario_ids
            ],
        }
        with open(self.scenarios_path, "w") as f:
            json.dump(data, f)

    def test_all_present_passes(self):
        """When all required IDs are present the check passes."""
        from validate_fixture_integrity import (
            IntegrityResult,
            REQUIRED_EDGE_SCENARIO_IDS,
            validate_required_edge_scenario_ids,
        )

        self._write_scenarios(sorted(REQUIRED_EDGE_SCENARIO_IDS))

        # Monkey-patch MANIFESTS_DIR temporarily.
        import validate_fixture_integrity as vfi

        orig = vfi.MANIFESTS_DIR
        vfi.MANIFESTS_DIR = self.tmpdir
        try:
            result = IntegrityResult()
            validate_required_edge_scenario_ids(result, verbose=False)
            self.assertTrue(
                result.passed,
                f"Expected pass but got errors: {result.errors}",
            )
        finally:
            vfi.MANIFESTS_DIR = orig

    def test_missing_one_id_fails(self):
        """Removing one required ID causes the check to fail."""
        from validate_fixture_integrity import (
            IntegrityResult,
            REQUIRED_EDGE_SCENARIO_IDS,
            validate_required_edge_scenario_ids,
        )

        ids = sorted(REQUIRED_EDGE_SCENARIO_IDS)
        removed = ids.pop(0)  # remove the first (alphabetically)
        self._write_scenarios(ids)

        import validate_fixture_integrity as vfi

        orig = vfi.MANIFESTS_DIR
        vfi.MANIFESTS_DIR = self.tmpdir
        try:
            result = IntegrityResult()
            validate_required_edge_scenario_ids(result, verbose=False)
            self.assertFalse(
                result.passed,
                "Expected failure when a required edge scenario ID is missing",
            )
            # Check the specific ID is reported.
            error_text = " ".join(result.errors)
            self.assertIn(
                removed,
                error_text,
                f"Missing ID '{removed}' should be reported in errors",
            )
        finally:
            vfi.MANIFESTS_DIR = orig

    def test_missing_multiple_ids_reports_all(self):
        """Removing multiple required IDs reports each one."""
        from validate_fixture_integrity import (
            IntegrityResult,
            REQUIRED_EDGE_SCENARIO_IDS,
            validate_required_edge_scenario_ids,
        )

        ids = sorted(REQUIRED_EDGE_SCENARIO_IDS)
        removed = ids[:3]
        remaining = ids[3:]
        self._write_scenarios(remaining)

        import validate_fixture_integrity as vfi

        orig = vfi.MANIFESTS_DIR
        vfi.MANIFESTS_DIR = self.tmpdir
        try:
            result = IntegrityResult()
            validate_required_edge_scenario_ids(result, verbose=False)
            self.assertFalse(result.passed)
            error_text = " ".join(result.errors)
            for rid in removed:
                self.assertIn(rid, error_text, f"Missing ID '{rid}' not reported")
        finally:
            vfi.MANIFESTS_DIR = orig

    def test_missing_manifest_file_fails(self):
        """If scenarios.json is absent the check fails."""
        from validate_fixture_integrity import (
            IntegrityResult,
            validate_required_edge_scenario_ids,
        )

        import validate_fixture_integrity as vfi

        orig = vfi.MANIFESTS_DIR
        vfi.MANIFESTS_DIR = self.tmpdir  # no scenarios.json here
        try:
            result = IntegrityResult()
            validate_required_edge_scenario_ids(result, verbose=False)
            self.assertFalse(result.passed)
        finally:
            vfi.MANIFESTS_DIR = orig


class TestScenarioManifestVerifyDetectsMissing(unittest.TestCase):
    """Verify build_scenario_manifest.verify_all() catches missing required IDs."""

    def test_verify_passes_with_full_set(self):
        """verify_all() passes when all required edge scenario IDs are present."""
        from build_scenario_manifest import verify_all

        self.assertTrue(verify_all())

    def test_verify_fails_when_edge_scenario_removed(self):
        """verify_all() fails when a required edge scenario is removed
        from the SCENARIOS list."""
        import build_scenario_manifest as bsm

        orig = bsm.SCENARIOS[:]
        removed_id = "edge-max-count"
        bsm.SCENARIOS[:] = [s for s in bsm.SCENARIOS if s["id"] != removed_id]
        try:
            result = bsm.verify_all()
            self.assertFalse(
                result,
                f"verify_all() should fail when '{removed_id}' is removed",
            )
        finally:
            bsm.SCENARIOS[:] = orig


if __name__ == "__main__":
    unittest.main()
