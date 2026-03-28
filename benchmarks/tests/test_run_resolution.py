#!/usr/bin/env python3
"""Tests for hardened benchmark latest-run resolution.

Ensures that ``--run latest`` resolves to canonical benchmark runs only
(not transient temp paths) and that validator workflows use robust
latest-run filtering.

Tests verify:
  - ``is_canonical_run_dir`` accepts valid timestamp-named directories.
  - ``is_canonical_run_dir`` rejects temp paths, symlinks, and non-matching names.
  - ``resolve_run_dir("latest")`` follows a valid symlink to a canonical dir.
  - ``resolve_run_dir("latest")`` ignores a symlink pointing to a temp dir.
  - ``resolve_run_dir("latest")`` falls back to the most recent canonical dir.
  - ``_update_latest_symlink`` does not update when target is a temp dir.
  - ``_update_latest_symlink`` updates normally for canonical directories.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "benchmarks"))

from run_resolution import (
    _CANONICAL_RUN_ID_RE,
    is_canonical_run_dir,
    resolve_run_dir,
)


# ---------------------------------------------------------------------------
# is_canonical_run_dir
# ---------------------------------------------------------------------------


class TestIsCanonicalRunDir:
    """Unit tests for the canonical run directory predicate."""

    def test_valid_timestamp_dir(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "20260305T152433Z"
        run_dir.mkdir()
        assert is_canonical_run_dir(run_dir, base=tmp_path)

    def test_rejects_non_timestamp_name(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "my-run"
        run_dir.mkdir()
        assert not is_canonical_run_dir(run_dir, base=tmp_path)

    def test_rejects_latest_symlink(self, tmp_path: Path) -> None:
        """A symlink named 'latest' is not itself a canonical dir."""
        real = tmp_path / "20260305T152433Z"
        real.mkdir()
        link = tmp_path / "latest"
        link.symlink_to(real.name)
        # The symlink itself is not canonical (we want the target).
        assert not is_canonical_run_dir(link, base=tmp_path)

    def test_rejects_dir_outside_base(self, tmp_path: Path) -> None:
        """A directory with a valid name but outside the base is rejected."""
        base = tmp_path / "base"
        base.mkdir()
        outside = tmp_path / "20260305T152433Z"
        outside.mkdir()
        assert not is_canonical_run_dir(outside, base=base)

    def test_rejects_nested_dir(self, tmp_path: Path) -> None:
        """A deeply nested directory (not a direct child) is rejected."""
        nested = tmp_path / "sub" / "20260305T152433Z"
        nested.mkdir(parents=True)
        assert not is_canonical_run_dir(nested, base=tmp_path)

    def test_rejects_temp_path(self, tmp_path: Path) -> None:
        """A typical pytest tmp_path directory is rejected."""
        base = tmp_path / "benchmarks_out"
        base.mkdir()
        temp_run = tmp_path / "pytest-tmp-run"
        temp_run.mkdir()
        assert not is_canonical_run_dir(temp_run, base=base)

    def test_rejects_nonexistent_dir(self, tmp_path: Path) -> None:
        missing = tmp_path / "20260305T000000Z"
        assert not is_canonical_run_dir(missing, base=tmp_path)

    def test_rejects_file_with_valid_name(self, tmp_path: Path) -> None:
        """A file (not directory) with a timestamp name is rejected."""
        f = tmp_path / "20260305T152433Z"
        f.write_text("not a dir")
        assert not is_canonical_run_dir(f, base=tmp_path)


# ---------------------------------------------------------------------------
# _CANONICAL_RUN_ID_RE
# ---------------------------------------------------------------------------


class TestCanonicalRunIdRegex:
    """Validate the timestamp regex pattern."""

    def test_matches_valid_ids(self) -> None:
        assert _CANONICAL_RUN_ID_RE.match("20260305T152433Z")
        assert _CANONICAL_RUN_ID_RE.match("20240101T000000Z")

    def test_rejects_invalid_ids(self) -> None:
        assert not _CANONICAL_RUN_ID_RE.match("latest")
        assert not _CANONICAL_RUN_ID_RE.match("my-run-id")
        assert not _CANONICAL_RUN_ID_RE.match("20260305")
        assert not _CANONICAL_RUN_ID_RE.match("")
        assert not _CANONICAL_RUN_ID_RE.match("test_command_equivalence_artif0")


# ---------------------------------------------------------------------------
# resolve_run_dir
# ---------------------------------------------------------------------------


class TestResolveRunDir:
    """Tests for the hardened resolve_run_dir function."""

    def test_explicit_run_dir_returned_directly(self, tmp_path: Path) -> None:
        """When --run-dir is given, it is returned as-is."""
        result = resolve_run_dir(None, str(tmp_path), benchmarks_out=tmp_path)
        assert result == tmp_path

    def test_explicit_run_id(self, tmp_path: Path) -> None:
        """An explicit run ID becomes a child of benchmarks_out."""
        result = resolve_run_dir("20260305T152433Z", None, benchmarks_out=tmp_path)
        assert result == tmp_path / "20260305T152433Z"

    def test_latest_follows_valid_symlink(self, tmp_path: Path) -> None:
        """``latest`` follows a symlink when it points to a canonical dir."""
        canonical = tmp_path / "20260305T152433Z"
        canonical.mkdir()
        link = tmp_path / "latest"
        link.symlink_to(canonical.name)

        result = resolve_run_dir("latest", None, benchmarks_out=tmp_path)
        assert result == canonical.resolve()

    def test_latest_ignores_temp_symlink(self, tmp_path: Path) -> None:
        """``latest`` ignores a symlink pointing to a temp directory."""
        # Create a canonical run dir for fallback.
        canonical = tmp_path / "20260305T100000Z"
        canonical.mkdir()

        # Create a broken symlink pointing to a temp path (outside base).
        temp_target = tmp_path / "temp_stuff" / "pytest-run"
        temp_target.mkdir(parents=True)
        link = tmp_path / "latest"
        link.symlink_to(os.path.relpath(temp_target, tmp_path))

        result = resolve_run_dir("latest", None, benchmarks_out=tmp_path)
        assert result == canonical.resolve()

    def test_latest_fallback_picks_most_recent(self, tmp_path: Path) -> None:
        """Without a symlink, ``latest`` picks the most recent canonical dir."""
        (tmp_path / "20260305T100000Z").mkdir()
        (tmp_path / "20260305T200000Z").mkdir()
        (tmp_path / "20260305T150000Z").mkdir()

        result = resolve_run_dir("latest", None, benchmarks_out=tmp_path)
        assert result.name == "20260305T200000Z"

    def test_latest_fallback_ignores_non_canonical_dirs(self, tmp_path: Path) -> None:
        """Non-canonical directory names are ignored during fallback scan."""
        (tmp_path / "20260305T100000Z").mkdir()
        (tmp_path / "some-temp-dir").mkdir()
        (tmp_path / "pytest-run-12345").mkdir()

        result = resolve_run_dir("latest", None, benchmarks_out=tmp_path)
        assert result.name == "20260305T100000Z"

    def test_latest_exits_when_no_canonical_dirs(self, tmp_path: Path) -> None:
        """Exits with code 2 when no canonical directories exist."""
        (tmp_path / "some-temp-dir").mkdir()

        with pytest.raises(SystemExit) as exc_info:
            resolve_run_dir("latest", None, benchmarks_out=tmp_path)
        assert exc_info.value.code == 2

    def test_latest_exits_when_base_missing(self, tmp_path: Path) -> None:
        """Exits with code 2 when the output base directory doesn't exist."""
        nonexistent = tmp_path / "does_not_exist"

        with pytest.raises(SystemExit) as exc_info:
            resolve_run_dir("latest", None, benchmarks_out=nonexistent)
        assert exc_info.value.code == 2

    def test_latest_symlink_pointing_to_non_timestamp_dir(self, tmp_path: Path) -> None:
        """Symlink to a non-timestamp child is ignored; fallback is used."""
        non_timestamp = tmp_path / "my-custom-run"
        non_timestamp.mkdir()
        canonical = tmp_path / "20260305T120000Z"
        canonical.mkdir()

        link = tmp_path / "latest"
        link.symlink_to("my-custom-run")

        result = resolve_run_dir("latest", None, benchmarks_out=tmp_path)
        assert result == canonical.resolve()

    def test_latest_ignores_symlinks_in_fallback_scan(self, tmp_path: Path) -> None:
        """The fallback scan should skip symlinks (even valid-looking ones)."""
        canonical = tmp_path / "20260305T100000Z"
        canonical.mkdir()

        # Create a symlink with a canonical-looking name.
        alias = tmp_path / "20260305T999999Z"
        alias.symlink_to(canonical.name)

        result = resolve_run_dir("latest", None, benchmarks_out=tmp_path)
        # Should pick the real directory, not the symlink alias.
        assert result.name == "20260305T100000Z"


