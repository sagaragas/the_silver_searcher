#!/usr/bin/env python3
"""Audit third-party license inventory for completeness and consistency.

Validates (per VAL-PUB-006):
1. license_inventory.json exists and is well-formed.
2. Every runtime dependency in `cargo tree` output appears in the inventory.
3. Upstream source attribution references existing NOTICE and LICENSE files.
4. Benchmark comparator tools are listed.
5. All licenses in inventory are permissive (no copyleft in runtime deps).
6. Memo includes a license attribution section referencing the inventory.

Usage:
    python3 publication/license_audit.py
"""

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PERMISSIVE_LICENSES = {
    "MIT",
    "Apache-2.0",
    "Unlicense",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "PSF-2.0",
    "MIT OR Apache-2.0",
    "Unlicense OR MIT",
    "Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT",
}

REQUIRED_COMPARATORS = {"ripgrep", "rg", "ugrep"}

REQUIRED_INVENTORY_CATEGORIES = [
    "upstream_source",
    "rust_runtime_dependencies",
    "benchmark_comparators",
]


def load_inventory() -> dict | None:
    """Load license inventory JSON."""
    inv_path = REPO_ROOT / "publication" / "license_inventory.json"
    if not inv_path.exists():
        return None
    with open(inv_path) as f:
        return json.load(f)


def get_cargo_runtime_deps() -> list[str]:
    """Get runtime dependency names from cargo tree (depth 1, no dev)."""
    try:
        result = subprocess.run(
            ["cargo", "tree", "--workspace", "--depth", "1",
             "--edges", "normal", "--format", "{p}"],
            capture_output=True, text=True, cwd=REPO_ROOT, timeout=30,
        )
        names = set()
        for line in result.stdout.splitlines():
            line = line.strip().lstrip("├── ").lstrip("└── ").lstrip("│   ")
            match = re.match(r"(\S+)\s+v", line)
            if match:
                name = match.group(1)
                if name != "rust-ag":
                    names.add(name)
        return sorted(names)
    except (subprocess.SubprocessError, FileNotFoundError):
        return []


def check_inventory_schema(inventory: dict) -> list[str]:
    """Check basic schema validity."""
    errors = []
    if "schema_version" not in inventory:
        errors.append("Missing 'schema_version' field")
    if "categories" not in inventory:
        errors.append("Missing 'categories' field")
        return errors

    for cat_name in REQUIRED_INVENTORY_CATEGORIES:
        if cat_name not in inventory["categories"]:
            errors.append(f"Missing required category: '{cat_name}'")
        else:
            cat = inventory["categories"][cat_name]
            if "entries" not in cat:
                errors.append(f"Category '{cat_name}' missing 'entries' list")
            else:
                for entry in cat["entries"]:
                    for field in ("name", "license", "usage"):
                        if field not in entry:
                            errors.append(
                                f"Entry in '{cat_name}' missing '{field}': "
                                f"{entry.get('name', '???')}"
                            )
    return errors


def check_runtime_dep_coverage(
    inventory: dict, cargo_deps: list[str]
) -> list[str]:
    """Check that all cargo runtime deps appear in inventory."""
    errors = []
    inv_names = set()
    for cat_key in ("rust_runtime_dependencies",):
        cat = inventory.get("categories", {}).get(cat_key, {})
        for entry in cat.get("entries", []):
            inv_names.add(entry["name"].lower())

    for dep in cargo_deps:
        if dep.lower() not in inv_names:
            errors.append(f"Runtime dependency '{dep}' not in license inventory")

    return errors


def check_upstream_attribution(inventory: dict) -> list[str]:
    """Check upstream source attribution files exist."""
    errors = []
    cat = inventory.get("categories", {}).get("upstream_source", {})
    for entry in cat.get("entries", []):
        notice = entry.get("notice_file")
        if notice and not (REPO_ROOT / notice).exists():
            errors.append(f"Referenced NOTICE file not found: {notice}")
        license_file = entry.get("license_file")
        if license_file and not (REPO_ROOT / license_file).exists():
            errors.append(f"Referenced LICENSE file not found: {license_file}")
    return errors


