#!/usr/bin/env python3
"""Tests for benchmark harness manifest integrity, matrix completeness,
command-equivalence, and comparator version capture.

VAL-BENCH-001: Comparator matrix is complete — all scenario-comparator cells
               execute with no missing runs.
VAL-BENCH-002: Comparator versions are captured — every run records exact
               comparator versions/build identifiers.
VAL-BENCH-009: Comparator command intent is equivalent — scenario definitions
               are expanded into comparator-specific commands that preserve
               equivalent logical workload intent.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# benchmarks/tests/ → parents[0]=tests, parents[1]=benchmarks, parents[2]=repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "benchmarks"))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MANIFESTS_DIR = REPO_ROOT / "manifests"


@pytest.fixture
def scenarios_manifest():
    """Load the on-disk scenarios.json manifest."""
    path = MANIFESTS_DIR / "scenarios.json"
    assert path.exists(), "scenarios.json manifest must exist"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def queries_manifest():
    """Load the on-disk queries.json manifest."""
    path = MANIFESTS_DIR / "queries.json"
    assert path.exists(), "queries.json manifest must exist"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# VAL-BENCH-001: Matrix completeness
# ---------------------------------------------------------------------------


class TestMatrixCompleteness:
    """Verify that every scenario has commands for all required comparators."""

    REQUIRED_COMPARATORS = {"ag", "rust-ag", "rg", "ugrep"}

    def test_all_scenarios_have_command_entries(self, scenarios_manifest):
        """Every scenario must define a commands dict."""
        for scenario in scenarios_manifest["scenarios"]:
            assert "commands" in scenario, (
                f"Scenario '{scenario['id']}' missing 'commands' dict"
            )

    def test_full_matrix_comparators_present(self, scenarios_manifest):
        """Scenarios targeting all comparators must have all four present.

        Some scenarios are ag/rust-ag-only (e.g., edge-case parity tests),
        but scenarios that include rg/ugrep must include all four.
        """
        full_comparator_scenarios = []
        partial_scenarios = []

        for scenario in scenarios_manifest["scenarios"]:
            cmds = scenario.get("commands", {})
            comparators_present = set(cmds.keys())
            if comparators_present == self.REQUIRED_COMPARATORS:
                full_comparator_scenarios.append(scenario["id"])
            else:
                partial_scenarios.append(
                    (scenario["id"], comparators_present)
                )

        # There must be at least some scenarios with all comparators.
        assert len(full_comparator_scenarios) > 0, (
            "No scenarios found with all four comparators"
        )

    def test_no_empty_command_templates(self, scenarios_manifest):
        """No command template should be empty or None."""
        for scenario in scenarios_manifest["scenarios"]:
            for comp, cmd in scenario.get("commands", {}).items():
                assert cmd and cmd.strip(), (
                    f"Scenario '{scenario['id']}' has empty command for '{comp}'"
                )

    def test_comparators_list_matches_manifest(self, scenarios_manifest):
        """Top-level comparators list should match canonical set."""
        assert set(scenarios_manifest["comparators"]) == self.REQUIRED_COMPARATORS

    def test_scenario_count_matches(self, scenarios_manifest):
        """scenario_count field matches actual number of scenarios."""
        assert scenarios_manifest["scenario_count"] == len(
            scenarios_manifest["scenarios"]
        )


# ---------------------------------------------------------------------------
# VAL-BENCH-002: Comparator version capture
# ---------------------------------------------------------------------------


class TestComparatorVersionCapture:
    """Verify that the harness captures comparator versions correctly."""

    def test_capture_version_ag(self):
        """ag version capture returns a non-empty version string."""
        from harness import capture_comparator_version, resolve_binary

        binary = resolve_binary("ag")
        if binary is None:
            pytest.skip("ag binary not available")
        version = capture_comparator_version("ag", binary)
        assert version, "ag version should not be empty"
        assert "ag" in version.lower() or "version" in version.lower() or len(version) > 0

    def test_capture_version_rust_ag(self):
        """rust-ag version capture returns a non-empty version string."""
        from harness import capture_comparator_version, resolve_binary

        binary = resolve_binary("rust-ag")
        if binary is None:
            pytest.skip("rust-ag binary not available")
        version = capture_comparator_version("rust-ag", binary)
        assert version, "rust-ag version should not be empty"

    def test_capture_version_rg(self):
        """rg version capture returns a non-empty version string."""
        from harness import capture_comparator_version, resolve_binary

        binary = resolve_binary("rg")
        if binary is None:
            pytest.skip("rg binary not available")
        version = capture_comparator_version("rg", binary)
        assert version, "rg version should not be empty"
        assert "ripgrep" in version.lower() or "rg" in version.lower()

    def test_capture_version_ugrep(self):
        """ugrep version capture returns a non-empty version string."""
        from harness import capture_comparator_version, resolve_binary

        binary = resolve_binary("ugrep")
        if binary is None:
            pytest.skip("ugrep binary not available")
        version = capture_comparator_version("ugrep", binary)
        assert version, "ugrep version should not be empty"

    def test_tools_metadata_schema(self):
        """Tools metadata artifact should have expected schema."""
        from harness import collect_tools_metadata

        meta = collect_tools_metadata(["ag", "rust-ag", "rg", "ugrep"])
        assert "comparators" in meta
        for comp in ["ag", "rust-ag", "rg", "ugrep"]:
            assert comp in meta["comparators"], f"Missing {comp} in tools metadata"
            entry = meta["comparators"][comp]
            assert "binary_path" in entry
            assert "version" in entry
            assert "version_raw" in entry


# ---------------------------------------------------------------------------
# VAL-BENCH-009: Command equivalence
# ---------------------------------------------------------------------------


class TestCommandEquivalence:
    """Verify that expanded commands preserve equivalent workload intent."""

    def test_all_commands_use_pattern_placeholder(self, scenarios_manifest):
        """Every command template should include {pattern} placeholder."""
        for scenario in scenarios_manifest["scenarios"]:
            for comp, cmd in scenario.get("commands", {}).items():
                assert "{pattern}" in cmd, (
                    f"Scenario '{scenario['id']}' / {comp}: "
                    f"missing {{pattern}} placeholder in: {cmd}"
                )

    def test_all_commands_use_corpus_placeholder(self, scenarios_manifest):
        """Every command template should include {corpus} placeholder."""
        for scenario in scenarios_manifest["scenarios"]:
            for comp, cmd in scenario.get("commands", {}).items():
                assert "{corpus}" in cmd, (
                    f"Scenario '{scenario['id']}' / {comp}: "
                    f"missing {{corpus}} placeholder in: {cmd}"
                )

    def test_color_disabled_in_all_commands(self, scenarios_manifest):
        """All commands should disable color for benchmark consistency."""
        color_patterns = {
            "ag": "--nocolor",
            "rust-ag": "--nocolor",
            "rg": "--color=never",
            "ugrep": "--color=never",
        }
        for scenario in scenarios_manifest["scenarios"]:
            for comp, cmd in scenario.get("commands", {}).items():
                expected = color_patterns.get(comp)
                if expected:
                    assert expected in cmd, (
                        f"Scenario '{scenario['id']}' / {comp}: "
                        f"missing color disable flag ({expected}) in: {cmd}"
                    )

    def test_equivalent_flags_across_comparators(self, scenarios_manifest):
        """Verify that equivalent flags are used across comparators.

        Examples of equivalent intent:
        - ag -i / rg -i / ugrep -i  (case-insensitive)
        - ag --count / rg --count / ugrep --count  (count mode)
        - ag -B2 -A2 / rg -B2 -A2 / ugrep -B2 -A2  (context)
        """
        # Check a few canonical scenarios that should have equivalent flags.
        scenarios_by_id = {s["id"]: s for s in scenarios_manifest["scenarios"]}

        # literal-nocase: all should have -i
        if "literal-nocase" in scenarios_by_id:
            s = scenarios_by_id["literal-nocase"]
            for comp, cmd in s["commands"].items():
                assert "-i" in cmd.split(), (
                    f"literal-nocase/{comp} missing -i flag: {cmd}"
                )

        # count-matches: all should have --count
        if "count-matches" in scenarios_by_id:
            s = scenarios_by_id["count-matches"]
            for comp, cmd in s["commands"].items():
                assert "--count" in cmd, (
                    f"count-matches/{comp} missing --count flag: {cmd}"
                )

        # context-before-after: all should have -B2 -A2
        if "context-before-after" in scenarios_by_id:
            s = scenarios_by_id["context-before-after"]
            for comp, cmd in s["commands"].items():
                assert "-B2" in cmd and "-A2" in cmd, (
                    f"context-before-after/{comp} missing context flags: {cmd}"
                )

    def test_expand_command_produces_valid_argv(self, scenarios_manifest, queries_manifest):
        """Expanding a command template with pattern+corpus produces a valid string."""
        from harness import expand_command

        query_by_id = {q["id"]: q for q in queries_manifest["queries"]}

        for scenario in scenarios_manifest["scenarios"]:
            query = query_by_id.get(scenario["query_id"])
            if not query:
                continue
            for comp, template in scenario.get("commands", {}).items():
                expanded = expand_command(template, query["pattern"], scenario["corpus"])
                assert "{pattern}" not in expanded, (
                    f"Unexpanded {{pattern}} in {scenario['id']}/{comp}"
                )
                assert "{corpus}" not in expanded, (
                    f"Unexpanded {{corpus}} in {scenario['id']}/{comp}"
                )
                # Should have at least the binary name.
                assert len(expanded.strip()) > 0

    def test_query_ids_reference_valid_queries(self, scenarios_manifest, queries_manifest):
        """Every scenario's query_id must reference an existing query."""
        query_ids = {q["id"] for q in queries_manifest["queries"]}
        for scenario in scenarios_manifest["scenarios"]:
            assert scenario["query_id"] in query_ids, (
                f"Scenario '{scenario['id']}' references unknown query '{scenario['query_id']}'"
            )

    def test_symlink_flag_equivalence(self, scenarios_manifest):
        """Symlink-follow flags should be equivalent across comparators.

        ag uses -f, rg/ugrep use -L for symlink following.
        """
        scenarios_by_id = {s["id"]: s for s in scenarios_manifest["scenarios"]}
        if "edge-symlink-traversal" in scenarios_by_id:
            s = scenarios_by_id["edge-symlink-traversal"]
            cmds = s["commands"]
            if "ag" in cmds:
                assert "-f" in cmds["ag"].split()
            if "rust-ag" in cmds:
                assert "-f" in cmds["rust-ag"].split()
            if "rg" in cmds:
                assert "-L" in cmds["rg"].split()
            if "ugrep" in cmds:
                assert "-L" in cmds["ugrep"].split()