# ---------------------------------------------------------------------------
# _update_latest_symlink hardening
# ---------------------------------------------------------------------------


class TestUpdateLatestSymlink:
    """Verify _update_latest_symlink guards against non-canonical targets."""

    def test_skips_update_for_temp_dir(self, tmp_path: Path) -> None:
        """Symlink should NOT be created for a temp-path target."""
        from harness import _update_latest_symlink

        out_base = tmp_path / "out"
        out_base.mkdir()

        # Existing valid symlink.
        canonical = out_base / "20260305T100000Z"
        canonical.mkdir()
        latest = out_base / "latest"
        latest.symlink_to(canonical.name)

        # Attempt to update with a temp dir (not inside out_base).
        temp_run = tmp_path / "pytest-tmp-run"
        temp_run.mkdir()
        _update_latest_symlink(out_base, temp_run)

        # Symlink should still point to the original canonical dir.
        assert latest.is_symlink()
        assert latest.resolve() == canonical.resolve()

    def test_updates_for_canonical_dir(self, tmp_path: Path) -> None:
        """Symlink IS updated when pointing to a canonical run dir."""
        from harness import _update_latest_symlink

        out_base = tmp_path / "out"
        out_base.mkdir()

        old_run = out_base / "20260305T100000Z"
        old_run.mkdir()
        new_run = out_base / "20260305T200000Z"
        new_run.mkdir()

        latest = out_base / "latest"
        latest.symlink_to(old_run.name)

        _update_latest_symlink(out_base, new_run)

        assert latest.is_symlink()
        assert latest.resolve() == new_run.resolve()

    def test_creates_symlink_when_none_exists(self, tmp_path: Path) -> None:
        """Symlink is created when no prior symlink exists."""
        from harness import _update_latest_symlink

        out_base = tmp_path / "out"
        out_base.mkdir()

        run_dir = out_base / "20260305T100000Z"
        run_dir.mkdir()

        _update_latest_symlink(out_base, run_dir)

        latest = out_base / "latest"
        assert latest.is_symlink()
        assert latest.resolve() == run_dir.resolve()

    def test_no_symlink_for_non_matching_name(self, tmp_path: Path) -> None:
        """Symlink not created when dir name doesn't match timestamp pattern."""
        from harness import _update_latest_symlink

        out_base = tmp_path / "out"
        out_base.mkdir()

        run_dir = out_base / "custom-run-name"
        run_dir.mkdir()

        _update_latest_symlink(out_base, run_dir)

        latest = out_base / "latest"
        assert not latest.exists()
