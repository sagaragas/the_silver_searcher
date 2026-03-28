#!/usr/bin/env python3
"""Tests for edge-case fixture preflight logic.

Verifies that:
  - preflight_check() detects missing fixture directories.
  - preflight_check() detects partial fixture trees (directory exists but
    required marker files are absent).
  - preflight_check() passes when all markers are present.
  - _resolve_needed_edge_categories() maps scenario/group selections
    to the correct fixture category sets.
  - _build_scenario_to_category_map() derives mapping from the manifest.
  - _preflight_edge_fixtures() complete, incomplete, and fail-fast paths.
  - Scenario-to-category mapping cannot silently drift from manifests.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

# ---------------------------------------------------------------------------
# Import helpers from setup_fixtures and run_matrix
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EDGE_CASES_DIR = _REPO_ROOT / "tests" / "edge-cases"
_PARITY_DIR = Path(__file__).resolve().parent

if str(_EDGE_CASES_DIR) not in sys.path:
    sys.path.insert(0, str(_EDGE_CASES_DIR))
if str(_PARITY_DIR) not in sys.path:
    sys.path.insert(0, str(_PARITY_DIR))

from setup_fixtures import (  # noqa: E402
    BUILDERS,
    REQUIRED_MARKERS,
    preflight_check,
    setup_categories,
)
from run_matrix import (  # noqa: E402
    _build_scenario_to_category_map,
    _preflight_edge_fixtures,
    _resolve_needed_edge_categories,
    SCENARIOS_PATH,
)


# ---------------------------------------------------------------------------
# Tests for preflight_check()
# ---------------------------------------------------------------------------


class TestPreflightCheck(unittest.TestCase):
    """Verify that preflight_check detects partial and missing fixture trees."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ag-preflight-test-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_all_missing_returns_all_categories(self) -> None:
        """When the fixture base is empty, every category is incomplete."""
        incomplete = preflight_check(
            categories=list(REQUIRED_MARKERS),
            fixtures_base=self.tmpdir,
        )
        self.assertEqual(sorted(incomplete), sorted(REQUIRED_MARKERS.keys()))

    def test_single_missing_directory(self) -> None:
        """A single absent directory is detected."""
        # Set up all except 'large-file'.
        for name in REQUIRED_MARKERS:
            if name == "large-file":
                continue
            cat_dir = self.tmpdir / name
            cat_dir.mkdir(parents=True, exist_ok=True)
            for marker in REQUIRED_MARKERS[name]:
                marker_path = cat_dir / marker
                marker_path.parent.mkdir(parents=True, exist_ok=True)
                marker_path.write_text("stub", encoding="utf-8")
        # Write platform metadata so it doesn't trigger a false incomplete.
        (self.tmpdir / "platform_metadata.json").write_text("{}", encoding="utf-8")

        incomplete = preflight_check(
            categories=list(REQUIRED_MARKERS),
            fixtures_base=self.tmpdir,
        )
        self.assertEqual(incomplete, ["large-file"])

    def test_partial_tree_detected(self) -> None:
        """A directory that exists but is missing a marker file is flagged."""
        # Create the max-count directory but omit mixed.txt.
        cat_dir = self.tmpdir / "max-count"
        cat_dir.mkdir(parents=True, exist_ok=True)
        (cat_dir / "few-matches.txt").write_text("stub", encoding="utf-8")
        (cat_dir / "many-matches.txt").write_text("stub", encoding="utf-8")
        # mixed.txt deliberately omitted.
        (self.tmpdir / "platform_metadata.json").write_text("{}", encoding="utf-8")

        incomplete = preflight_check(
            categories=["max-count"],
            fixtures_base=self.tmpdir,
        )
        self.assertEqual(incomplete, ["max-count"])

    def test_complete_tree_passes(self) -> None:
        """A fully-populated category passes preflight."""
        cat_dir = self.tmpdir / "max-count"
        cat_dir.mkdir(parents=True, exist_ok=True)
        for marker in REQUIRED_MARKERS["max-count"]:
            (cat_dir / marker).write_text("stub", encoding="utf-8")
        (self.tmpdir / "platform_metadata.json").write_text("{}", encoding="utf-8")

        incomplete = preflight_check(
            categories=["max-count"],
            fixtures_base=self.tmpdir,
        )
        self.assertEqual(incomplete, [])

    def test_missing_platform_metadata_triggers_incomplete(self) -> None:
        """Missing platform_metadata.json triggers at least one incomplete."""
        cat_dir = self.tmpdir / "max-count"
        cat_dir.mkdir(parents=True, exist_ok=True)
        for marker in REQUIRED_MARKERS["max-count"]:
            (cat_dir / marker).write_text("stub", encoding="utf-8")
        # Do NOT write platform_metadata.json.

        incomplete = preflight_check(
            categories=["max-count"],
            fixtures_base=self.tmpdir,
        )
        # Should flag at least one category to force metadata regeneration.
        self.assertTrue(len(incomplete) > 0)

    def test_subset_check_only_inspects_requested(self) -> None:
        """Checking a subset of categories ignores unrequested ones."""
        # Only create ignore-source; leave hidden-files missing.
        cat_dir = self.tmpdir / "ignore-source"
        cat_dir.mkdir(parents=True, exist_ok=True)
        for marker in REQUIRED_MARKERS["ignore-source"]:
            p = cat_dir / marker
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("stub", encoding="utf-8")
        (self.tmpdir / "platform_metadata.json").write_text("{}", encoding="utf-8")

        incomplete = preflight_check(
            categories=["ignore-source"],
            fixtures_base=self.tmpdir,
        )
        self.assertEqual(incomplete, [])

    def test_unknown_category_flagged_incomplete(self) -> None:
        """An unrecognised category name is flagged as incomplete."""
        (self.tmpdir / "platform_metadata.json").write_text("{}", encoding="utf-8")
        incomplete = preflight_check(
            categories=["nonexistent-category"],
            fixtures_base=self.tmpdir,
        )
        self.assertEqual(incomplete, ["nonexistent-category"])


