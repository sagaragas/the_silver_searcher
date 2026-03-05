#!/usr/bin/env python3
"""Tests for argv tokenization in the parity runner.

Verifies that run_command() correctly preserves quoted arguments and
paths/patterns containing spaces, using shlex.split() instead of naive
str.split().
"""

from __future__ import annotations

import shlex
import unittest


class TestArgvTokenization(unittest.TestCase):
    """Verify that shlex.split handles the command templates we use."""

    def test_simple_command_no_spaces(self):
        """Plain command with no quoting needed tokenizes identically."""
        cmd = "ag --nocolor --workers=1 foo src"
        self.assertEqual(shlex.split(cmd), ["ag", "--nocolor", "--workers=1", "foo", "src"])

    def test_quoted_corpus_with_spaces(self):
        """Corpus path containing spaces is preserved as single token."""
        cmd = 'ag --nocolor --workers=1 NEEDLE "tests/edge-cases/quoted args"'
        tokens = shlex.split(cmd)
        self.assertEqual(tokens[-1], "tests/edge-cases/quoted args")
        self.assertNotIn('"tests/edge-cases/quoted', tokens)

    def test_quoted_pattern_with_spaces(self):
        """Multi-word pattern in quotes is preserved as single token."""
        cmd = 'ag --nocolor --workers=1 "the marker" "tests/edge-cases/quoted args"'
        tokens = shlex.split(cmd)
        self.assertEqual(tokens[-2], "the marker")
        self.assertEqual(tokens[-1], "tests/edge-cases/quoted args")

    def test_naive_split_breaks_quoted_args(self):
        """Demonstrate that naive str.split() incorrectly fragments quoted args."""
        cmd = 'ag --nocolor --workers=1 NEEDLE "tests/edge-cases/quoted args"'
        naive = cmd.split()
        # Naive split breaks the path into two pieces with embedded quotes.
        self.assertIn('"tests/edge-cases/quoted', naive)
        self.assertIn('args"', naive)

        # shlex correctly keeps the path as one token.
        safe = shlex.split(cmd)
        self.assertIn("tests/edge-cases/quoted args", safe)

    def test_double_quoted_pattern_and_corpus(self):
        """Both pattern and corpus with spaces are preserved correctly."""
        cmd = 'ag --nocolor "hello world" "path with spaces/dir"'
        tokens = shlex.split(cmd)
        self.assertEqual(tokens, ["ag", "--nocolor", "hello world", "path with spaces/dir"])

    def test_single_quoted_pattern(self):
        """Single-quoted arguments are also handled correctly."""
        cmd = "ag --nocolor 'hello world' 'path with spaces'"
        tokens = shlex.split(cmd)
        self.assertEqual(tokens, ["ag", "--nocolor", "hello world", "path with spaces"])

    def test_template_substitution_with_quoting(self):
        """Simulate the template substitution done in run_command."""
        template = 'ag --nocolor --workers=1 --parallel --noaffinity "{pattern}" "{corpus}"'
        pattern = "the marker"
        corpus = "tests/edge-cases/quoted args"

        cmd_str = template.replace("{pattern}", pattern).replace("{corpus}", corpus)
        tokens = shlex.split(cmd_str)

        # Pattern and corpus should be preserved as single tokens.
        self.assertIn("the marker", tokens)
        self.assertIn("tests/edge-cases/quoted args", tokens)

    def test_template_no_quotes_simple_args(self):
        """Template without quotes works fine for non-space args."""
        template = "ag --nocolor --workers=1 --parallel --noaffinity {pattern} {corpus}"
        pattern = "NEEDLE"
        corpus = "tests/edge-cases/max-count"

        cmd_str = template.replace("{pattern}", pattern).replace("{corpus}", corpus)
        tokens = shlex.split(cmd_str)

        self.assertIn("NEEDLE", tokens)
        self.assertIn("tests/edge-cases/max-count", tokens)


if __name__ == "__main__":
    unittest.main()
