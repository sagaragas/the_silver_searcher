#!/usr/bin/env python3
"""Tests for argv tokenization in the parity runner.

Verifies that the tokenize_command() helper correctly:
  - Preserves quoted arguments/paths containing spaces as single tokens.
  - Preserves literal backslashes in unquoted tokens (e.g. \\b word
    boundaries in regex patterns).
  - Behaves identically to naive split for simple commands without
    quotes or backslashes.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Ensure the parity scripts directory is importable.
_PARITY_DIR = Path(__file__).resolve().parent
if str(_PARITY_DIR) not in sys.path:
    sys.path.insert(0, str(_PARITY_DIR))

from run_matrix import tokenize_command  # noqa: E402


class TestArgvTokenization(unittest.TestCase):
    """Verify that tokenize_command handles both quoted and backslash cases."""

    # ------------------------------------------------------------------
    # Basic tokenization (no quotes, no backslashes)
    # ------------------------------------------------------------------

    def test_simple_command_no_spaces(self):
        """Plain command with no quoting needed tokenizes identically."""
        cmd = "ag --nocolor --workers=1 foo src"
        self.assertEqual(
            tokenize_command(cmd),
            ["ag", "--nocolor", "--workers=1", "foo", "src"],
        )

    def test_template_no_quotes_simple_args(self):
        """Template without quotes works fine for non-space args."""
        template = "ag --nocolor --workers=1 --parallel --noaffinity {pattern} {corpus}"
        pattern = "NEEDLE"
        corpus = "tests/edge-cases/max-count"
        cmd_str = template.replace("{pattern}", pattern).replace("{corpus}", corpus)
        tokens = tokenize_command(cmd_str)
        self.assertIn("NEEDLE", tokens)
        self.assertIn("tests/edge-cases/max-count", tokens)

    # ------------------------------------------------------------------
    # Quoted arguments (paths / patterns with spaces)
    # ------------------------------------------------------------------

    def test_quoted_corpus_with_spaces(self):
        """Corpus path containing spaces is preserved as single token."""
        cmd = 'ag --nocolor --workers=1 NEEDLE "tests/edge-cases/quoted args"'
        tokens = tokenize_command(cmd)
        self.assertEqual(tokens[-1], "tests/edge-cases/quoted args")
        self.assertNotIn('"tests/edge-cases/quoted', tokens)

    def test_quoted_pattern_with_spaces(self):
        """Multi-word pattern in quotes is preserved as single token."""
        cmd = 'ag --nocolor --workers=1 "the marker" "tests/edge-cases/quoted args"'
        tokens = tokenize_command(cmd)
        self.assertEqual(tokens[-2], "the marker")
        self.assertEqual(tokens[-1], "tests/edge-cases/quoted args")

    def test_double_quoted_pattern_and_corpus(self):
        """Both pattern and corpus with spaces are preserved correctly."""
        cmd = 'ag --nocolor "hello world" "path with spaces/dir"'
        tokens = tokenize_command(cmd)
        self.assertEqual(
            tokens, ["ag", "--nocolor", "hello world", "path with spaces/dir"]
        )

    def test_single_quoted_pattern(self):
        """Single-quoted arguments are also handled correctly."""
        cmd = "ag --nocolor 'hello world' 'path with spaces'"
        tokens = tokenize_command(cmd)
        self.assertEqual(
            tokens, ["ag", "--nocolor", "hello world", "path with spaces"]
        )

    def test_template_substitution_with_quoting(self):
        """Simulate the template substitution done in run_command."""
        template = 'ag --nocolor --workers=1 --parallel --noaffinity "{pattern}" "{corpus}"'
        pattern = "the marker"
        corpus = "tests/edge-cases/quoted args"
        cmd_str = template.replace("{pattern}", pattern).replace("{corpus}", corpus)
        tokens = tokenize_command(cmd_str)
        self.assertIn("the marker", tokens)
        self.assertIn("tests/edge-cases/quoted args", tokens)

    def test_naive_split_breaks_quoted_args(self):
        """Demonstrate that naive str.split() incorrectly fragments quoted args."""
        cmd = 'ag --nocolor --workers=1 NEEDLE "tests/edge-cases/quoted args"'
        naive = cmd.split()
        # Naive split breaks the path into two pieces with embedded quotes.
        self.assertIn('"tests/edge-cases/quoted', naive)
        self.assertIn('args"', naive)

        # tokenize_command correctly keeps the path as one token.
        safe = tokenize_command(cmd)
        self.assertIn("tests/edge-cases/quoted args", safe)

    # ------------------------------------------------------------------
    # Escaped-regex backslash preservation (the regression from shlex)
    # ------------------------------------------------------------------

    def test_backslash_word_boundary_preserved(self):
        r"""Unquoted \b word boundaries must remain literal backslashes."""
        cmd = r"ag --nocolor --workers=1 \b[A-Z]{2,}_[A-Z]{2,}\b ."
        tokens = tokenize_command(cmd)
        # The pattern token must still contain literal \b on each side.
        self.assertIn(r"\b[A-Z]{2,}_[A-Z]{2,}\b", tokens)

    def test_template_regex_complex_preserves_backslash(self):
        r"""Template substitution for regex-complex preserves \b boundaries."""
        template = (
            "ag --nocolor --workers=1 --parallel --noaffinity {pattern} {corpus}"
        )
        pattern = r"\b[A-Z]{2,}_[A-Z]{2,}\b"
        corpus = "."
        cmd_str = template.replace("{pattern}", pattern).replace("{corpus}", corpus)
        tokens = tokenize_command(cmd_str)
        self.assertEqual(
            tokens,
            [
                "ag",
                "--nocolor",
                "--workers=1",
                "--parallel",
                "--noaffinity",
                r"\b[A-Z]{2,}_[A-Z]{2,}\b",
                ".",
            ],
        )

    def test_backslash_in_newline_regex(self):
        r"""Multiline regex containing \\n literal is preserved."""
        cmd = r"ag --nocolor if.*\n.*return ."
        tokens = tokenize_command(cmd)
        self.assertIn(r"if.*\n.*return", tokens)

    def test_shlex_posix_eats_backslashes(self):
        r"""Demonstrate that shlex.split(posix=True) destroys backslashes."""
        import shlex

        cmd = r"ag --nocolor \bfoo\b ."
        posix_tokens = shlex.split(cmd)
        # shlex posix mode eats the backslash, turning \b into just b.
        self.assertIn("bfoob", posix_tokens)
        self.assertNotIn(r"\bfoo\b", posix_tokens)

        # Our tokenizer preserves the backslash.
        safe = tokenize_command(cmd)
        self.assertIn(r"\bfoo\b", safe)

    # ------------------------------------------------------------------
    # Combined: quotes + backslashes in the same command
    # ------------------------------------------------------------------

    def test_backslash_pattern_and_quoted_corpus(self):
        r"""Backslash regex + quoted corpus with spaces both handled."""
        cmd = r'ag --nocolor \bfoo\b "tests/edge-cases/quoted args"'
        tokens = tokenize_command(cmd)
        self.assertIn(r"\bfoo\b", tokens)
        self.assertIn("tests/edge-cases/quoted args", tokens)

    def test_quoted_pattern_with_backslash_and_spaces(self):
        r"""Quoted pattern containing both backslash and spaces."""
        cmd = r'ag --nocolor "\bthe marker\b" .'
        tokens = tokenize_command(cmd)
        self.assertIn(r"\bthe marker\b", tokens)


if __name__ == "__main__":
    unittest.main()
