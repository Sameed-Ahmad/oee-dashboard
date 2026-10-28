"""Per-item contractual packing labour cost, read from the individual
contractor bill workbooks (backend/data/labour cost/*Packing Contractor
Bill*.xlsx) -- one workbook per contractor, one sheet per 15-day billing
period ("01 To 15-<Mon>-26" / "16 To <end>-<Mon>-26"). Entirely separate
from both the day-by-day OEE workbooks (parser.py) and the Labor Cost
Analysis workbook (labor_cost.py): finer-grained (item-level, per 15
days) and a different source document altogether.

Each workbook's own "Department" cell -- fixed for every real period
sheet in that file, verified across all 4 files -- pins the WHOLE file
to one of the 4 Packing Dept products:

    Usman Packing Contractor Bill            "Packing Fry O"   -> fryo
    Ashiq Hussain Packing Contractor Bill    "Pops R10 / R 20" -> pops
    Ghulam Nabi Packing Contractor Bill      "BB R 10"         -> nimco
    Basit Enterprise Packing Contractor Bill "BB R 20"         -> nimco

Nimco has two separate contractors (same R-10 / R-20 split
labor_cost.py's PRODUCT_SOURCE_LINES already uses for Nimco) -- both are
summed into one "nimco" figure. No contractor file exists yet for
Ishida, so Ishida has no contractual-labour-cost data at all. A sheet
whose Department text doesn't match one of the 4 known values (template/
placeholder tabs with no real Department cell) is skipped.

By explicit instruction, this is kept as its own standalone "Contractual
labour cost" figure rather than merged into labor_cost.py's existing
Total Labor Cost / Cost per 1,000 units -- that workbook's own
"Contractual Workers Amount Paid" line (on its raw per-department sheet,
not the Report sheet this app reads) is a different, much smaller number
for the same product/month (confirmed ~4-8x off against these bills), so
the two evidently measure different things and aren't meant to be
reconciled here.

Each period sheet is a small fixed-form bill, not a transaction table:
a header block (Location/Department/Contractor Name/Bill Duration),
then one "Items Details" row per item/pack-size code, interspersed with
subtotal rows ("Total 72 Pcs HD", ...), ending in one "Total Payable"
row. Subtotal/blank rows are skipped by requiring a non-blank Items
Details cell -- every real item row has one, no subtotal or filler row
does (verified across all 4 files). The Rate column is only filled on
the first row of a same-rate group (the sheet's own merged-cell
convention, e.g. one rate shared by 4 different pack sizes) and blank on
the rest, so rate is read back out as amountRs / quantity per row
instead of trusted directly -- verified this reproduces the sheet's own
filled-in rate exactly wherever one IS present.

No month cutoff is hardcoded here: these bills actually run through
Oct-2026, well past the Labor Cost Analysis workbook's current Aug-2026
coverage, but labor_cost.compute_labor_cost_summary only ever looks up a
month it already has its own Output/Labor Cost figures for, so surfacing
only stops at Aug-2026 naturally today and starts including Sep onward
by itself the moment that workbook is extended -- no code change needed
here when that happens.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import openpyxl

# Real billing-period sheets are always named like "01 To 15-Jan-26" /
# "16 To 31-01-26" -- starting with the period's leading day number. Each
# workbook also carries leftover template/placeholder tabs named after the
# contractor itself (e.g. "Usman", "Usman (3)", "Pops", "Asif Ghulam
# Nabi") that, in Usman's file, still have a real Jan 1-15 Bill Duration
# copied into them -- without this check that period gets silently
# double-counted.
_PERIOD_SHEET_RE = re.compile(r"^\s*\d")

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "Shahi 1" / "labour cost"

DEPARTMENT_TO_SLUG = {
    "packing fry o": "fryo",
    "pops r10 / r 20": "pops",
    "bb r 10": "nimco",
    "bb r 20": "nimco",
}

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

_cache: dict[str, dict] | None = None  # slug -> {month_key: {monthLabel, costRs, contractors: {name: [items]}}}


def _num(v):
    return v if isinstance(v, (int, float)) else None


def _find_label_cell(ws, label: str, max_row: int = 15, max_col: int = 8) -> tuple[int, int] | tuple[None, None]:
    target = label.strip().lower()
    for r in range(1, min(ws.max_row, max_row) + 1):
        for c in range(1, min(ws.max_column, max_col) + 1):
            v = ws.cell(row=r, column=c).value
            if isinstance(v, str) and target in v.strip().lower():
                return r, c
    return None, None


def _find_total_payable_row(ws, start_row: int, max_row: int = 80) -> int | None:
    for r in range(start_row, min(ws.max_row, max_row) + 1):
        v = ws.cell(row=r, column=2).value
        if isinstance(v, str) and v.strip().lower() == "total payable":
            return r
    return None


def _parse_period_sheet(ws) -> dict | None:
    """Returns {"slug", "contractor", "monthKey", "monthLabel", "items"}
    for one real 15-day billing-period sheet, or None if this sheet isn't
    one (a template/placeholder tab with no real Bill Duration / Item
    Code block, or an unrecognized Department)."""
    if not _PERIOD_SHEET_RE.match(ws.title):
        return None

    dur_row, dur_col = _find_label_cell(ws, "bill duration")
    if dur_row is None:
        return None
    start = ws.cell(row=dur_row, column=dur_col + 1).value
    if not isinstance(start, datetime):
        return None

    dept_row, dept_col = _find_label_cell(ws, "department")
    department = ws.cell(row=dept_row, column=dept_col + 1).value if dept_row else None
    slug = DEPARTMENT_TO_SLUG.get(str(department).strip().lower()) if department else None
    if slug is None:
        return None

    cname_row, cname_col = _find_label_cell(ws, "contractor name")
    contractor = ws.cell(row=cname_row, column=cname_col + 1).value if cname_row else None
    contractor = " ".join(contractor.split()) if isinstance(contractor, str) else "Unknown"

    code_row, code_col = _find_label_cell(ws, "item code")
    if code_row is None:
        return None
    name_col = code_col + 1  # "Items Details" always sits one column right of "Item Code"
    _, qty_col = _find_label_cell(ws, "quantity packed", max_row=code_row)
    _, rate_col = _find_label_cell(ws, "rate", max_row=code_row)
    _, amount_col = _find_label_cell(ws, "amount", max_row=code_row)
    if qty_col is None or rate_col is None or amount_col is None:
        return None

    total_row = _find_total_payable_row(ws, code_row + 1)
    if total_row is None:
        return None

    items = []
    for r in range(code_row + 1, total_row):
        item_name = ws.cell(row=r, column=name_col).value
        if not isinstance(item_name, str) or not item_name.strip():
            continue  # subtotal/blank row -- every real item row has an Items Details value
        item_code = ws.cell(row=r, column=code_col).value
        quantity = _num(ws.cell(row=r, column=qty_col).value) or 0.0
        amount = _num(ws.cell(row=r, column=amount_col).value) or 0.0
        raw_rate = _num(ws.cell(row=r, column=rate_col).value)
        rate = raw_rate if raw_rate is not None else (round(amount / quantity, 2) if quantity else None)
        items.append({
            "itemCode": str(item_code).strip() if item_code is not None else None,
            "itemName": " ".join(item_name.split()),
            "quantity": quantity,
            "rate": rate,
            "amountRs": round(amount, 2),
        })

    return {
        "slug": slug,
        "contractor": contractor,
        "monthKey": f"{start.year:04d}-{start.month:02d}",
        "monthLabel": f"{MONTH_NAMES[start.month - 1]} {start.year}",
        "items": items,
    }


def _load_all() -> dict[str, dict]:
    global _cache
    if _cache is not None:
        return _cache

    result: dict[str, dict] = {}
    if DATA_DIR.exists():
        for path in DATA_DIR.glob("*Packing Contractor Bill*.xlsx"):
            if path.name.startswith("~$"):
                continue
            wb = openpyxl.load_workbook(path, data_only=True)
            # One workbook is one contractor, but its own "Contractor Name"
            # cell drifts in wording between periods (e.g. Ghulam Nabi's file
            # alternates "Mr. Asif Ghulam Nabi" / "Mr. Ghulam Nabi" across
            # different 15-day sheets for the same person) -- using the
            # first real period sheet's name as this whole file's canonical
            # label keeps one contractor as one drill-down row instead of
            # splitting into near-duplicates.
            canonical_contractor: str | None = None
            parsed_periods = []
            for sheet_name in wb.sheetnames:
                parsed = _parse_period_sheet(wb[sheet_name])
                if parsed is None:
                    continue
                if canonical_contractor is None:
                    canonical_contractor = parsed["contractor"]
                parsed_periods.append(parsed)
            wb.close()

            for parsed in parsed_periods:
                product = result.setdefault(parsed["slug"], {})
                month = product.setdefault(parsed["monthKey"], {
                    "monthLabel": parsed["monthLabel"],
                    "contractors": {},
                })
                bucket = month["contractors"].setdefault(canonical_contractor, [])
                bucket.extend(parsed["items"])

    _cache = result
    return result


def get_contractual_month(slug: str, month_key: str) -> dict | None:
    """Returns {"costRs", "contractors": [{"contractor", "totalQuantity",
    "totalAmountRs", "items": [...]}]} for this product+month, or None if
    no contractor bill data covers it at all (wrong product, or a month
    none of its contractors have billed yet)."""
    month = _load_all().get(slug, {}).get(month_key)
    if month is None:
        return None

    contractors = []
    cost_rs = 0.0
    for name, items in sorted(month["contractors"].items()):
        total_amount = round(sum(i["amountRs"] for i in items), 2)
        total_quantity = sum(i["quantity"] for i in items)
        cost_rs += total_amount
        contractors.append({
            "contractor": name,
            "totalQuantity": total_quantity,
            "totalAmountRs": total_amount,
            "items": items,
        })

    return {"costRs": round(cost_rs, 2), "contractors": contractors}