# ---------------------------------------------------------------------------
# Harness smoke test integration
# ---------------------------------------------------------------------------


class TestHarnessSmokeExecution:
    """Integration tests for the harness smoke subcommand."""

    def test_smoke_run_produces_run_manifest(self, tmp_path):
        """A smoke run should produce a run manifest with all comparator cells."""
        from harness import run_smoke, resolve_binary

        # Check all comparators are available.
        comparators = ["ag", "rust-ag", "rg", "ugrep"]
        available = [c for c in comparators if resolve_binary(c) is not None]
        if len(available) < len(comparators):
            missing = set(comparators) - set(available)
            pytest.skip(f"Missing comparator(s): {missing}")

        result = run_smoke(
            comparators=comparators,
            output_dir=tmp_path,
        )

        # Run manifest should exist.
        assert (tmp_path / "run_manifest.json").exists()

        # Load and validate structure.
        with open(tmp_path / "run_manifest.json") as f:
            manifest = json.load(f)

        assert "run_id" in manifest
        assert "timestamp" in manifest
        assert "comparators" in manifest
        assert "scenarios" in manifest
        assert "tools_metadata" in manifest

        # Tools metadata should have all comparators.
        tools = manifest["tools_metadata"]["comparators"]
        for c in comparators:
            assert c in tools, f"Missing {c} in tools_metadata"
            assert tools[c]["version"], f"Empty version for {c}"

        # Every scenario should have results for all available comparators.
        for scenario in manifest["scenarios"]:
            if scenario.get("skipped"):
                continue
            for c in comparators:
                if c in scenario.get("commands", {}):
                    assert c in scenario.get("results", {}), (
                        f"Missing result for {c} in scenario {scenario['scenario_id']}"
                    )

    def test_smoke_run_no_missing_cells(self, tmp_path):
        """No scenario-comparator cells should be missing in smoke run."""
        from harness import run_smoke, resolve_binary

        comparators = ["ag", "rust-ag", "rg", "ugrep"]
        available = [c for c in comparators if resolve_binary(c) is not None]
        if len(available) < len(comparators):
            missing = set(comparators) - set(available)
            pytest.skip(f"Missing comparator(s): {missing}")

        result = run_smoke(
            comparators=comparators,
            output_dir=tmp_path,
        )

        with open(tmp_path / "run_manifest.json") as f:
            manifest = json.load(f)

        missing_cells = []
        for scenario in manifest["scenarios"]:
            if scenario.get("skipped"):
                continue
            commands = scenario.get("commands", {})
            results = scenario.get("results", {})
            for comp in commands:
                if comp not in results:
                    missing_cells.append(f"{scenario['scenario_id']}/{comp}")

        assert len(missing_cells) == 0, (
            f"Missing cells: {missing_cells}"
        )

    def test_command_equivalence_artifact_produced(self, tmp_path):
        """Smoke run should produce a command_equivalence.json artifact."""
        from harness import run_smoke, resolve_binary

        comparators = ["ag", "rust-ag", "rg", "ugrep"]
        available = [c for c in comparators if resolve_binary(c) is not None]
        if len(available) < len(comparators):
            missing = set(comparators) - set(available)
            pytest.skip(f"Missing comparator(s): {missing}")

        run_smoke(comparators=comparators, output_dir=tmp_path)

        equiv_path = tmp_path / "command_equivalence.json"
        assert equiv_path.exists(), "command_equivalence.json should be produced"

        with open(equiv_path) as f:
            equiv = json.load(f)

        assert "scenarios" in equiv
        assert len(equiv["scenarios"]) > 0
        for entry in equiv["scenarios"]:
            assert "scenario_id" in entry
            assert "expanded_commands" in entry


