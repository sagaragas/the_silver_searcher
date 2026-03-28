#!/usr/bin/env python3
"""Tests for the ``latest`` symlink created by run_matrix.

Verifies that the ``latest`` symlink resolves correctly for both default
(inside ``parity-artifacts/``) and custom ``--output-dir`` paths.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

# Import the function under test.
# We exercise it through run_matrix() by monkey-patching the heavy bits,
# but we can also directly test the symlink logic extracted into a helper.
# For now, test the end-to-end symlink resolution by calling the
# _update_latest_symlink helper that the fix introduces.

import importlib
import sys

# Ensure the scripts/parity directory is importable.
SCRIPTS_PARITY = Path(__file__).resolve().parent
if str(SCRIPTS_PARITY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PARITY))

import run_matrix  # noqa: E402


class TestLatestSymlinkResolution(unittest.TestCase):
    """Verify latest symlink targets resolve for default and custom dirs."""

    def setUp(self) -> None:
        """Create temporary directories simulating artifact structure."""
        self.tmpdir = Path(tempfile.mkdtemp(prefix="parity-symtest-"))
        self.artifacts_base = self.tmpdir / "parity-artifacts"
        self.artifacts_base.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _call_update_latest(self, artifacts_base: Path, run_dir: Path) -> None:
        """Call the symlink update helper."""
        run_matrix._update_latest_symlink(artifacts_base, run_dir)

    # --- Default output dir (run_dir inside artifacts_base) ----------------

    def test_default_output_dir_relative_symlink(self):
        """Default run dir inside artifacts_base gets a relative symlink."""
        run_dir = self.artifacts_base / "20260305T120000Z"
        run_dir.mkdir()
        self._call_update_latest(self.artifacts_base, run_dir)

        latest = self.artifacts_base / "latest"
        self.assertTrue(latest.is_symlink(), "latest symlink should exist")
        # Should be a relative target.
        target = os.readlink(str(latest))
        self.assertEqual(target, "20260305T120000Z")
        # Should resolve to the run dir.
        self.assertEqual(latest.resolve(), run_dir.resolve())

    def test_default_output_dir_symlink_replacement(self):
        """A second run replaces the existing latest symlink."""
        run1 = self.artifacts_base / "20260305T100000Z"
        run1.mkdir()
        self._call_update_latest(self.artifacts_base, run1)

        run2 = self.artifacts_base / "20260305T120000Z"
        run2.mkdir()
        self._call_update_latest(self.artifacts_base, run2)

        latest = self.artifacts_base / "latest"
        self.assertEqual(latest.resolve(), run2.resolve())

    # --- Custom output dir (run_dir outside artifacts_base) ----------------

    def test_custom_output_dir_symlink_resolves(self):
        """Custom output dir gets a symlink that actually resolves."""
        custom_dir = self.tmpdir / "custom-out"
        custom_dir.mkdir()
        self._call_update_latest(self.artifacts_base, custom_dir)

        latest = self.artifacts_base / "latest"
        self.assertTrue(latest.is_symlink(), "latest symlink should exist")
        # Must resolve to the custom directory.
        self.assertEqual(latest.resolve(), custom_dir.resolve())

    def test_custom_output_dir_absolute_target(self):
        """For a custom output dir outside artifacts_base, the symlink
        target must be resolvable (absolute or correct relative)."""
        custom_dir = self.tmpdir / "another-custom"
        custom_dir.mkdir()
        self._call_update_latest(self.artifacts_base, custom_dir)

        latest = self.artifacts_base / "latest"
        # readlink should give us something that resolves from the symlink's
        # parent directory.
        target = os.readlink(str(latest))
        resolved = (latest.parent / target).resolve()
        self.assertEqual(resolved, custom_dir.resolve())

    def test_custom_output_dir_deeply_nested(self):
        """Deeply nested custom dir resolves correctly."""
        custom_dir = self.tmpdir / "a" / "b" / "c" / "run-output"
        custom_dir.mkdir(parents=True)
        self._call_update_latest(self.artifacts_base, custom_dir)

        latest = self.artifacts_base / "latest"
        self.assertTrue(latest.is_symlink())
        self.assertEqual(latest.resolve(), custom_dir.resolve())

    def test_custom_output_dir_replacement(self):
        """Multiple custom dir runs update the symlink each time."""
        dir1 = self.tmpdir / "out1"
        dir1.mkdir()
        self._call_update_latest(self.artifacts_base, dir1)
        self.assertEqual((self.artifacts_base / "latest").resolve(), dir1.resolve())

        dir2 = self.tmpdir / "out2"
        dir2.mkdir()
        self._call_update_latest(self.artifacts_base, dir2)
        self.assertEqual((self.artifacts_base / "latest").resolve(), dir2.resolve())

    def test_missing_artifacts_base_is_created(self):
        """The helper creates parity-artifacts before writing latest."""
        missing_base = self.tmpdir / "missing" / "parity-artifacts"
        custom_dir = self.tmpdir / "custom-out"
        custom_dir.mkdir()

        self._call_update_latest(missing_base, custom_dir)

        latest = missing_base / "latest"
        self.assertTrue(missing_base.is_dir(), "artifacts base should be created")
        self.assertTrue(latest.is_symlink(), "latest symlink should exist")
        self.assertEqual(latest.resolve(), custom_dir.resolve())


if __name__ == "__main__":
    unittest.main()
