#!/usr/bin/env python3
"""Publication style gate: reject unsupported numeric prose and enforce specificity.

Validates (per VAL-PUB-007):
1. Numeric claims without nearby claim IDs are rejected.
2. Generic filler phrases ("significant improvement", "much faster",
   "dramatically better") are flagged when not backed by specifics.
3. Unlinked percentage/speedup claims are rejected.
4. Vague attributions ("studies show", "it is known") are flagged.
5. Required sections are present (regressions, limitations, licensing, Q&A).

Usage:
    python3 publication/style_gate.py --memo publication/ragas_blog_memo.md
"""

import argparse
import re
import sys
from pathlib import Path

# Patterns that indicate unsupported generic filler
FILLER_PATTERNS = [
    (r"\bsignificant(?:ly)?\s+(?:improve|fast|better|reduc)",
     "vague 'significant' without quantification"),
    (r"\bmuch\s+(?:fast|slow|better|worse)\b",
     "vague 'much faster/slower' without quantification"),
    (r"\bdramatical(?:ly)?\s+",
     "vague 'dramatically' without quantification"),
    (r"\bvast(?:ly)?\s+(?:improve|superior|better|fast)",
     "vague 'vastly' without quantification"),
    (r"\bstudies\s+show\b",
     "vague attribution 'studies show'"),
    (r"\bit\s+is\s+(?:well\s+)?known\s+that\b",
     "vague attribution 'it is known'"),
    (r"\bresearch\s+(?:has\s+)?show(?:s|n)\b",
     "vague attribution 'research shows'"),
    (r"\bgenerally\s+(?:fast|better|superior)\b",
     "vague 'generally faster/better'"),
    (r"\bin\s+our\s+experience\b",
     "anecdotal 'in our experience' — cite evidence"),
    (r"\bclearly\s+(?:fast|better|superior|outperform)",
     "assumes conclusion with 'clearly' — let data speak"),
]

# Required sections for a complete memo
REQUIRED_SECTIONS = [
    (r"(?i)##\s+.*(?:regression|failure)", "Regressions/Failures section"),
    (r"(?i)##\s+.*(?:limitation|trade.off)", "Limitations/Trade-offs section"),
    (r"(?i)##\s+.*(?:license|attribution|third.party|compliance)",
     "License attribution section"),
    (r"(?i)##\s+.*(?:adversarial|reviewer|q\s*&\s*a|qa)",
     "Adversarial reviewer Q&A section"),
]


def find_unsupported_numeric_claims(memo_text: str) -> list[str]:
    """Find numeric claims not near a CLM-* ID.

    This replicates the check from check_claims.py but in the style gate
    context for a unified gate report.
    """
    numeric_pattern = re.compile(
        r"\d+\.?\d*\s*(?:ms|×|x|%|GiB|GB|MB|cores?|seconds?|s\b)"
        r"|"
        r"\d+\.?\d*×",
        re.IGNORECASE,
    )
    claim_id_pattern = re.compile(r"CLM-[A-Z]+-\d+")
    lines = memo_text.splitlines()
    errors = []

    in_code_block = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        # Skip table separators
        if stripped.startswith("|--") or stripped.startswith("| --"):
            continue
        # Skip code/command lines
        if stripped.startswith(("#", "git ", "python3 ", "./", "rg ", "ugrep ", "ag ", "rust-ag ")):
            continue

        if not numeric_pattern.search(line):
            continue

        # Skip lines that are manifest hashes / commit SHAs
        if re.search(r"[a-f0-9]{40}", line):
            continue
        # Skip hash/policy hash lines
        if "hash" in line.lower() and "CLM-" not in line:
            continue
        # Skip version-only lines
        if re.search(r"\b\d+\.\d+\.\d+\b", line) and "median" not in line.lower():
            if "speedup" not in line.lower() and "faster" not in line.lower():
                continue

        # Check ±10 lines window for claim ID
        start = max(0, i - 10)
        end = min(len(lines), i + 11)
        window = "\n".join(lines[start:end])
        if not claim_id_pattern.search(window):
            errors.append(
                f"Line {i + 1}: unsupported numeric claim: "
                f"{stripped[:120]}"
            )

    return errors