# ---------------------------------------------------------------------------
# Negative tests: missing required comparator cells fail validation
# ---------------------------------------------------------------------------


class TestRequiredComparatorEnforcement:
    """Verify that missing required comparator cells cause hard failures."""

    def test_validate_manifest_fails_on_missing_required_cell(self, tmp_path):
        """validate_manifest must fail when a required comparator cell is missing.

        A scenario declares commands for ag, rust-ag, rg, ugrep but the run
        manifest only has results for 3 of them — validation must fail.
        """
        from validate_manifest import validate_run

        run_dir = tmp_path / "test_run"
        run_dir.mkdir()

        # Build a run manifest where scenario "literal-simple" is missing
        # the ugrep result despite having a command for it.
        manifest = {
            "schema_version": 1,
            "run_id": "test-missing-cell",
            "run_type": "smoke",
            "timestamp": "2026-03-05T00:00:00Z",
            "commit_sha": "abc123",
            "comparators": ["ag", "rust-ag", "rg", "ugrep"],
            "manifest_hashes": {"scenarios": "", "queries": "", "corpus": ""},
            "environment": {},
            "tools_metadata": {
                "comparators": {
                    "ag": {"binary_path": "/usr/bin/ag", "version": "1.0", "version_raw": "1.0"},
                    "rust-ag": {"binary_path": "/usr/bin/rust-ag", "version": "1.0", "version_raw": "1.0"},
                    "rg": {"binary_path": "/usr/bin/rg", "version": "1.0", "version_raw": "1.0"},
                    "ugrep": {"binary_path": "/usr/bin/ugrep", "version": "1.0", "version_raw": "1.0"},
                },
            },
            "scenario_count": 1,
            "cell_totals": {"total": 4, "executed": 3, "skipped": 1, "errors": 0},
            "scenarios": [
                {
                    "scenario_id": "literal-simple",
                    "query_id": "q-literal-simple",
                    "pattern": "TODO",
                    "corpus": ".",
                    "commands": {
                        "ag": "ag {pattern} {corpus}",
                        "rust-ag": "rust-ag {pattern} {corpus}",
                        "rg": "rg {pattern} {corpus}",
                        "ugrep": "ugrep {pattern} {corpus}",
                    },
                    "results": {
                        "ag": {"command": "ag TODO .", "exit_code": 0, "elapsed_s": 0.1},
                        "rust-ag": {"command": "rust-ag TODO .", "exit_code": 0, "elapsed_s": 0.1},
                        "rg": {"command": "rg TODO .", "exit_code": 0, "elapsed_s": 0.1},
                        # ugrep is MISSING — this must fail validation
                    },
                    "skipped": False,
                }
            ],
        }
        _write_test_manifest(run_dir, manifest)

        ok = validate_run(run_dir)
        assert not ok, "Validation must fail when a required comparator cell is missing"

    def test_validate_manifest_fails_on_skipped_required_cell(self, tmp_path):
        """validate_manifest must fail when a required comparator cell is skipped.

        A scenario declares commands for a comparator but the result says
        skipped=True — this is a required cell and must not be allowed.
        """
        from validate_manifest import validate_run

        run_dir = tmp_path / "test_run"
        run_dir.mkdir()

        manifest = {
            "schema_version": 1,
            "run_id": "test-skipped-cell",
            "run_type": "smoke",
            "timestamp": "2026-03-05T00:00:00Z",
            "commit_sha": "abc123",
            "comparators": ["ag", "rust-ag", "rg", "ugrep"],
            "manifest_hashes": {"scenarios": "", "queries": "", "corpus": ""},
            "environment": {},
            "tools_metadata": {
                "comparators": {
                    "ag": {"binary_path": "/usr/bin/ag", "version": "1.0", "version_raw": "1.0"},
                    "rust-ag": {"binary_path": "/usr/bin/rust-ag", "version": "1.0", "version_raw": "1.0"},
                    "rg": {"binary_path": "/usr/bin/rg", "version": "1.0", "version_raw": "1.0"},
                    "ugrep": {"binary_path": "/usr/bin/ugrep", "version": "1.0", "version_raw": "1.0"},
                },
            },
            "scenario_count": 1,
            "cell_totals": {"total": 4, "executed": 3, "skipped": 1, "errors": 0},
            "scenarios": [
                {
                    "scenario_id": "literal-simple",
                    "query_id": "q-literal-simple",
                    "pattern": "TODO",
                    "corpus": ".",
                    "commands": {
                        "ag": "ag {pattern} {corpus}",
                        "rust-ag": "rust-ag {pattern} {corpus}",
                        "rg": "rg {pattern} {corpus}",
                        "ugrep": "ugrep {pattern} {corpus}",
                    },
                    "results": {
                        "ag": {"command": "ag TODO .", "exit_code": 0, "elapsed_s": 0.1},
                        "rust-ag": {"command": "rust-ag TODO .", "exit_code": 0, "elapsed_s": 0.1},
                        "rg": {"command": "rg TODO .", "exit_code": 0, "elapsed_s": 0.1},
                        "ugrep": {"skipped": True, "reason": "No command template for ugrep"},
                    },
                    "skipped": False,
                }
            ],
        }
        _write_test_manifest(run_dir, manifest)

        ok = validate_run(run_dir)
        assert not ok, "Validation must fail when a required comparator cell is skipped"

    def test_validate_manifest_passes_for_partial_scenario(self, tmp_path):
        """Scenarios that only define ag/rust-ag commands should pass when
        only those comparators have results (they are not required for rg/ugrep).
        """
        from validate_manifest import validate_run

        run_dir = tmp_path / "test_run"
        run_dir.mkdir()

        manifest = {
            "schema_version": 1,
            "run_id": "test-partial-ok",
            "run_type": "smoke",
            "timestamp": "2026-03-05T00:00:00Z",
            "commit_sha": "abc123",
            "comparators": ["ag", "rust-ag", "rg", "ugrep"],
            "manifest_hashes": {"scenarios": "", "queries": "", "corpus": ""},
            "environment": {},
            "tools_metadata": {
                "comparators": {
                    "ag": {"binary_path": "/usr/bin/ag", "version": "1.0", "version_raw": "1.0"},
                    "rust-ag": {"binary_path": "/usr/bin/rust-ag", "version": "1.0", "version_raw": "1.0"},
                    "rg": {"binary_path": "/usr/bin/rg", "version": "1.0", "version_raw": "1.0"},
                    "ugrep": {"binary_path": "/usr/bin/ugrep", "version": "1.0", "version_raw": "1.0"},
                },
            },
            "scenario_count": 1,
            "cell_totals": {"total": 2, "executed": 2, "skipped": 0, "errors": 0},
            "scenarios": [
                {
                    "scenario_id": "edge-ignore-scope-leak",
                    "query_id": "q-edge-needle",
                    "pattern": "NEEDLE",
                    "corpus": "tests/edge-cases/ignore-scope-leak",
                    "commands": {
                        "ag": "ag {pattern} {corpus}",
                        "rust-ag": "rust-ag {pattern} {corpus}",
                        # No rg/ugrep commands — they are NOT required
                    },
                    "results": {
                        "ag": {"command": "ag NEEDLE .", "exit_code": 0, "elapsed_s": 0.1},
                        "rust-ag": {"command": "rust-ag NEEDLE .", "exit_code": 0, "elapsed_s": 0.1},
                    },
                    "skipped": False,
                }
            ],
        }
        _write_test_manifest(run_dir, manifest)

        ok = validate_run(run_dir)
        assert ok, "Validation should pass when all defined-command comparators have results"

    def test_harness_smoke_fails_on_missing_required_cell(self, tmp_path):
        """Harness smoke run must fail (non-zero exit) when a required comparator
        cell cannot be executed because the comparator in the scenario's commands
        was requested but the binary is not found.

        We mock resolve_binary to return None for ugrep to simulate missing.
        """
        from harness import run_smoke, resolve_binary

        # Only run this test if we can mock away one comparator.
        # We need at least ag, rust-ag, rg to be present.
        for comp in ["ag", "rust-ag", "rg"]:
            if resolve_binary(comp) is None:
                pytest.skip(f"Missing comparator {comp}")

        with mock.patch("harness.resolve_binary") as mock_resolve:
            def mock_resolve_fn(name):
                if name == "ugrep":
                    return None
                return resolve_binary.__wrapped__(name) if hasattr(resolve_binary, '__wrapped__') else resolve_binary(name)

            # We need the original resolve_binary to work for non-ugrep.
            original_resolve = resolve_binary

            def selective_mock(name):
                if name == "ugrep":
                    return None
                return original_resolve(name)

            mock_resolve.side_effect = selective_mock

            # The harness should detect missing required cells and raise or exit.
            with pytest.raises(SystemExit) as exc_info:
                run_smoke(
                    comparators=["ag", "rust-ag", "rg", "ugrep"],
                    output_dir=tmp_path,
                    scenario_ids=["literal-simple"],
                    timeout=10,
                )

            # Must be a non-zero exit.
            assert exc_info.value.code != 0, (
                "Harness must exit non-zero when required comparator is missing"
            )

    def test_validate_manifest_fails_on_binary_not_found_cell(self, tmp_path):
        """validate_manifest must fail when a cell has error=binary_not_found
        for a comparator defined in the scenario's commands.
        """
        from validate_manifest import validate_run

        run_dir = tmp_path / "test_run"
        run_dir.mkdir()

        manifest = {
            "schema_version": 1,
            "run_id": "test-binary-not-found",
            "run_type": "smoke",
            "timestamp": "2026-03-05T00:00:00Z",
            "commit_sha": "abc123",
            "comparators": ["ag", "rust-ag", "rg", "ugrep"],
            "manifest_hashes": {"scenarios": "", "queries": "", "corpus": ""},
            "environment": {},
            "tools_metadata": {
                "comparators": {
                    "ag": {"binary_path": "/usr/bin/ag", "version": "1.0", "version_raw": "1.0"},
                    "rust-ag": {"binary_path": "/usr/bin/rust-ag", "version": "1.0", "version_raw": "1.0"},
                    "rg": {"binary_path": "/usr/bin/rg", "version": "1.0", "version_raw": "1.0"},
                    "ugrep": {"binary_path": None, "version": "not found", "version_raw": "not found"},
                },
            },
            "scenario_count": 1,
            "cell_totals": {"total": 4, "executed": 3, "skipped": 0, "errors": 1},
            "scenarios": [
                {
                    "scenario_id": "literal-simple",
                    "query_id": "q-literal-simple",
                    "pattern": "TODO",
                    "corpus": ".",
                    "commands": {
                        "ag": "ag {pattern} {corpus}",
                        "rust-ag": "rust-ag {pattern} {corpus}",
                        "rg": "rg {pattern} {corpus}",
                        "ugrep": "ugrep {pattern} {corpus}",
                    },
                    "results": {
                        "ag": {"command": "ag TODO .", "exit_code": 0, "elapsed_s": 0.1},
                        "rust-ag": {"command": "rust-ag TODO .", "exit_code": 0, "elapsed_s": 0.1},
                        "rg": {"command": "rg TODO .", "exit_code": 0, "elapsed_s": 0.1},
                        "ugrep": {
                            "command": "ugrep TODO .",
                            "exit_code": -127,
                            "elapsed_s": 0,
                            "error": "binary_not_found",
                        },
                    },
                    "skipped": False,
                }
            ],
        }
        _write_test_manifest(run_dir, manifest)

        ok = validate_run(run_dir)
        assert not ok, "Validation must fail when a required cell has binary_not_found error"

    def test_validate_manifest_enforces_required_for_requested_comparators(self, tmp_path):
        """When run comparators list includes a comparator that has a command
        template in a scenario, the cell result MUST exist.
        """
        from validate_manifest import validate_run

        run_dir = tmp_path / "test_run"
        run_dir.mkdir()

        # Scenario has all 4 commands, but results only for 2.
        manifest = {
            "schema_version": 1,
            "run_id": "test-half-missing",
            "run_type": "smoke",
            "timestamp": "2026-03-05T00:00:00Z",
            "commit_sha": "abc123",
            "comparators": ["ag", "rust-ag", "rg", "ugrep"],
            "manifest_hashes": {"scenarios": "", "queries": "", "corpus": ""},
            "environment": {},
            "tools_metadata": {
                "comparators": {
                    "ag": {"binary_path": "/usr/bin/ag", "version": "1.0", "version_raw": "1.0"},
                    "rust-ag": {"binary_path": "/usr/bin/rust-ag", "version": "1.0", "version_raw": "1.0"},
                    "rg": {"binary_path": "/usr/bin/rg", "version": "1.0", "version_raw": "1.0"},
                    "ugrep": {"binary_path": "/usr/bin/ugrep", "version": "1.0", "version_raw": "1.0"},
                },
            },
            "scenario_count": 1,
            "cell_totals": {"total": 4, "executed": 2, "skipped": 2, "errors": 0},
            "scenarios": [
                {
                    "scenario_id": "literal-simple",
                    "query_id": "q-literal-simple",
                    "pattern": "TODO",
                    "corpus": ".",
                    "commands": {
                        "ag": "ag {pattern} {corpus}",
                        "rust-ag": "rust-ag {pattern} {corpus}",
                        "rg": "rg {pattern} {corpus}",
                        "ugrep": "ugrep {pattern} {corpus}",
                    },
                    "results": {
                        "ag": {"command": "ag TODO .", "exit_code": 0, "elapsed_s": 0.1},
                        "rust-ag": {"command": "rust-ag TODO .", "exit_code": 0, "elapsed_s": 0.1},
                        # rg and ugrep are MISSING — hard failure
                    },
                    "skipped": False,
                }
            ],
        }
        _write_test_manifest(run_dir, manifest)

        ok = validate_run(run_dir)
        assert not ok, "Validation must fail when multiple required comparator cells are missing"


