#!/usr/bin/env python3
"""Tests for environment metadata validation.

VAL-BENCH-005: Environment metadata is complete.
    Each benchmark run captures environment metadata (OS, CPU, memory,
    toolchains, commit SHA, timestamp).

Tests verify:
  - Schema validation passes for valid metadata.
  - Schema validation fails when required fields are missing.
  - Memory and CPU info are captured by the collection function.
  - Toolchain info (Rust, Python) is captured.
  - Validator exits non-zero on bad metadata.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "benchmarks"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_valid_env_metadata() -> dict:
    """Build a valid environment metadata dict."""
    return {
        "schema_version": 1,
        "timestamp": "2026-03-05T00:00:00+00:00",
        "commit_sha": "abc123def456",
        "platform": {
            "system": "Darwin",
            "release": "25.3.0",
            "machine": "arm64",
            "python": "3.14.2",
        },
        "cpu": {
            "brand": "Apple M3 Pro",
            "cores_physical": 12,
            "cores_logical": 12,
        },
        "memory": {
            "total_bytes": 36_000_000_000,
            "total_human": "33.5 GiB",
        },
        "toolchains": {
            "rust": "rustc 1.80.0",
            "cargo": "cargo 1.80.0",
            "python": "3.14.2",
        },
    }


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestEnvMetadataSchema:
    """Tests for environment metadata schema validation."""

    def test_valid_metadata_passes(self):
        """Valid metadata passes schema validation."""
        from validate_env_metadata import validate_env_metadata_schema

        meta = _make_valid_env_metadata()
        errors = validate_env_metadata_schema(meta)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_missing_timestamp_fails(self):
        """Missing timestamp is detected."""
        from validate_env_metadata import validate_env_metadata_schema

        meta = _make_valid_env_metadata()
        del meta["timestamp"]
        errors = validate_env_metadata_schema(meta)
        assert any("timestamp" in e for e in errors)

    def test_missing_commit_sha_fails(self):
        """Missing commit_sha is detected."""
        from validate_env_metadata import validate_env_metadata_schema

        meta = _make_valid_env_metadata()
        del meta["commit_sha"]
        errors = validate_env_metadata_schema(meta)
        assert any("commit_sha" in e for e in errors)

    def test_missing_platform_fails(self):
        """Missing platform block is detected."""
        from validate_env_metadata import validate_env_metadata_schema

        meta = _make_valid_env_metadata()
        del meta["platform"]
        errors = validate_env_metadata_schema(meta)
        assert any("platform" in e for e in errors)

    def test_missing_cpu_fails(self):
        """Missing cpu block is detected."""
        from validate_env_metadata import validate_env_metadata_schema

        meta = _make_valid_env_metadata()
        del meta["cpu"]
        errors = validate_env_metadata_schema(meta)
        assert any("cpu" in e for e in errors)

    def test_missing_memory_fails(self):
        """Missing memory block is detected."""
        from validate_env_metadata import validate_env_metadata_schema

        meta = _make_valid_env_metadata()
        del meta["memory"]
        errors = validate_env_metadata_schema(meta)
        assert any("memory" in e for e in errors)

    def test_missing_toolchains_fails(self):
        """Missing toolchains block is detected."""
        from validate_env_metadata import validate_env_metadata_schema

        meta = _make_valid_env_metadata()
        del meta["toolchains"]
        errors = validate_env_metadata_schema(meta)
        assert any("toolchains" in e for e in errors)

    def test_missing_platform_subfield_fails(self):
        """Missing platform.system is detected."""
        from validate_env_metadata import validate_env_metadata_schema

        meta = _make_valid_env_metadata()
        del meta["platform"]["system"]
        errors = validate_env_metadata_schema(meta)
        assert any("system" in e for e in errors)

    def test_missing_cpu_brand_fails(self):
        """Missing cpu.brand is detected."""
        from validate_env_metadata import validate_env_metadata_schema

        meta = _make_valid_env_metadata()
        del meta["cpu"]["brand"]
        errors = validate_env_metadata_schema(meta)
        assert any("brand" in e for e in errors)

    def test_missing_memory_total_bytes_fails(self):
        """Missing memory.total_bytes is detected."""
        from validate_env_metadata import validate_env_metadata_schema

        meta = _make_valid_env_metadata()
        del meta["memory"]["total_bytes"]
        errors = validate_env_metadata_schema(meta)
        assert any("total_bytes" in e for e in errors)


class TestEnvMetadataCollection:
    """Tests for environment metadata collection function."""

    def test_collect_returns_all_required_fields(self):
        """collect_environment_metadata returns all required fields."""
        from validate_env_metadata import collect_full_environment_metadata

        meta = collect_full_environment_metadata()
        assert "schema_version" in meta
        assert "timestamp" in meta
        assert "commit_sha" in meta
        assert "platform" in meta
        assert "cpu" in meta
        assert "memory" in meta
        assert "toolchains" in meta

    def test_collect_cpu_has_brand(self):
        """CPU info includes a brand string."""
        from validate_env_metadata import collect_full_environment_metadata

        meta = collect_full_environment_metadata()
        assert meta["cpu"]["brand"], "CPU brand should not be empty"

    def test_collect_cpu_has_cores(self):
        """CPU info includes core counts."""
        from validate_env_metadata import collect_full_environment_metadata

        meta = collect_full_environment_metadata()
        assert meta["cpu"]["cores_physical"] > 0
        assert meta["cpu"]["cores_logical"] > 0

    def test_collect_memory_has_total(self):
        """Memory info includes total bytes > 0."""
        from validate_env_metadata import collect_full_environment_metadata

        meta = collect_full_environment_metadata()
        assert meta["memory"]["total_bytes"] > 0
        assert meta["memory"]["total_human"], "Human-readable memory should not be empty"

    def test_collect_toolchains_has_rust(self):
        """Toolchain info includes Rust version."""
        from validate_env_metadata import collect_full_environment_metadata

        meta = collect_full_environment_metadata()
        assert meta["toolchains"]["rust"], "Rust toolchain should be captured"

    def test_collect_toolchains_has_python(self):
        """Toolchain info includes Python version."""
        from validate_env_metadata import collect_full_environment_metadata

        meta = collect_full_environment_metadata()
        assert meta["toolchains"]["python"], "Python version should be captured"

    def test_collect_passes_own_schema(self):
        """Collected metadata passes its own schema validation."""
        from validate_env_metadata import (
            collect_full_environment_metadata,
            validate_env_metadata_schema,
        )

        meta = collect_full_environment_metadata()
        errors = validate_env_metadata_schema(meta)
        assert errors == [], f"Collected metadata fails schema: {errors}"


class TestEnvMetadataArtifact:
    """Tests for writing environment metadata artifact."""

    def test_write_artifact(self, tmp_path):
        """Environment metadata is written as a JSON artifact."""
        from validate_env_metadata import (
            collect_full_environment_metadata,
            write_env_metadata_artifact,
        )

        meta = collect_full_environment_metadata()
        write_env_metadata_artifact(meta, tmp_path)
        artifact = tmp_path / "environment_metadata.json"
        assert artifact.exists()
        data = json.loads(artifact.read_text())
        assert data["schema_version"] == 1
