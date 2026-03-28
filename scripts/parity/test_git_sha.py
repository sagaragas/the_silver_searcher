#!/usr/bin/env python3
"""Tests for git SHA capture in parity run metadata."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_PARITY = Path(__file__).resolve().parent
if str(SCRIPTS_PARITY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PARITY))

import run_matrix  # noqa: E402


class TestGitSha(unittest.TestCase):
    """Verify _git_sha handles non-git directories robustly."""

    @mock.patch("run_matrix.subprocess.run")
    def test_git_sha_returns_head_on_success(self, mock_run: mock.MagicMock) -> None:
        mock_run.return_value = mock.Mock(returncode=0, stdout="abc123\n")
        self.assertEqual(run_matrix._git_sha(), "abc123")

    @mock.patch("run_matrix.subprocess.run")
    def test_git_sha_returns_unknown_when_git_fails(
        self,
        mock_run: mock.MagicMock,
    ) -> None:
        mock_run.return_value = mock.Mock(returncode=128, stdout="")
        self.assertEqual(run_matrix._git_sha(), "unknown")

    @mock.patch("run_matrix.subprocess.run", side_effect=OSError("git missing"))
    def test_git_sha_returns_unknown_on_exception(
        self,
        _mock_run: mock.MagicMock,
    ) -> None:
        self.assertEqual(run_matrix._git_sha(), "unknown")


if __name__ == "__main__":
    unittest.main()
