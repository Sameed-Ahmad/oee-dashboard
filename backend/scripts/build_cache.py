#!/usr/bin/env python
"""CLI: parse a product's Excel workbook and write its processed JSON cache.

Usage:
    python backend/scripts/build_cache.py --product fryo
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
from app.products.registry import PRODUCTS  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--product", required=True, choices=sorted(PRODUCTS.keys()),
        help="product slug to build the cache for",
    )
    args = parser.parse_args()

    config = PRODUCTS[args.product]
    print(f"Parsing '{config.display_name}' ({config.slug}) from {config.resolved_excel_path} ...")

    result = parse_workbook(config)

    print()
    print(f"  Days parsed:    {len(result.records)}")
    print(f"  Sheets skipped: {len(result.skipped_sheets)} (Summary/Link/duplicate sheets)")
    if result.records:
        print(f"  Date range:     {result.records[0]['date']} to {result.records[-1]['date']}")
    if result.errors:
        print(f"  Errors/warnings ({len(result.errors)}):")
        for err in result.errors:
            print(f"    - {err}")
    else:
        print("  Errors/warnings: none")

    save_cache(config.slug, result.records)
    print()
    print(f"Wrote {len(result.records)} records to backend/data/processed/{config.slug}.json")


if __name__ == "__main__":
    main()