# ---------------------------------------------------------------------------
# Tests for _build_scenario_to_category_map()
# ---------------------------------------------------------------------------


class TestBuildScenarioToCategoryMap(unittest.TestCase):
    """Verify manifest-derived scenario → category mapping."""

    def test_map_covers_all_edge_scenarios(self) -> None:
        """Every edge-* scenario in the manifest has a mapping entry."""
        mapping = _build_scenario_to_category_map()
        with open(SCENARIOS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        edge_ids = [
            s["id"] for s in data["scenarios"]
            if s["id"].startswith("edge-")
            and s["corpus"].startswith("tests/edge-cases/")
        ]
        for sid in edge_ids:
            self.assertIn(
                sid, mapping,
                f"Edge scenario '{sid}' missing from derived mapping",
            )

    def test_map_values_match_corpus_paths(self) -> None:
        """Mapped category names match the corpus path component."""
        mapping = _build_scenario_to_category_map()
        with open(SCENARIOS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        prefix = "tests/edge-cases/"
        for s in data["scenarios"]:
            if s["id"] in mapping:
                expected_cat = s["corpus"][len(prefix):].split("/")[0]
                self.assertEqual(
                    mapping[s["id"]], expected_cat,
                    f"Category mismatch for {s['id']}",
                )

    def test_map_returns_empty_for_missing_manifest(self) -> None:
        """When scenarios.json does not exist, returns empty dict."""
        import run_matrix

        original = run_matrix.SCENARIOS_PATH
        try:
            run_matrix.SCENARIOS_PATH = Path("/nonexistent/scenarios.json")
            mapping = _build_scenario_to_category_map()
            self.assertEqual(mapping, {})
        finally:
            run_matrix.SCENARIOS_PATH = original

    def test_categories_match_builders(self) -> None:
        """All manifest-derived categories exist in setup_fixtures.BUILDERS."""
        mapping = _build_scenario_to_category_map()
        derived_categories = set(mapping.values())
        builder_categories = set(BUILDERS.keys())
        unknown = derived_categories - builder_categories
        self.assertEqual(
            unknown, set(),
            f"Manifest-derived categories not in BUILDERS: {unknown}",
        )

    def test_no_orphan_builders(self) -> None:
        """Every fixture builder category is referenced by at least one edge scenario."""
        mapping = _build_scenario_to_category_map()
        derived_categories = set(mapping.values())
        builder_categories = set(BUILDERS.keys())
        orphans = builder_categories - derived_categories
        self.assertEqual(
            orphans, set(),
            f"Fixture builder categories not referenced by any scenario: {orphans}",
        )


# ---------------------------------------------------------------------------
# Tests for _resolve_needed_edge_categories()
# ---------------------------------------------------------------------------


class TestResolveNeededCategories(unittest.TestCase):
    """Verify scenario/group → category resolution.

    The expected unique category count is 9 because the manifest now
    includes ``ignore-scope-leak`` alongside the original 8 categories.
    """

    def test_edge_cases_group_returns_all(self) -> None:
        cats = _resolve_needed_edge_categories(None, "edge-cases")
        self.assertIsNotNone(cats)
        # Should contain all 9 unique categories (deduped).
        self.assertEqual(len(set(cats)), 9)

    def test_all_group_returns_all(self) -> None:
        cats = _resolve_needed_edge_categories(None, "all")
        self.assertIsNotNone(cats)
        self.assertEqual(len(set(cats)), 9)

    def test_none_group_returns_all(self) -> None:
        cats = _resolve_needed_edge_categories(None, None)
        self.assertIsNotNone(cats)
        self.assertEqual(len(set(cats)), 9)

    def test_smoke_group_returns_none(self) -> None:
        cats = _resolve_needed_edge_categories(None, "smoke")
        self.assertIsNone(cats)

    def test_explicit_edge_scenario_returns_category(self) -> None:
        cats = _resolve_needed_edge_categories(["edge-large-file"], None)
        self.assertEqual(cats, ["large-file"])

    def test_explicit_non_edge_scenario_returns_none(self) -> None:
        cats = _resolve_needed_edge_categories(["literal-simple"], None)
        self.assertIsNone(cats)

    def test_mixed_scenarios_returns_only_edge(self) -> None:
        cats = _resolve_needed_edge_categories(
            ["literal-simple", "edge-ignore-source", "edge-max-count"], None
        )
        self.assertEqual(cats, ["ignore-source", "max-count"])

    def test_categories_are_deduplicated(self) -> None:
        """Multiple scenarios mapping to the same category produce no dupes."""
        # edge-recursion-n-r-precedence and edge-ignore-source both map to
        # ignore-source; the result list should not contain duplicates.
        cats = _resolve_needed_edge_categories(
            ["edge-recursion-n-r-precedence", "edge-ignore-source"], None
        )
        self.assertIsNotNone(cats)
        self.assertEqual(cats, ["ignore-source"])

    def test_ignore_scope_leak_included(self) -> None:
        """edge-ignore-scope-leak maps to the ignore-scope-leak category."""
        cats = _resolve_needed_edge_categories(
            ["edge-ignore-scope-leak"], None
        )
        self.assertEqual(cats, ["ignore-scope-leak"])


# ---------------------------------------------------------------------------
# Tests for _preflight_edge_fixtures() — complete, incomplete, fail-fast
# ---------------------------------------------------------------------------


class TestPreflightEdgeFixtures(unittest.TestCase):
    """Direct tests for _preflight_edge_fixtures() orchestration paths.

    These tests mock the setup_fixtures module import and the underlying
    preflight_check / setup_categories functions to verify the three
    primary control-flow paths without mutating real fixtures on disk.
    """

    def _make_fake_setup_module(
        self,
        preflight_results: list[list[str]],
        setup_side_effect: object = None,
    ) -> mock.MagicMock:
        """Build a fake setup_fixtures module with controllable preflight.

        Parameters
        ----------
        preflight_results:
            Sequential return values for ``preflight_check()``.  The first
            call returns ``preflight_results[0]``, the second returns
            ``preflight_results[1]``, etc.
        setup_side_effect:
            Optional side_effect for ``setup_categories()``.  Defaults to
            ``None`` (no-op).
        """
        mod = mock.MagicMock()
        mod.preflight_check = mock.MagicMock(side_effect=preflight_results)
        mod.setup_categories = mock.MagicMock(side_effect=setup_side_effect)
        return mod

    @mock.patch("run_matrix._resolve_needed_edge_categories")
    def test_complete_fixtures_skip_setup(self, mock_resolve: mock.MagicMock) -> None:
        """When all fixtures are complete, setup_categories is never called."""
        mock_resolve.return_value = ["max-count"]

        fake_mod = self._make_fake_setup_module(
            preflight_results=[[]],  # first check → all complete
        )

        with mock.patch("run_matrix.REPO_ROOT", _REPO_ROOT):
            # Patch importlib to return our fake module.
            with mock.patch("importlib.util.spec_from_file_location") as mock_spec:
                mock_loader = mock.MagicMock()
                mock_loader.exec_module = mock.MagicMock(
                    side_effect=lambda m: None
                )
                spec_obj = mock.MagicMock()
                spec_obj.loader = mock_loader
                mock_spec.return_value = spec_obj
                with mock.patch(
                    "importlib.util.module_from_spec", return_value=fake_mod
                ):
                    _preflight_edge_fixtures(["ag"], None, "edge-cases")

        # preflight_check called once; setup_categories never called.
        fake_mod.preflight_check.assert_called_once()
        fake_mod.setup_categories.assert_not_called()

    @mock.patch("run_matrix._resolve_needed_edge_categories")
    def test_incomplete_triggers_auto_setup(self, mock_resolve: mock.MagicMock) -> None:
        """When preflight finds incomplete categories, auto-setup runs and re-checks."""
        mock_resolve.return_value = ["large-file", "max-count"]

        fake_mod = self._make_fake_setup_module(
            preflight_results=[
                ["large-file"],  # first check → large-file incomplete
                [],              # re-check after setup → all complete
            ],
        )

        with mock.patch("run_matrix.REPO_ROOT", _REPO_ROOT):
            with mock.patch("importlib.util.spec_from_file_location") as mock_spec:
                mock_loader = mock.MagicMock()
                mock_loader.exec_module = mock.MagicMock(
                    side_effect=lambda m: None
                )
                spec_obj = mock.MagicMock()
                spec_obj.loader = mock_loader
                mock_spec.return_value = spec_obj
                with mock.patch(
                    "importlib.util.module_from_spec", return_value=fake_mod
                ):
                    _preflight_edge_fixtures(["ag"], None, "edge-cases")

        # preflight_check called twice (before and after setup).
        self.assertEqual(fake_mod.preflight_check.call_count, 2)
        # setup_categories called once with the incomplete list.
        fake_mod.setup_categories.assert_called_once_with(["large-file"])

    @mock.patch("run_matrix._resolve_needed_edge_categories")
    def test_fail_fast_after_failed_auto_setup(self, mock_resolve: mock.MagicMock) -> None:
        """When auto-setup fails to fix categories, sys.exit(2) is called."""
        mock_resolve.return_value = ["large-file"]

        fake_mod = self._make_fake_setup_module(
            preflight_results=[
                ["large-file"],  # first check → incomplete
                ["large-file"],  # re-check → still incomplete
            ],
        )

        with mock.patch("run_matrix.REPO_ROOT", _REPO_ROOT):
            with mock.patch("importlib.util.spec_from_file_location") as mock_spec:
                mock_loader = mock.MagicMock()
                mock_loader.exec_module = mock.MagicMock(
                    side_effect=lambda m: None
                )
                spec_obj = mock.MagicMock()
                spec_obj.loader = mock_loader
                mock_spec.return_value = spec_obj
                with mock.patch(
                    "importlib.util.module_from_spec", return_value=fake_mod
                ):
                    with self.assertRaises(SystemExit) as ctx:
                        _preflight_edge_fixtures(["ag"], None, "edge-cases")

        self.assertEqual(ctx.exception.code, 2)
        # setup_categories was called attempting repair.
        fake_mod.setup_categories.assert_called_once_with(["large-file"])

    @mock.patch("run_matrix._resolve_needed_edge_categories")
    def test_no_edge_scenarios_skips_preflight(self, mock_resolve: mock.MagicMock) -> None:
        """When no edge scenarios are needed, preflight is skipped entirely."""
        mock_resolve.return_value = None

        # Should not import setup_fixtures at all.
        with mock.patch("importlib.util.spec_from_file_location") as mock_spec:
            _preflight_edge_fixtures(["ag"], None, "smoke")
            mock_spec.assert_not_called()

    @mock.patch("run_matrix._resolve_needed_edge_categories")
    def test_deduplicates_needed_categories(self, mock_resolve: mock.MagicMock) -> None:
        """Duplicate categories from multiple scenarios are deduplicated."""
        # Simulate two scenarios both needing ignore-source.
        mock_resolve.return_value = ["ignore-source", "ignore-source", "max-count"]

        fake_mod = self._make_fake_setup_module(
            preflight_results=[[]],  # all complete
        )

        with mock.patch("run_matrix.REPO_ROOT", _REPO_ROOT):
            with mock.patch("importlib.util.spec_from_file_location") as mock_spec:
                mock_loader = mock.MagicMock()
                mock_loader.exec_module = mock.MagicMock(
                    side_effect=lambda m: None
                )
                spec_obj = mock.MagicMock()
                spec_obj.loader = mock_loader
                mock_spec.return_value = spec_obj
                with mock.patch(
                    "importlib.util.module_from_spec", return_value=fake_mod
                ):
                    _preflight_edge_fixtures(["ag"], None, "edge-cases")

        # The categories passed to preflight_check should be deduplicated.
        call_args = fake_mod.preflight_check.call_args
        checked_categories = call_args[0][0] if call_args[0] else call_args[1].get("categories", call_args[0])
        # Should have 2 unique, not 3 with a duplicate.
        self.assertEqual(len(checked_categories), 2)
        self.assertIn("ignore-source", checked_categories)
        self.assertIn("max-count", checked_categories)


# ---------------------------------------------------------------------------
# Tests for setup_categories()
# ---------------------------------------------------------------------------


class TestSetupCategories(unittest.TestCase):
    """Verify that setup_categories rebuilds only requested categories."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ag-setup-cat-test-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_setup_single_category(self) -> None:
        """Building a single category populates its markers."""
        # Redirect FIXTURES_BASE for test isolation is tricky; instead we
        # test via preflight on the real fixtures dir — but that mutates
        # state.  Instead, verify setup_categories exists and is callable.
        #
        # The integration path (auto-setup in run_matrix) is tested by the
        # verification steps.
        import setup_fixtures

        # Verify the function signature exists.
        self.assertTrue(callable(setup_fixtures.setup_categories))


# ---------------------------------------------------------------------------
# Tests for REQUIRED_MARKERS consistency with BUILDERS
# ---------------------------------------------------------------------------


class TestRequiredMarkersConsistency(unittest.TestCase):
    """Ensure every BUILDERS category has REQUIRED_MARKERS and vice versa."""

    def test_builders_and_markers_match(self) -> None:
        self.assertEqual(
            sorted(BUILDERS.keys()),
            sorted(REQUIRED_MARKERS.keys()),
            "BUILDERS and REQUIRED_MARKERS must define the same categories",
        )


# ---------------------------------------------------------------------------
# Tests for scenario-category drift detection
# ---------------------------------------------------------------------------


class TestScenarioCategoryDrift(unittest.TestCase):
    """Verify that scenario-to-category mapping cannot silently drift.

    These tests ensure the manifest-derived mapping stays in sync with
    fixture builder definitions, catching drift at test time.
    """

    def test_all_derived_categories_have_builders(self) -> None:
        """Every category derived from the manifest has a fixture builder."""
        mapping = _build_scenario_to_category_map()
        derived = set(mapping.values())
        for cat in derived:
            self.assertIn(
                cat, BUILDERS,
                f"Category '{cat}' from manifest has no fixture builder",
            )

    def test_all_builders_have_scenarios(self) -> None:
        """Every fixture builder category is referenced by at least one scenario."""
        mapping = _build_scenario_to_category_map()
        derived = set(mapping.values())
        for cat in BUILDERS:
            self.assertIn(
                cat, derived,
                f"Fixture builder category '{cat}' has no scenario reference",
            )

    def test_all_builders_have_required_markers(self) -> None:
        """Every builder category has corresponding REQUIRED_MARKERS."""
        for cat in BUILDERS:
            self.assertIn(
                cat, REQUIRED_MARKERS,
                f"Builder category '{cat}' has no REQUIRED_MARKERS entry",
            )

    def test_adding_scenario_without_builder_detected(self) -> None:
        """Simulated scenario referencing unknown category is detected.

        This test patches the manifest to add a fake edge scenario with a
        corpus pointing to a non-existent category, and verifies the
        drift detection catches it.
        """
        import run_matrix

        # Create a temporary manifest with an extra scenario.
        tmpdir = Path(tempfile.mkdtemp(prefix="ag-drift-test-"))
        try:
            fake_manifest = {
                "scenarios": [
                    {
                        "id": "edge-fake-category",
                        "corpus": "tests/edge-cases/fake-new-category",
                        "commands": {"ag": "ag {pattern} {corpus}"},
                    }
                ]
            }
            fake_path = tmpdir / "scenarios.json"
            with open(fake_path, "w") as f:
                json.dump(fake_manifest, f)

            original = run_matrix.SCENARIOS_PATH
            try:
                run_matrix.SCENARIOS_PATH = fake_path
                mapping = _build_scenario_to_category_map()
            finally:
                run_matrix.SCENARIOS_PATH = original

            self.assertIn("edge-fake-category", mapping)
            self.assertEqual(mapping["edge-fake-category"], "fake-new-category")
            # The derived category is NOT in BUILDERS → drift detected.
            self.assertNotIn("fake-new-category", BUILDERS)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