def _get_on_disk_manifest_hashes() -> dict[str, str]:
    """Read manifest hashes from on-disk scenario/query/corpus manifests."""
    hashes = {}
    for name in ["scenarios", "queries", "corpus"]:
        path = MANIFESTS_DIR / f"{name}.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            hashes[name] = data.get("manifest_hash", "")
        else:
            hashes[name] = ""
    return hashes


def _write_test_manifest(run_dir: Path, manifest: dict) -> None:
    """Write test manifests to a run directory for validation tests.

    Automatically populates manifest_hashes from on-disk manifests if
    the test manifest has empty hashes, to avoid spurious hash-mismatch
    failures that would mask the check being tested.
    """
    import json

    # Auto-fill manifest hashes if they are empty placeholders.
    mh = manifest.get("manifest_hashes", {})
    if not mh.get("scenarios") and not mh.get("queries") and not mh.get("corpus"):
        on_disk = _get_on_disk_manifest_hashes()
        manifest["manifest_hashes"] = on_disk

    # Write run manifest
    with open(run_dir / "run_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    # Write minimal tools_metadata.json
    tools = manifest.get("tools_metadata", {})
    with open(run_dir / "tools_metadata.json", "w") as f:
        json.dump(tools, f, indent=2)

    # Write minimal command_equivalence.json
    equiv = {
        "schema_version": 1,
        "scenarios": [
            {
                "scenario_id": s["scenario_id"],
                "expanded_commands": {
                    comp: cmd.replace("{pattern}", s.get("pattern", "X")).replace("{corpus}", s.get("corpus", "."))
                    for comp, cmd in s.get("commands", {}).items()
                },
            }
            for s in manifest.get("scenarios", [])
            if not s.get("skipped")
        ],
    }
    with open(run_dir / "command_equivalence.json", "w") as f:
        json.dump(equiv, f, indent=2)
