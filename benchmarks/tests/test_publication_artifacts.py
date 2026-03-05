#!/usr/bin/env python3
"""Tests for publication artifact bundling, checksum verification,
and inclusion/exclusion ledger completeness.

VAL-BENCH-008: Raw benchmark artifacts are publishable.
VAL-CROSS-006: Scenario coverage is complete in published results.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "benchmarks"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=False, ensure_ascii=False)
        f.write("\n")


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_minimal_run(run_dir: Path, *, schema_version: int = 2) -> dict[str, Any]:
    """Create a minimal benchmark run directory with required artifacts."""
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema_version": schema_version,
        "run_id": "20260305T120000Z",
        "run_type": "local",
        "timestamp": "2026-03-05T12:00:00+00:00",
        "commit_sha": "abc123def456",
        "comparators": ["ag", "rust-ag", "rg", "ugrep"],
        "manifest_hashes": {
            "scenarios": "scenariohash123",
            "queries": "queryhash456",
            "corpus": "corpushash789",
        },
        "environment": {
            "timestamp": "2026-03-05T12:00:00+00:00",
            "platform": {
                "system": "Darwin",
                "release": "25.3.0",
                "machine": "arm64",
                "python": "3.14.2",
            },
            "commit_sha": "abc123def456",
        },
        "tools_metadata": {
            "comparators": {
                "ag": {"binary_path": "/usr/bin/ag", "version": "2.2.0", "version_raw": "ag 2.2.0"},
                "rust-ag": {"binary_path": "/usr/bin/rust-ag", "version": "0.1.0", "version_raw": "rust-ag 0.1.0"},
                "rg": {"binary_path": "/usr/bin/rg", "version": "15.1.0", "version_raw": "ripgrep 15.1.0"},
                "ugrep": {"binary_path": "/usr/bin/ugrep", "version": "7.0.1", "version_raw": "ugrep 7.0.1"},
            },
            "timestamp": "2026-03-05T12:00:00+00:00",
            "commit_sha": "abc123def456",
        },
        "sampling_config": {
            "warmup_iterations": 2,
            "measured_iterations": 5,
            "total_iterations": 7,
        },
        "execution_schedule": {
            "schedule": "interleaved_random",
            "seed": 12345,
            "entries": [],
        },
        "scenario_count": 2,
        "cell_totals": {"total": 8, "executed": 7, "skipped": 1, "errors": 0},
        "scenarios": [
            {
                "scenario_id": "literal-simple",
                "query_id": "q-literal-simple",
                "pattern": "test",
                "corpus": ".",
                "commands": {
                    "ag": "ag --nocolor test .",
                    "rust-ag": "rust-ag --nocolor test .",
                    "rg": "rg --color=never test .",
                    "ugrep": "ugrep --color=never test .",
                },
                "results": {
                    "ag": {"command": "ag --nocolor test .", "exit_code": 0, "elapsed_s": 0.1,
                           "stdout_hash": "aaa", "stdout_sorted_hash": "bbb", "stdout_bytes": 100},
                    "rust-ag": {"command": "rust-ag --nocolor test .", "exit_code": 0, "elapsed_s": 0.05,
                                "stdout_hash": "aaa", "stdout_sorted_hash": "bbb", "stdout_bytes": 100},
                    "rg": {"command": "rg --color=never test .", "exit_code": 0, "elapsed_s": 0.03,
                           "stdout_hash": "ccc", "stdout_sorted_hash": "ddd", "stdout_bytes": 120},
                    "ugrep": {"command": "ugrep --color=never test .", "exit_code": 0, "elapsed_s": 0.04,
                              "stdout_hash": "eee", "stdout_sorted_hash": "fff", "stdout_bytes": 110},
                },
                "skipped": False,
            },
            {
                "scenario_id": "edge-one-device",
                "skipped": True,
                "skip_reason": "Cross-device mount point not available",
            },
        ],
    }

    tools_metadata = manifest["tools_metadata"]
    environment_metadata = {
        "schema_version": 1,
        "timestamp": "2026-03-05T12:00:00+00:00",
        "commit_sha": "abc123def456",
        "platform": {"system": "Darwin", "release": "25.3.0", "machine": "arm64", "python": "3.14.2"},
        "cpu": {"brand": "Apple M2", "cores_physical": 8, "cores_logical": 8},
        "memory": {"total_bytes": 17179869184, "total_human": "16.00 GB"},
        "toolchains": {"rust": "1.82.0", "python": "3.14.2"},
    }
    command_equivalence = {
        "schema_version": 1,
        "description": "Command equivalence expansion",
        "timestamp": "2026-03-05T12:00:00+00:00",
        "scenario_count": 1,
        "scenarios": [
            {
                "scenario_id": "literal-simple",
                "query_id": "q-literal-simple",
                "pattern": "test",
                "corpus": ".",
                "templates": {"ag": "ag --nocolor {pattern} {corpus}"},
                "expanded_commands": {"ag": "ag --nocolor test ."},
            },
        ],
    }
    correctness_gate = {
        "schema_version": 1,
        "gate": "pass",
        "timestamp": "2026-03-05T12:00:00+00:00",
        "commit_sha": "abc123def456",
        "run_id": "20260305T120000Z",
        "scenarios_checked": 1,
        "scenarios_passed": 1,
        "scenarios_failed": 0,
        "scenarios_skipped": 1,
    }
    sampling_validation = {
        "schema_version": 1,
        "gate": "pass",
        "timestamp": "2026-03-05T12:00:00+00:00",
        "run_id": "20260305T120000Z",
    }

    _write_json(run_dir / "run_manifest.json", manifest)
    _write_json(run_dir / "tools_metadata.json", tools_metadata)
    _write_json(run_dir / "environment_metadata.json", environment_metadata)
    _write_json(run_dir / "command_equivalence.json", command_equivalence)
    _write_json(run_dir / "correctness_gate.json", correctness_gate)
    _write_json(run_dir / "sampling_validation.json", sampling_validation)

    return manifest


# ===========================================================================
# Test: Publication Manifest Structure (VAL-BENCH-008)
# ===========================================================================


class TestPublicationManifestStructure:
    """Publication manifest includes all required raw and derived artifacts."""

    def test_publication_manifest_has_required_fields(self, tmp_path: Path) -> None:
        """Publication manifest has schema_version, run_id, commit_sha,
        artifacts list, checksums, and inclusion_exclusion_ledger."""
        from package_publication_artifacts import package_publication_artifacts

        run_dir = tmp_path / "run"
        _make_minimal_run(run_dir)

        result = package_publication_artifacts(run_dir, tmp_path / "pub")
        pub_manifest = _load_json(tmp_path / "pub" / "publication_manifest.json")

        required = [
            "schema_version",
            "run_id",
            "commit_sha",
            "timestamp",
            "artifacts",
            "checksums",
            "inclusion_exclusion_ledger",
        ]
        for field in required:
            assert field in pub_manifest, f"Missing required field: {field}"

    def test_publication_manifest_lists_raw_artifacts(self, tmp_path: Path) -> None:
        """Publication manifest lists all raw benchmark artifacts."""
        from package_publication_artifacts import package_publication_artifacts

        run_dir = tmp_path / "run"
        _make_minimal_run(run_dir)

        result = package_publication_artifacts(run_dir, tmp_path / "pub")
        pub_manifest = _load_json(tmp_path / "pub" / "publication_manifest.json")

        artifact_names = {a["name"] for a in pub_manifest["artifacts"]}
        required_artifacts = {
            "run_manifest.json",
            "tools_metadata.json",
            "environment_metadata.json",
            "command_equivalence.json",
            "correctness_gate.json",
            "sampling_validation.json",
        }
        for ra in required_artifacts:
            assert ra in artifact_names, f"Missing artifact: {ra}"

    def test_publication_manifest_lists_derived_artifacts(self, tmp_path: Path) -> None:
        """Publication manifest lists derived artifacts (checksums, ledger)."""
        from package_publication_artifacts import package_publication_artifacts

        run_dir = tmp_path / "run"
        _make_minimal_run(run_dir)

        result = package_publication_artifacts(run_dir, tmp_path / "pub")
        pub_manifest = _load_json(tmp_path / "pub" / "publication_manifest.json")

        artifact_names = {a["name"] for a in pub_manifest["artifacts"]}
        assert "checksums.sha256" in artifact_names
        assert "inclusion_exclusion_ledger.json" in artifact_names

    def test_all_listed_artifacts_exist_on_disk(self, tmp_path: Path) -> None:
        """Every artifact referenced in the publication manifest exists on disk."""
        from package_publication_artifacts import package_publication_artifacts

        run_dir = tmp_path / "run"
        _make_minimal_run(run_dir)

        pub_dir = tmp_path / "pub"
        package_publication_artifacts(run_dir, pub_dir)
        pub_manifest = _load_json(pub_dir / "publication_manifest.json")

        for artifact in pub_manifest["artifacts"]:
            artifact_path = pub_dir / artifact["name"]
            assert artifact_path.exists(), f"Artifact missing on disk: {artifact['name']}"


# ===========================================================================
# Test: Checksum Generation and Verification
# ===========================================================================


class TestChecksumGenerationVerification:
    """Checksums are generated and verified (VAL-BENCH-008)."""

    def test_checksums_file_generated(self, tmp_path: Path) -> None:
        """checksums.sha256 file is generated in the publication bundle."""
        from package_publication_artifacts import package_publication_artifacts

        run_dir = tmp_path / "run"
        _make_minimal_run(run_dir)

        pub_dir = tmp_path / "pub"
        package_publication_artifacts(run_dir, pub_dir)

        assert (pub_dir / "checksums.sha256").exists()

    def test_checksums_cover_all_raw_artifacts(self, tmp_path: Path) -> None:
        """checksums.sha256 contains entries for all raw artifacts."""
        from package_publication_artifacts import package_publication_artifacts

        run_dir = tmp_path / "run"
        _make_minimal_run(run_dir)

        pub_dir = tmp_path / "pub"
        package_publication_artifacts(run_dir, pub_dir)

        checksums_text = (pub_dir / "checksums.sha256").read_text()
        lines = [l.strip() for l in checksums_text.strip().splitlines() if l.strip()]

        # Each line should be "hash  filename".
        for line in lines:
            parts = line.split("  ", 1)
            assert len(parts) == 2, f"Malformed checksum line: {line}"
            assert len(parts[0]) == 64, f"Not a SHA-256 hash: {parts[0]}"

        checksummed_files = {line.split("  ", 1)[1] for line in lines}
        required = {
            "run_manifest.json",
            "tools_metadata.json",
            "environment_metadata.json",
            "command_equivalence.json",
            "correctness_gate.json",
        }
        for r in required:
            assert r in checksummed_files, f"Missing checksum for: {r}"

    def test_verify_checksums_passes_for_valid_bundle(self, tmp_path: Path) -> None:
        """verify_checksums.py passes when all checksums match."""
        from package_publication_artifacts import package_publication_artifacts
        from verify_checksums import verify_checksums

        run_dir = tmp_path / "run"
        _make_minimal_run(run_dir)

        pub_dir = tmp_path / "pub"
        package_publication_artifacts(run_dir, pub_dir)

        result = verify_checksums(pub_dir / "publication_manifest.json")
        assert result["gate"] == "pass"
        assert result["mismatches"] == []

    def test_verify_checksums_fails_on_tampered_artifact(self, tmp_path: Path) -> None:
        """verify_checksums.py fails when an artifact has been tampered with."""
        from package_publication_artifacts import package_publication_artifacts
        from verify_checksums import verify_checksums

        run_dir = tmp_path / "run"
        _make_minimal_run(run_dir)

        pub_dir = tmp_path / "pub"
        package_publication_artifacts(run_dir, pub_dir)

        # Tamper with an artifact.
        tampered = pub_dir / "run_manifest.json"
        tampered.write_text("TAMPERED CONTENT")

        result = verify_checksums(pub_dir / "publication_manifest.json")
        assert result["gate"] == "fail"
        assert len(result["mismatches"]) > 0
        assert any("run_manifest.json" in m["file"] for m in result["mismatches"])

    def test_verify_checksums_fails_on_missing_artifact(self, tmp_path: Path) -> None:
        """verify_checksums.py fails when a listed artifact is missing."""
        from package_publication_artifacts import package_publication_artifacts
        from verify_checksums import verify_checksums

        run_dir = tmp_path / "run"
        _make_minimal_run(run_dir)

        pub_dir = tmp_path / "pub"
        package_publication_artifacts(run_dir, pub_dir)

        # Remove an artifact.
        (pub_dir / "tools_metadata.json").unlink()

        result = verify_checksums(pub_dir / "publication_manifest.json")
        assert result["gate"] == "fail"
        assert len(result["missing"]) > 0


# ===========================================================================
# Test: Inclusion/Exclusion Ledger (VAL-CROSS-006)
# ===========================================================================


class TestInclusionExclusionLedger:
    """Published scenario inclusion/exclusion ledger is complete."""

    def test_ledger_generated(self, tmp_path: Path) -> None:
        """inclusion_exclusion_ledger.json is generated."""
        from package_publication_artifacts import package_publication_artifacts

        run_dir = tmp_path / "run"
        _make_minimal_run(run_dir)

        pub_dir = tmp_path / "pub"
        package_publication_artifacts(run_dir, pub_dir)

        assert (pub_dir / "inclusion_exclusion_ledger.json").exists()

    def test_ledger_has_required_fields(self, tmp_path: Path) -> None:
        """Ledger has schema_version, run_id, scenarios, summary."""
        from package_publication_artifacts import package_publication_artifacts

        run_dir = tmp_path / "run"
        _make_minimal_run(run_dir)

        pub_dir = tmp_path / "pub"
        package_publication_artifacts(run_dir, pub_dir)

        ledger = _load_json(pub_dir / "inclusion_exclusion_ledger.json")
        required = ["schema_version", "run_id", "scenarios", "summary"]
        for field in required:
            assert field in ledger, f"Missing ledger field: {field}"

    def test_ledger_covers_all_run_scenarios(self, tmp_path: Path) -> None:
        """Ledger references every scenario from the run manifest."""
        from package_publication_artifacts import package_publication_artifacts

        run_dir = tmp_path / "run"
        manifest = _make_minimal_run(run_dir)

        # Provide a scenarios manifest matching only the run's scenarios
        # so the ledger doesn't pick up the real on-disk scenarios.json.
        scenarios_manifest = {
            "schema_version": 1,
            "manifest_hash": "scenariohash123",
            "scenario_count": 2,
            "scenarios": [
                {"id": "literal-simple", "description": "Simple literal"},
                {"id": "edge-one-device", "description": "One device edge case"},
            ],
        }
        scenarios_path = tmp_path / "scenarios.json"
        _write_json(scenarios_path, scenarios_manifest)

        pub_dir = tmp_path / "pub"
        package_publication_artifacts(
            run_dir, pub_dir, scenarios_manifest_path=scenarios_path
        )

        ledger = _load_json(pub_dir / "inclusion_exclusion_ledger.json")
        ledger_scenario_ids = {s["scenario_id"] for s in ledger["scenarios"]}
        manifest_scenario_ids = {s["scenario_id"] for s in manifest["scenarios"]}

        # Ledger should cover at least all run manifest scenarios.
        assert manifest_scenario_ids.issubset(ledger_scenario_ids)

    def test_ledger_marks_skipped_as_excluded(self, tmp_path: Path) -> None:
        """Skipped scenarios are marked as excluded with reason."""
        from package_publication_artifacts import package_publication_artifacts

        run_dir = tmp_path / "run"
        _make_minimal_run(run_dir)

        pub_dir = tmp_path / "pub"
        package_publication_artifacts(run_dir, pub_dir)

        ledger = _load_json(pub_dir / "inclusion_exclusion_ledger.json")
        excluded = [s for s in ledger["scenarios"] if s["status"] == "excluded"]
        assert len(excluded) >= 1
        for ex in excluded:
            assert "reason" in ex and ex["reason"], f"Excluded scenario missing reason: {ex}"

    def test_ledger_marks_included_scenarios(self, tmp_path: Path) -> None:
        """Non-skipped scenarios are marked as included."""
        from package_publication_artifacts import package_publication_artifacts

        run_dir = tmp_path / "run"
        _make_minimal_run(run_dir)

        pub_dir = tmp_path / "pub"
        package_publication_artifacts(run_dir, pub_dir)

        ledger = _load_json(pub_dir / "inclusion_exclusion_ledger.json")
        included = [s for s in ledger["scenarios"] if s["status"] == "included"]
        assert len(included) >= 1

    def test_ledger_summary_counts_are_correct(self, tmp_path: Path) -> None:
        """Ledger summary has correct included/excluded counts."""
        from package_publication_artifacts import package_publication_artifacts

        run_dir = tmp_path / "run"
        _make_minimal_run(run_dir)

        pub_dir = tmp_path / "pub"
        package_publication_artifacts(run_dir, pub_dir)

        ledger = _load_json(pub_dir / "inclusion_exclusion_ledger.json")
        summary = ledger["summary"]

        included = len([s for s in ledger["scenarios"] if s["status"] == "included"])
        excluded = len([s for s in ledger["scenarios"] if s["status"] == "excluded"])

        assert summary["included"] == included
        assert summary["excluded"] == excluded
        assert summary["total"] == included + excluded

    def test_ledger_references_full_scenario_matrix(self, tmp_path: Path) -> None:
        """Ledger includes per-comparator status for included scenarios."""
        from package_publication_artifacts import package_publication_artifacts

        run_dir = tmp_path / "run"
        _make_minimal_run(run_dir)

        pub_dir = tmp_path / "pub"
        package_publication_artifacts(run_dir, pub_dir)

        ledger = _load_json(pub_dir / "inclusion_exclusion_ledger.json")
        included = [s for s in ledger["scenarios"] if s["status"] == "included"]
        for entry in included:
            assert "comparators" in entry, f"Missing comparators in {entry['scenario_id']}"
            assert len(entry["comparators"]) > 0


# ===========================================================================
# Test: Publication Bundle from Scenarios Manifest (VAL-CROSS-006)
# ===========================================================================


class TestPublicationScenariosManifestCoverage:
    """Publication ledger references the full registered scenario matrix."""

    def test_ledger_covers_registered_scenarios_when_provided(self, tmp_path: Path) -> None:
        """When a scenarios manifest is available, ledger covers ALL registered
        scenarios (not just those that were run)."""
        from package_publication_artifacts import package_publication_artifacts

        run_dir = tmp_path / "run"
        manifest = _make_minimal_run(run_dir)

        # Create a scenarios manifest with more scenarios than the run.
        scenarios_manifest = {
            "schema_version": 1,
            "manifest_hash": "scenariohash123",
            "scenario_count": 3,
            "scenarios": [
                {"id": "literal-simple", "description": "Simple literal"},
                {"id": "edge-one-device", "description": "One device edge case"},
                {"id": "regex-complex", "description": "Complex regex"},
            ],
        }
        scenarios_path = tmp_path / "scenarios.json"
        _write_json(scenarios_path, scenarios_manifest)

        pub_dir = tmp_path / "pub"
        package_publication_artifacts(
            run_dir, pub_dir, scenarios_manifest_path=scenarios_path
        )

        ledger = _load_json(pub_dir / "inclusion_exclusion_ledger.json")
        ledger_ids = {s["scenario_id"] for s in ledger["scenarios"]}

        # Should include all registered scenarios.
        assert "literal-simple" in ledger_ids
        assert "edge-one-device" in ledger_ids
        assert "regex-complex" in ledger_ids

    def test_unrun_scenarios_marked_as_excluded(self, tmp_path: Path) -> None:
        """Scenarios in the manifest but not in the run are excluded."""
        from package_publication_artifacts import package_publication_artifacts

        run_dir = tmp_path / "run"
        _make_minimal_run(run_dir)

        scenarios_manifest = {
            "schema_version": 1,
            "manifest_hash": "scenariohash123",
            "scenario_count": 3,
            "scenarios": [
                {"id": "literal-simple", "description": "Simple literal"},
                {"id": "edge-one-device", "description": "One device edge case"},
                {"id": "regex-complex", "description": "Complex regex"},
            ],
        }
        scenarios_path = tmp_path / "scenarios.json"
        _write_json(scenarios_path, scenarios_manifest)

        pub_dir = tmp_path / "pub"
        package_publication_artifacts(
            run_dir, pub_dir, scenarios_manifest_path=scenarios_path
        )

        ledger = _load_json(pub_dir / "inclusion_exclusion_ledger.json")
        regex_complex = [s for s in ledger["scenarios"] if s["scenario_id"] == "regex-complex"]
        assert len(regex_complex) == 1
        assert regex_complex[0]["status"] == "excluded"
        assert "not present in run" in regex_complex[0]["reason"].lower()


# ===========================================================================
# Test: End-to-end CLI invocation
# ===========================================================================


class TestPublicationCLI:
    """The package_publication_artifacts.py CLI works end-to-end."""

    def test_cli_with_run_dir(self, tmp_path: Path) -> None:
        """CLI packages artifacts given --run-dir."""
        import subprocess

        run_dir = tmp_path / "run"
        _make_minimal_run(run_dir)

        pub_dir = tmp_path / "pub"
        result = subprocess.run(
            [
                "python3",
                str(REPO_ROOT / "benchmarks" / "package_publication_artifacts.py"),
                "--run-dir", str(run_dir),
                "--output-dir", str(pub_dir),
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, f"CLI failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        assert (pub_dir / "publication_manifest.json").exists()
        assert (pub_dir / "checksums.sha256").exists()
        assert (pub_dir / "inclusion_exclusion_ledger.json").exists()


class TestVerifyChecksumsCLI:
    """The verify_checksums.py CLI works end-to-end."""

    def test_cli_verify_valid_bundle(self, tmp_path: Path) -> None:
        """CLI exits 0 for valid bundle."""
        import subprocess

        run_dir = tmp_path / "run"
        _make_minimal_run(run_dir)

        pub_dir = tmp_path / "pub"
        # First package.
        subprocess.run(
            [
                "python3",
                str(REPO_ROOT / "benchmarks" / "package_publication_artifacts.py"),
                "--run-dir", str(run_dir),
                "--output-dir", str(pub_dir),
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )

        # Then verify.
        result = subprocess.run(
            [
                "python3",
                str(REPO_ROOT / "benchmarks" / "verify_checksums.py"),
                "--manifest", str(pub_dir / "publication_manifest.json"),
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, f"Verify failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
