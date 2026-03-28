#!/usr/bin/env python3
"""Validate that all numeric/factual claims in the memo have claim ID linkage.

Checks:
1. Every claim ID referenced in the memo exists in claim_evidence_map.json.
2. Every claim ID in claim_evidence_map.json is referenced in the memo.
3. Every claim has at least one evidence artifact.
4. Numeric claims (containing numbers with units like ms, ×, %) have claim IDs
   in their surrounding context.

Usage:
    python3 publication/check_claims.py --memo publication/ragas_blog_memo.md
"""

import argparse
import json
import re
import sys
from pathlib import Path


def load_claim_map(repo_root: Path) -> dict:
    """Load claim-evidence map from publication directory."""
    map_path = repo_root / "publication" / "claim_evidence_map.json"
    if not map_path.exists():
        print(f"FAIL: claim_evidence_map.json not found at {map_path}", file=sys.stderr)
        sys.exit(1)
    with open(map_path) as f:
        return json.load(f)


def extract_claim_ids_from_memo(memo_text: str) -> set[str]:
    """Extract all CLM-* claim IDs referenced in the memo."""
    return set(re.findall(r"CLM-[A-Z]+-\d+", memo_text))


def extract_claim_ids_from_map(claim_map: dict) -> set[str]:
    """Extract all claim IDs defined in the claim-evidence map."""
    return {c["claim_id"] for c in claim_map.get("claims", [])}


def find_numeric_lines(memo_text: str) -> list[tuple[int, str]]:
    """Find lines containing numeric claims (numbers with units or countable nouns)."""
    numeric_pattern = re.compile(
        r"\d+\.?\d*\s*(?:ms|×|x|%|GiB|GB|MB|cores?|seconds?|s\b)"
        r"|"
        r"\d+\.?\d*×"
        r"|"
        r"\b\d+\s+(?:scenario|scenarios|runs?|samples?|clusters?|comparators?"
        r"|checks?|tools?|features?|iterations?|warmups?|cells?|pairs?"
        r"|violations?|flagged|dropped|entries|dependencies|crates?)\b",
        re.IGNORECASE,
    )
    results = []
    for i, line in enumerate(memo_text.splitlines(), 1):
        # Skip table headers, separators, and artifact references
        stripped = line.strip()
        if stripped.startswith("|--") or stripped.startswith("| --"):
            continue
        if stripped.startswith("```"):
            continue
        if numeric_pattern.search(line):
            results.append((i, line))
    return results


def check_numeric_claim_coverage(
    memo_text: str, numeric_lines: list[tuple[int, str]]
) -> list[str]:
    """Check that numeric claim lines have claim IDs in nearby context.

    A numeric claim line is covered if there is a CLM-* ID within a
    window of 10 lines before or after it, or in an HTML comment on
    the same section.
    """
    lines = memo_text.splitlines()
    errors = []
    claim_id_pattern = re.compile(r"CLM-[A-Z]+-\d+")

    for line_num, line_text in numeric_lines:
        # Skip lines that are inside code blocks
        if line_text.strip().startswith(("#", "```", "git ", "python3 ", "./")):
            continue
        # Skip lines that are manifest hashes or commit SHAs
        if re.search(r"[a-f0-9]{40}", line_text):
            continue
        # Skip table rows that are just metadata (manifest hashes, policy hashes)
        if "hash" in line_text.lower() and "CLM-" not in line_text:
            continue
        # Skip lines inside reproducibility instructions (code blocks)
        if line_text.strip().startswith(("rg ", "ugrep ", "ag ", "rust-ag ")):
            continue
        # Skip version number lines in tables (comparator version info)
        if re.search(r"\b\d+\.\d+\.\d+\b", line_text) and "median" not in line_text.lower():
            if "speedup" not in line_text.lower() and "faster" not in line_text.lower():
                continue

        # Check window of ±10 lines for claim ID
        start = max(0, line_num - 11)
        end = min(len(lines), line_num + 10)
        window = "\n".join(lines[start:end])

        if not claim_id_pattern.search(window):
            errors.append(
                f"  Line {line_num}: numeric claim without nearby claim ID: "
                f"{line_text.strip()[:100]}"
            )

    return errors


def validate_evidence_completeness(claim_map: dict) -> list[str]:
    """Check that every claim has at least one evidence entry."""
    errors = []
    for claim in claim_map.get("claims", []):
        cid = claim["claim_id"]
        evidence = claim.get("evidence", [])
        if not evidence:
            errors.append(f"  {cid}: no evidence artifacts linked")
        for ev in evidence:
            if not ev.get("artifact"):
                errors.append(f"  {cid}: evidence entry missing 'artifact' path")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate memo claim-evidence linkage")
    parser.add_argument("--memo", required=True, help="Path to memo markdown file")
    args = parser.parse_args()

    memo_path = Path(args.memo)
    if not memo_path.exists():
        print(f"FAIL: Memo not found at {memo_path}", file=sys.stderr)
        return 1

    # Determine repo root relative to memo
    repo_root = memo_path.resolve().parent.parent
    if not (repo_root / "publication").exists():
        repo_root = Path.cwd()

    memo_text = memo_path.read_text()
    claim_map = load_claim_map(repo_root)

    memo_ids = extract_claim_ids_from_memo(memo_text)
    map_ids = extract_claim_ids_from_map(claim_map)

    errors: list[str] = []
    ok_count = 0

    # Check 1: All memo claim IDs exist in the map
    orphan_memo = memo_ids - map_ids
    if orphan_memo:
        errors.append(f"Claim IDs in memo but not in map: {sorted(orphan_memo)}")
    else:
        ok_count += 1

    # Check 2: All map claim IDs are referenced in the memo
    orphan_map = map_ids - memo_ids
    if orphan_map:
        errors.append(f"Claim IDs in map but not in memo: {sorted(orphan_map)}")
    else:
        ok_count += 1

    # Check 3: Evidence completeness
    evidence_errors = validate_evidence_completeness(claim_map)
    if evidence_errors:
        errors.append("Evidence completeness failures:")
        errors.extend(evidence_errors)
    else:
        ok_count += 1

    # Check 4: Numeric claim coverage
    numeric_lines = find_numeric_lines(memo_text)
    coverage_errors = check_numeric_claim_coverage(memo_text, numeric_lines)
    if coverage_errors:
        errors.append("Numeric claims without nearby claim ID:")
        errors.extend(coverage_errors)
    else:
        ok_count += 1

    # Report
    print(f"Claim validation: {ok_count}/4 checks passed")
    print(f"  Memo claim IDs: {len(memo_ids)}")
    print(f"  Map claim IDs: {len(map_ids)}")
    print(f"  Numeric claim lines found: {len(numeric_lines)}")

    if errors:
        print("\nFAILURES:")
        for e in errors:
            print(f"  {e}")
        return 1

    print("\nAll claim-evidence checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
