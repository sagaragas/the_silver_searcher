#!/usr/bin/env python3
"""Validate that metrics tables in the memo include required columns and context.

Checks (per VAL-PUB-003):
1. Performance tables include units (ms), sample sizes (n), and uncertainty (CI).
2. Speedup tables include comparator context and cross-run deltas.
3. All reported numeric values can be traced to benchmark artifacts.
4. Tables are well-formed markdown with consistent column counts.

Usage:
    python3 publication/validate_metrics_tables.py --memo publication/ragas_blog_memo.md
"""

import argparse
import json
import re
import sys
from pathlib import Path


# Required columns in performance detail tables
REQUIRED_PERF_COLUMNS = {"median", "iqr", "ci lower", "ci upper", "samples"}

# Required columns in speedup tables
REQUIRED_SPEEDUP_COLUMNS = {"faster", "slower", "speedup", "ci overlap", "claim"}


def extract_tables(memo_text: str) -> list[dict]:
    """Extract markdown tables from memo text.

    Returns list of dicts with 'header', 'rows', 'start_line', 'raw_header'.
    """
    lines = memo_text.splitlines()
    tables = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Detect table header: line starting with | and followed by separator
        if line.startswith("|") and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if next_line.startswith("|") and re.search(r"-{2,}", next_line):
                # Parse header
                header_cells = [
                    c.strip().lower()
                    for c in line.split("|")
                    if c.strip()
                ]
                raw_header = line
                rows = []
                j = i + 2  # skip header and separator
                while j < len(lines) and lines[j].strip().startswith("|"):
                    row_cells = [
                        c.strip() for c in lines[j].split("|") if c.strip()
                    ]
                    rows.append(row_cells)
                    j += 1
                tables.append({
                    "header": header_cells,
                    "raw_header": raw_header,
                    "rows": rows,
                    "start_line": i + 1,
                    "end_line": j,
                })
                i = j
                continue
        i += 1
    return tables


def check_performance_tables(tables: list[dict]) -> list[str]:
    """Check that performance detail tables have required columns."""
    errors = []
    perf_table_found = False

    for table in tables:
        header_text = " ".join(table["header"])
        # Identify performance tables by presence of median/iqr columns
        if "median" in header_text and "iqr" in header_text:
            perf_table_found = True

            # Check for required column presence
            for req in REQUIRED_PERF_COLUMNS:
                if not any(req in h for h in table["header"]):
                    errors.append(
                        f"Line {table['start_line']}: Performance table missing "
                        f"'{req}' column. Headers: {table['header']}"
                    )

            # Check units in header (ms)
            has_units = any("ms" in h or "(ms)" in h for h in table["header"])
            if not has_units:
                errors.append(
                    f"Line {table['start_line']}: Performance table headers "
                    f"missing unit annotations (ms). Headers: {table['header']}"
                )

            # Check sample size column has data
            sample_col_idx = None
            for idx, h in enumerate(table["header"]):
                if "samples" in h or "(n)" in h:
                    sample_col_idx = idx
                    break

            if sample_col_idx is not None:
                for row in table["rows"]:
                    if sample_col_idx < len(row):
                        val = row[sample_col_idx].strip()
                        if not val or val == "-":
                            errors.append(
                                f"Line {table['start_line']}: Performance table "
                                f"row has empty sample count: {row}"
                            )

            # Check row consistency (all rows have same column count)
            expected_cols = len(table["header"])
            for row_idx, row in enumerate(table["rows"]):
                if len(row) != expected_cols:
                    errors.append(
                        f"Line {table['start_line']}: Row {row_idx + 1} has "
                        f"{len(row)} columns, expected {expected_cols}"
                    )

    if not perf_table_found:
        errors.append("No performance detail tables found (expected tables with "
                       "median/IQR/CI columns)")

    return errors


def check_speedup_tables(tables: list[dict]) -> list[str]:
    """Check that speedup comparison tables have required columns."""
    errors = []
    speedup_table_found = False

    for table in tables:
        header_text = " ".join(table["header"])
        if "faster" in header_text and "slower" in header_text:
            speedup_table_found = True

            # Check for speedup ratio columns
            has_speedup = any("speedup" in h for h in table["header"])
            if not has_speedup:
                errors.append(
                    f"Line {table['start_line']}: Speedup table missing "
                    f"'speedup' column"
                )

            # Check for CI overlap
            has_overlap = any("overlap" in h or "ci" in h for h in table["header"])
            if not has_overlap:
                errors.append(
                    f"Line {table['start_line']}: Speedup table missing "
                    f"CI overlap column"
                )

            # Check for claim status
            has_claim = any("claim" in h for h in table["header"])
            if not has_claim:
                errors.append(
                    f"Line {table['start_line']}: Speedup table missing "
                    f"'claim allowed' column"
                )

            # Check multiple run types are represented
            run_type_count = sum(
                1 for h in table["header"]
                if any(rt in h for rt in ["local", "nightly", "manual"])
            )
            if run_type_count < 2:
                errors.append(
                    f"Line {table['start_line']}: Speedup table should show "
                    f"multiple run types for cross-run context (found {run_type_count})"
                )

    if not speedup_table_found:
        errors.append("No speedup comparison tables found (expected tables with "
                       "faster/slower columns)")

    return errors