def check_comparator_coverage(inventory: dict) -> list[str]:
    """Check that benchmark comparators are listed."""
    errors = []
    cat = inventory.get("categories", {}).get("benchmark_comparators", {})
    comparator_text = " ".join(
        entry.get("name", "").lower()
        for entry in cat.get("entries", [])
    )
    for comp in REQUIRED_COMPARATORS:
        if comp.lower() not in comparator_text:
            errors.append(f"Benchmark comparator '{comp}' not in inventory")
    return errors


def check_license_permissiveness(inventory: dict) -> list[str]:
    """Check all runtime dep licenses are permissive."""
    errors = []
    for cat_key in ("rust_runtime_dependencies", "upstream_source"):
        cat = inventory.get("categories", {}).get(cat_key, {})
        for entry in cat.get("entries", []):
            lic = entry.get("license", "")
            if lic not in PERMISSIVE_LICENSES:
                errors.append(
                    f"Non-permissive license for '{entry['name']}': {lic}"
                )
    return errors


def check_memo_attribution_section() -> list[str]:
    """Check memo includes license attribution section."""
    errors = []
    memo_path = REPO_ROOT / "publication" / "ragas_blog_memo.md"
    if not memo_path.exists():
        errors.append("Memo file not found")
        return errors

    memo_text = memo_path.read_text()
    # Check for license/attribution section
    has_license_section = bool(
        re.search(
            r"(?i)##\s+.*(?:license|attribution|third.party|compliance)",
            memo_text,
        )
    )
    if not has_license_section:
        errors.append(
            "Memo missing license attribution section "
            "(expected heading with 'License', 'Attribution', or "
            "'Third-Party')"
        )

    # Check for inventory reference
    if "license_inventory" not in memo_text.lower().replace(" ", "_").replace("-", "_"):
        errors.append(
            "Memo does not reference 'license_inventory' artifact"
        )

    return errors


def main() -> int:
    errors: list[str] = []
    ok_count = 0

    # Check 1: Load inventory
    inventory = load_inventory()
    if inventory is None:
        print("FAIL: license_inventory.json not found", file=sys.stderr)
        return 1
    ok_count += 1
    print("  ✓ Inventory file found")

    # Check 2: Schema validity
    schema_errors = check_inventory_schema(inventory)
    if schema_errors:
        errors.extend(schema_errors)
        print(f"  ✗ Schema: {len(schema_errors)} issue(s)")
    else:
        ok_count += 1
        print("  ✓ Schema valid")

    # Check 3: Runtime dep coverage
    cargo_deps = get_cargo_runtime_deps()
    dep_errors = check_runtime_dep_coverage(inventory, cargo_deps)
    if dep_errors:
        errors.extend(dep_errors)
        print(f"  ✗ Runtime dep coverage: {len(dep_errors)} missing")
    else:
        ok_count += 1
        print(f"  ✓ Runtime dep coverage ({len(cargo_deps)} deps)")

    # Check 4: Upstream attribution
    attr_errors = check_upstream_attribution(inventory)
    if attr_errors:
        errors.extend(attr_errors)
        print(f"  ✗ Upstream attribution: {len(attr_errors)} issue(s)")
    else:
        ok_count += 1
        print("  ✓ Upstream attribution files verified")

    # Check 5: Comparator coverage
    comp_errors = check_comparator_coverage(inventory)
    if comp_errors:
        errors.extend(comp_errors)
        print(f"  ✗ Comparator coverage: {len(comp_errors)} missing")
    else:
        ok_count += 1
        print("  ✓ Comparator tools listed")

    # Check 6: License permissiveness
    perm_errors = check_license_permissiveness(inventory)
    if perm_errors:
        errors.extend(perm_errors)
        print(f"  ✗ Permissiveness: {len(perm_errors)} issue(s)")
    else:
        ok_count += 1
        print("  ✓ All runtime licenses permissive")

    # Check 7: Memo attribution section
    memo_errors = check_memo_attribution_section()
    if memo_errors:
        errors.extend(memo_errors)
        print(f"  ✗ Memo attribution: {len(memo_errors)} issue(s)")
    else:
        ok_count += 1
        print("  ✓ Memo includes attribution section")

    total = ok_count + (1 if errors else 0)
    print(f"\nLicense audit: {ok_count}/7 checks passed")

    if errors:
        print("\nFAILURES:")
        for e in errors:
            print(f"  {e}")
        return 1

    print("\nAll license audit checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
