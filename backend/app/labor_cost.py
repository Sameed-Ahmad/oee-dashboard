"""Labor cost per unit of output (packets for Packing Dept, KG for
Production Dept), read from the standalone monthly Labor Cost Analysis
workbook (backend/data/*Labor Cost Analysis*.xlsx) -- entirely separate
from the day-by-day OEE workbooks parser.py handles, and at a much coarser
grain (one figure per cost-center line per MONTH, not per day/shift), so
this is deliberately its own module.

Only Shahi-1 is covered -- the facility this dashboard's 10 products
belong to (Zain-1/Shahi-III are separate facilities also tracked in the
same workbook, but out of scope here).

Reads the workbook's own "Shahi-1 Report" sheet, which already computes
Output/Man-Hours/Labor Cost per cost-center line per month via formulas --
reusing those cached values rather than re-deriving from the raw source
sheet's own more complex per-month column blocks.

The workbook's cost-center line names don't map 1:1 onto this dashboard's
10 products (confirmed with the person maintaining both): Nimco is
reported as two separate packing lines ("R-10" and "R-20 / R-30") that
must be summed together; Coated Peanut and Namak Para share ONE combined
"Peanut & Namakpar" production line with no way to separate them at the
source, so both products show the same blended figure (mathematically,
splitting a blended cost proportionally by each product's own output
yields the identical cost-per-unit for both anyway -- there's no
information in this data to make them differ); Extruder has no
cost-center line anywhere in the workbook, so it has no figure at all.
"""
from __future__ import annotations

import re
from pathlib import Path

import openpyxl

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

REPORT_SHEET_NAME = "Shahi-1 Report"

TABLE_HEADERS = {
    "output": "Output",
    "manHours": "Total Man-Hours (Hrs)",
    "laborCost": "Total Labor Cost (Rs.)",
}

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_HEADER_RE = re.compile(r"^([A-Za-z]{3})-(\d{4})$")

# Product slug -> source line name(s) in the workbook to sum together.
# See module docstring for why Nimco/Coated Peanut/Namak Para aren't
# simple 1:1 matches, and why Extruder is absent entirely.
PRODUCT_SOURCE_LINES: dict[str, list[str]] = {
    "fryo": ["Packing -Fry -O"],
    "ishida": ["Packing - Ishida"],
    "pops": ["Packing - Pops & Weato"],
    "nimco": ["Packing - R-10", "Packing - R-20 / R-30"],
    "hnc-1": ["Production - H&C - 1"],
    "hnc-3": ["Production - H&C - 3"],
    "kuiper": ["Production - Kuiper"],
    "coated-peanut": ["Production - Peanut & Namakpar"],
    "namak-para": ["Production - Peanut & Namakpar"],
}

SHARED_PRODUCTS = {"coated-peanut", "namak-para"}

_workbook_cache: object | None = None
_workbook_loaded = False


def _num(v) -> float:
    return v if isinstance(v, (int, float)) else 0.0


def _load_workbook():
    global _workbook_cache, _workbook_loaded
    if not _workbook_loaded:
        _workbook_loaded = True
        candidates = sorted(DATA_DIR.glob("*Labor Cost Analysis*.xlsx"))
        _workbook_cache = openpyxl.load_workbook(candidates[0], data_only=True) if candidates else None
    return _workbook_cache


def _find_table(ws, label: str) -> tuple[int, dict[str, int]] | None:
    """Finds a table's anchor row by its exact label in column A, and
    returns (header_row, {"Jan-2026": column, ...}) for every month column
    found one row below it."""
    for r in range(1, ws.max_row + 1):
        if ws.cell(row=r, column=1).value == label:
            header_row = r + 1
            months = {}
            for c in range(1, ws.max_column + 1):
                v = ws.cell(row=header_row, column=c).value
                if isinstance(v, str) and MONTH_HEADER_RE.match(v):
                    months[v] = c
            return header_row, months
    return None


def _department_lines(ws, table_header_row: int, department: str) -> dict[str, int]:
    """Within a table (given its header row), finds `department`'s own row
    and returns {sub-department name: row number} for every line under it,
    stopping at the next populated column-A cell (the next department)."""
    lines: dict[str, int] = {}
    dept_row = None
    for r in range(table_header_row + 1, ws.max_row + 1):
        col1 = ws.cell(row=r, column=1).value
        if dept_row is None:
            if col1 == department:
                dept_row = r
            continue
        if col1 not in (None, ""):
            break
        sub = ws.cell(row=r, column=2).value
        if sub is None:
            break
        lines[str(sub).strip()] = r
    return lines


def compute_labor_cost_summary(slug: str) -> dict | None:
    """Returns {"sourceLines": [...], "shared": bool, "months": [...]}, or
    None if this product has no labor-cost line registered at all -- no
    workbook found, or genuinely absent (Extruder)."""
    source_lines = PRODUCT_SOURCE_LINES.get(slug)
    if not source_lines:
        return None

    wb = _load_workbook()
    if wb is None or REPORT_SHEET_NAME not in wb.sheetnames:
        return None
    ws = wb[REPORT_SHEET_NAME]

    output_table = _find_table(ws, TABLE_HEADERS["output"])
    hours_table = _find_table(ws, TABLE_HEADERS["manHours"])
    cost_table = _find_table(ws, TABLE_HEADERS["laborCost"])
    if not (output_table and hours_table and cost_table):
        return None

    department = "Production" if source_lines[0].startswith("Production") else "Packing"

    output_header_row, output_months = output_table
    hours_header_row, hours_months = hours_table
    cost_header_row, cost_months = cost_table

    output_lines = _department_lines(ws, output_header_row, department)
    hours_lines = _department_lines(ws, hours_header_row, department)
    cost_lines = _department_lines(ws, cost_header_row, department)

    unit = ""
    for line in source_lines:
        if line in output_lines:
            unit = ws.cell(row=output_lines[line], column=3).value or ""
            break

    common_headers = set(output_months) & set(hours_months) & set(cost_months)

    def sort_key(header: str) -> tuple[int, int]:
        mon, year = header.split("-")
        return int(year), MONTH_ABBR.index(mon)

    months_result = []
    for header in sorted(common_headers, key=sort_key):
        total_output = sum(
            _num(ws.cell(row=output_lines[line], column=output_months[header]).value)
            for line in source_lines if line in output_lines
        )
        if total_output <= 0:
            continue  # month not filled in yet on the source workbook

        total_hours = sum(
            _num(ws.cell(row=hours_lines[line], column=hours_months[header]).value)
            for line in source_lines if line in hours_lines
        )
        total_cost = sum(
            _num(ws.cell(row=cost_lines[line], column=cost_months[header]).value)
            for line in source_lines if line in cost_lines
        )

        mon, year = header.split("-")
        month_idx = MONTH_ABBR.index(mon)
        months_result.append({
            "month": f"{year}-{month_idx + 1:02d}",
            "monthLabel": f"{MONTH_NAMES[month_idx]} {year}",
            "manHours": round(total_hours, 1),
            "laborCost": round(total_cost, 2),
            "output": round(total_output, 1),
            "outputUnit": unit,
            "costPerUnit": round(total_cost / total_output, 4),
            "manHoursPerUnit": round(total_hours / total_output, 6),
        })

    return {
        "sourceLines": source_lines,
        "shared": slug in SHARED_PRODUCTS,
        "months": months_result,
    }
