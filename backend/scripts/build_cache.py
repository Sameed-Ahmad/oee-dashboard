#!/usr/bin/env python
"""CLI: parse a product's Excel workbook and write its processed JSON cache.

Usage:
    python backend/scripts/build_cache.py --product fryo
    python backend/scripts/build_cache.py --all
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as `python backend/scripts/build_cache.py` from the repo root.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.cache import save_cache  # noqa: E402
from app.parser import parse_workbook  # noqa: E402
from app.products.registry import PRODUCTS, ProductConfig  # noqa: E402


def build_one(config: ProductConfig) -> None:
    print(f"Parsing '{config.display_name}' ({config.slug}) ...")

    if config.excel_dir is None:
        print("  No excel_dir registered for this product yet -- skipping.")
        print()
        return

    result = parse_workbook(config)

    print(f"  Day records:    {len(result.records)}")
    print(f"  Sheets skipped: {len(result.skipped_sheets)} (Summary/Link/duplicate/blank-template sheets)")
    if result.records:
        print(f"  Date range:     {result.records[0]['date']} to {result.records[-1]['date']}")
    if result.errors:
        print(f"  Data quality warnings ({len(result.errors)}):")
        for err in result.errors:
            print(f"    - {err}")
    else:
        print("  Data quality warnings: none")

    groups = result.groups or {}
    if groups:
        print(f"  Machine/line breakdown: {', '.join(sorted(groups.keys()))}")

    save_cache(config.slug, result.records, result.errors, groups)
    print(f"  Wrote {len(result.records)} records to backend/data/processed/{config.slug}.json")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--product", choices=sorted(PRODUCTS.keys()), help="product slug to build the cache for")
    group.add_argument("--all", action="store_true", help="rebuild every product that has an excel_dir registered")
    args = parser.parse_args()

    if args.all:
        targets = [p for p in PRODUCTS.values() if p.excel_dir is not None]
        print(f"Building cache for {len(targets)} product(s) with a registered data source...\n")
        for config in targets:
            build_one(config)
    else:
        build_one(PRODUCTS[args.product])


if __name__ == "__main__":
    main()