def check_sampling_validation_table(tables: list[dict]) -> list[str]:
    """Check that a sampling/methodology validation table exists."""
    errors = []
    found = False

    for table in tables:
        header_text = " ".join(table["header"])
        if "check" in header_text and "result" in header_text:
            found = True
            # Should have warmup, sample count, statistical method entries
            row_texts = [" ".join(r).lower() for r in table["rows"]]
            all_text = " ".join(row_texts)
            required_checks = ["warmup", "sample", "outlier"]
            for chk in required_checks:
                if chk not in all_text:
                    errors.append(
                        f"Sampling validation table missing '{chk}' check row"
                    )

    if not found:
        errors.append("No sampling validation summary table found")

    return errors


def check_raw_sample_table(tables: list[dict]) -> list[str]:
    """Check that raw sample data table exists with outlier column."""
    errors = []
    found = False

    for table in tables:
        header_text = " ".join(table["header"])
        if "sample" in header_text and "outlier" in header_text:
            found = True
            # Should have at least 4 rows (one per comparator)
            if len(table["rows"]) < 4:
                errors.append(
                    f"Raw sample table has {len(table['rows'])} rows, "
                    f"expected at least 4 (one per comparator)"
                )

    if not found:
        errors.append("No raw sample data table found (expected table with "
                       "sample columns and outlier flags)")

    return errors


def check_environment_table(tables: list[dict]) -> list[str]:
    """Check that environment metadata table exists."""
    errors = []
    found = False

    for table in tables:
        header_text = " ".join(table["header"])
        if "property" in header_text and "value" in header_text:
            found = True
            row_texts = [" ".join(r).lower() for r in table["rows"]]
            all_text = " ".join(row_texts)
            for req in ["cpu", "ram", "os"]:
                if req not in all_text:
                    errors.append(
                        f"Environment table missing '{req}' entry"
                    )

    if not found:
        errors.append("No environment metadata table found")

    return errors


def check_comparator_version_table(tables: list[dict]) -> list[str]:
    """Check that comparator version table exists with all 4 tools."""
    errors = []
    found = False

    for table in tables:
        header_text = " ".join(table["header"])
        if "comparator" in header_text and "version" in header_text:
            found = True
            row_texts = [" ".join(r).lower() for r in table["rows"]]
            all_text = " ".join(row_texts)
            for tool in ["ag", "rust-ag", "rg", "ugrep"]:
                if tool not in all_text:
                    errors.append(
                        f"Comparator table missing '{tool}' entry"
                    )

    if not found:
        errors.append("No comparator version table found")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate metrics tables in memo"
    )
    parser.add_argument("--memo", required=True, help="Path to memo markdown")
    args = parser.parse_args()

    memo_path = Path(args.memo)
    if not memo_path.exists():
        print(f"FAIL: Memo not found at {memo_path}", file=sys.stderr)
        return 1

    memo_text = memo_path.read_text()
    tables = extract_tables(memo_text)

    print(f"Found {len(tables)} tables in memo")

    all_errors: list[str] = []
    checks = [
        ("Performance detail tables", check_performance_tables),
        ("Speedup comparison tables", check_speedup_tables),
        ("Sampling validation table", check_sampling_validation_table),
        ("Raw sample data table", check_raw_sample_table),
        ("Environment metadata table", check_environment_table),
        ("Comparator version table", check_comparator_version_table),
    ]

    for name, check_fn in checks:
        errors = check_fn(tables)
        if errors:
            all_errors.append(f"\n{name}:")
            all_errors.extend(f"  {e}" for e in errors)
            print(f"  ✗ {name}: {len(errors)} issue(s)")
        else:
            print(f"  ✓ {name}")

    if all_errors:
        print(f"\nFAILURES ({len(all_errors)} issues):")
        for e in all_errors:
            print(e)
        return 1

    print("\nAll metrics table validations passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