def find_filler_violations(memo_text: str) -> list[str]:
    """Find generic filler phrases that reduce specificity."""
    lines = memo_text.splitlines()
    errors = []
    in_code_block = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        # Skip HTML comments
        if "<!--" in line and "-->" in line:
            continue

        for pattern, description in FILLER_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                # Allow if line also contains a claim ID or specific number
                has_claim = re.search(r"CLM-[A-Z]+-\d+", line)
                has_number = re.search(
                    r"\d+\.?\d*\s*(?:ms|×|x|%)", line, re.IGNORECASE
                )
                if not has_claim and not has_number:
                    errors.append(
                        f"Line {i + 1}: {description}: "
                        f"{stripped[:120]}"
                    )
    return errors


def check_required_sections(memo_text: str) -> list[str]:
    """Check that required sections are present."""
    errors = []
    for pattern, section_name in REQUIRED_SECTIONS:
        if not re.search(pattern, memo_text):
            errors.append(f"Missing required section: {section_name}")
    return errors


def check_claim_evidence_references(memo_text: str) -> list[str]:
    """Check that claim-evidence index table exists and is populated."""
    errors = []
    if "Claim-Evidence Index" not in memo_text and "claim-evidence" not in memo_text.lower():
        errors.append("Missing Claim-Evidence Index section")
    elif re.search(r"CLM-[A-Z]+-\d+", memo_text):
        # At least some claims exist — check there's a mapping table
        if memo_text.count("CLM-") < 10:
            errors.append(
                "Claim-Evidence Index may be incomplete "
                f"(found {memo_text.count('CLM-')} claim references)"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publication style gate for memo quality"
    )
    parser.add_argument("--memo", required=True, help="Path to memo markdown")
    args = parser.parse_args()

    memo_path = Path(args.memo)
    if not memo_path.exists():
        print(f"FAIL: Memo not found at {memo_path}", file=sys.stderr)
        return 1

    memo_text = memo_path.read_text()

    all_errors: list[str] = []
    ok_count = 0

    # Gate 1: Unsupported numeric claims
    num_errors = find_unsupported_numeric_claims(memo_text)
    if num_errors:
        all_errors.append("Unsupported numeric claims (no nearby CLM-* ID):")
        all_errors.extend(f"  {e}" for e in num_errors)
        print(f"  ✗ Numeric claim gate: {len(num_errors)} unsupported")
    else:
        ok_count += 1
        print("  ✓ Numeric claim gate: all claims supported")

    # Gate 2: Filler/specificity violations
    filler_errors = find_filler_violations(memo_text)
    if filler_errors:
        all_errors.append("Generic filler violations:")
        all_errors.extend(f"  {e}" for e in filler_errors)
        print(f"  ✗ Specificity gate: {len(filler_errors)} filler phrases")
    else:
        ok_count += 1
        print("  ✓ Specificity gate: no filler detected")

    # Gate 3: Required sections
    section_errors = check_required_sections(memo_text)
    if section_errors:
        all_errors.append("Missing required sections:")
        all_errors.extend(f"  {e}" for e in section_errors)
        print(f"  ✗ Section completeness: {len(section_errors)} missing")
    else:
        ok_count += 1
        print("  ✓ Section completeness: all required sections present")

    # Gate 4: Claim-evidence references
    ref_errors = check_claim_evidence_references(memo_text)
    if ref_errors:
        all_errors.append("Claim-evidence reference issues:")
        all_errors.extend(f"  {e}" for e in ref_errors)
        print(f"  ✗ Claim references: {len(ref_errors)} issue(s)")
    else:
        ok_count += 1
        print("  ✓ Claim references: index present and populated")

    print(f"\nStyle gate: {ok_count}/4 checks passed")

    if all_errors:
        print("\nFAILURES:")
        for e in all_errors:
            print(e)
        return 1

    print("\nAll style gate checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
