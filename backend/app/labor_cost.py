"""Labor cost per unit of output (packets for Packing Dept, KG for
Production Dept), read from the standalone monthly Labor Cost Analysis
workbook (backend/data/labour cost/*Labor Cost Analysis*.xlsx) -- entirely separate
from the day-by-day OEE workbooks parser.py handles, and at a much coarser
grain (one figure per cost-center line per MONTH, not per day/shift), so
this is deliberately its own module.

Also exposes compute_output_reconciliation, which reuses this same
workbook's Output table to compare it against this dashboard's own
OEE-tracked output -- see that function's docstring for why the two
numbers are expected to differ (they measure different points in the
pipeline) rather than being a data-quality bug to fix.

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
information in this data to make them differ); Extruder's line is filed
as "Production - Pops" (see PRODUCT_SOURCE_LINES), not a line literally
named "Extruder" -- it's Pops' upstream production-stage machine, not a
separate product with its own line.
"""
from __future__ import annotations

import re
from pathlib import Path

import openpyxl

from .contractor_labor import get_contractual_month
from .maintenance_cost import compute_maintenance_repair_cost

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "Shahi 1" / "labour cost"

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
# simple 1:1 matches. Extruder's line is filed as "Production - Pops" --
# NOT a typo or a different product: Extruder is Pops' upstream
# production-stage machine (see gas.py module docstring for the same
# mix-up found in the gas meter readings), and this line's own KG figures
# track Extruder's OEE-tracked output almost exactly (e.g. June 2026:
# workbook 26,274.5 KG vs. OEE-tracked 26,646 KG).
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
    "extruder": ["Production - Pops"],
}

SHARED_PRODUCTS = {"coated-peanut", "namak-para"}

RAW_SHEET_NAME = "Shahi-1"

# The raw "Shahi-1" sheet's own department grouping -- every top-level
# department EXCEPT Packing and Production, confirmed identical (same 9
# names) on both the raw sheet and the "Shahi-1 Report" sheet's Total
# Labor Cost table, across Jan-26 and Aug-26. Shahi 3's analogous figure
# comes from a dedicated "Support Department" sheet; here the same kind
# of cost sits as ordinary top-level rows in the same table as Packing/
# Production.
SUPPORT_DEPARTMENTS = [
    "Factory Administration & HR", "FG Store", "Maintenance - Electrical",
    "Maintenance - Mechanical", "Management", "Power Generation",
    "QA Lab.R&D,QMS", "RM STORE", "Tech. Store & Purchase",
]

# Packing sub-line (raw "Shahi-1" sheet label, same strings as
# PRODUCT_SOURCE_LINES) -> product slug, for every Packing product --
# used to look up contractor_labor.py's real per-item contractual figure
# for that line. get_contractual_month naturally returns None for Ishida
# (no contractor file exists for it), so no code branch is needed to
# special-case it -- it falls straight through to "use this line's own
# total unchanged" in compute_shahi1_manufacturing_overhead /
# compute_department_labor_cost.
PACKING_LINE_TO_SLUG = {
    line: slug for slug, lines in PRODUCT_SOURCE_LINES.items()
    for line in lines if line.startswith("Packing")
}

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


def _department_total_row(ws, table_header_row: int, department: str) -> int | None:
    """Finds `department`'s own TOTAL row within a table (e.g. the
    "Packing" row itself, already the sum of every one of its cost-center
    lines) -- distinct from _department_lines, which finds its children."""
    for r in range(table_header_row + 1, ws.max_row + 1):
        if ws.cell(row=r, column=1).value == department:
            return r
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


def _find_raw_month_blocks(ws) -> dict[str, int]:
    """{"2026-01": 3, ...} -- each month's block-start column (the
    "Permanent # staff" column of that month's own 9-column block) on
    the raw "Shahi-1" sheet, located by its own "For the month of
    <Mon>-<Year>" marker in row 2 -- not fixed arithmetic (every block IS
    9 columns wide in practice, but relying on that alone would silently
    misalign if a month's block were ever inserted/resized)."""
    blocks: dict[str, int] = {}
    month_re = re.compile(r"for the month of\s+([a-z]+)-(\d{4})", re.IGNORECASE)
    abbr_lower = [a.lower() for a in MONTH_ABBR]
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=2, column=c).value
        if not isinstance(v, str):
            continue
        m = month_re.search(v.strip().lower())
        if not m:
            continue
        mon_abbr, year = m.group(1)[:3], m.group(2)
        if mon_abbr not in abbr_lower:
            continue
        month_num = abbr_lower.index(mon_abbr) + 1
        blocks[f"{year}-{month_num:02d}"] = c
    return blocks


def _parse_raw_shahi1_sheet(ws) -> dict[str, dict]:
    """Returns {month_key: {"lines": {sub_department_label:
    {"permanentRs", "contractualRs", "totalRs"}}, "departmentOf":
    {sub_department_label: top_level_department}}}.

    Reads the RAW "Shahi-1" sheet -- NOT the "Shahi-1 Report" sheet's own
    pre-combined Total Labor Cost table everything else in this module
    uses -- because this is the only place Permanent and the workbook's
    own Contractual figures are reported SEPARATELY per line, needed to
    replace Packing's understated contractual portion with the real
    figure from contractor_labor.py (see
    compute_shahi1_manufacturing_overhead)."""
    blocks = _find_raw_month_blocks(ws)
    if not blocks:
        return {}

    header_row = None
    for r in range(1, 6):
        if ws.cell(row=r, column=1).value == "Department":
            header_row = r
            break
    if header_row is None:
        return {}

    result: dict[str, dict] = {}
    for month_key, start_col in blocks.items():
        perm_col, contract_col, total_col = start_col + 2, start_col + 5, start_col + 8
        lines: dict[str, dict] = {}
        department_of: dict[str, str] = {}
        current_dept: str | None = None
        for r in range(header_row + 1, ws.max_row + 1):
            a = ws.cell(row=r, column=1).value
            if isinstance(a, str) and a.strip().lower() == "total":
                break
            if isinstance(a, str) and a.strip():
                current_dept = " ".join(a.split())
            b = ws.cell(row=r, column=2).value
            if not isinstance(b, str) or not b.strip():
                continue
            sub_label = " ".join(b.split())
            lines[sub_label] = {
                "permanentRs": _num(ws.cell(row=r, column=perm_col).value) or 0.0,
                "contractualRs": _num(ws.cell(row=r, column=contract_col).value) or 0.0,
                "totalRs": _num(ws.cell(row=r, column=total_col).value) or 0.0,
            }
            if current_dept:
                department_of[sub_label] = current_dept
        if lines:
            result[month_key] = {"lines": lines, "departmentOf": department_of}
    return result


def _corrected_packing_cost(lines: dict[str, dict], department_of: dict[str, str], month_key: str) -> float:
    """One month's Packing Dept total, with each line that has real
    per-item contractor-bill data (contractor_labor.py) -- today Fry-O,
    Pops, and Nimco -- corrected to Permanent + that REAL contractual
    figure instead of the line's own contractual figure, confirmed to
    understate the real one by a wide margin (e.g. Fry-O Jan-26: the
    workbook's own Contractual column says Rs. 134,988; the real
    contractor bills for that same month total Rs. 1,060,974 -- nearly
    8x higher). Lines with no contractor-bill data (Ishida, Printing)
    keep their own existing total unchanged, since there's no better
    figure available for them.

    Nimco is filed as two raw-sheet lines (R-10, R-20/R-30) that both
    resolve to the same "nimco" slug -- its real contractual figure
    already covers both combined, so it's added only once (on whichever
    line is encountered first), with the second line contributing its
    own Permanent portion only, never a second copy of the real
    contractual total."""
    cost = 0.0
    slugs_applied: set[str] = set()
    for sub_label, data in lines.items():
        if department_of.get(sub_label) != "Packing":
            continue
        slug = PACKING_LINE_TO_SLUG.get(sub_label)
        real_contractual = get_contractual_month(slug, month_key) if slug else None
        if real_contractual:
            cost += data["permanentRs"]
            if slug not in slugs_applied:
                cost += real_contractual["costRs"]
                slugs_applied.add(slug)
        else:
            cost += data["totalRs"]
    return cost


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

    raw = _parse_raw_shahi1_sheet(wb[RAW_SHEET_NAME]) if RAW_SHEET_NAME in wb.sheetnames else {}

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
        month_key = f"{year}-{month_idx + 1:02d}"

        contractual = get_contractual_month(slug, month_key)
        contractual_cost = contractual["costRs"] if contractual else None
        contractors = contractual["contractors"] if contractual else []

        # laborCost (this Report-sheet figure) is Permanent + the
        # workbook's OWN contractual estimate combined -- confirmed far
        # smaller than the real per-item contractor bills for
        # Fry-O/Pops/Nimco (e.g. Fry-O Jan-26: workbook's own Contractual
        # column Rs. 134,988 vs. the real bills' Rs. 1,060,974).
        # permanentLaborCostRs pulls the TRUE Permanent-only portion out
        # of that blend, from the raw "Shahi-1" sheet (None if that sheet
        # has no data for this month). "Total Cost" then simply adds the
        # REAL contractual on top of permanentLaborCostRs (never
        # laborCost + contractualLaborCostRs, which would double-count
        # the workbook's own estimate) -- same corrected approach as
        # _corrected_packing_cost, just per product instead of for the
        # whole department. Where no real contractual exists for this
        # product (Ishida), totalCostRs falls back to laborCost unchanged
        # (nothing to correct, nothing better to use) rather than
        # dropping that workbook estimate from the total entirely.
        month_raw = raw.get(month_key)
        permanent_sum = (
            sum(month_raw["lines"][line]["permanentRs"] for line in source_lines if line in month_raw["lines"])
            if month_raw is not None else None
        )
        if permanent_sum is not None and contractual_cost is not None:
            full_total_cost = permanent_sum + contractual_cost
        else:
            full_total_cost = total_cost

        months_result.append({
            "month": month_key,
            "monthLabel": f"{MONTH_NAMES[month_idx]} {year}",
            "manHours": round(total_hours, 1),
            "laborCost": round(total_cost, 2),
            "output": round(total_output, 1),
            "outputUnit": unit,
            "costPerThousandUnits": round(total_cost / total_output * 1000, 2),
            "manHoursPerThousandUnits": round(total_hours / total_output * 1000, 3),
            "permanentLaborCostRs": round(permanent_sum, 2) if permanent_sum is not None else None,
            "permanentCostPerThousandUnits": round(permanent_sum / total_output * 1000, 2) if permanent_sum is not None else None,
            "contractualLaborCostRs": contractual_cost,
            "contractualCostPerThousandUnits": round(contractual_cost / total_output * 1000, 2) if contractual_cost is not None else None,
            "contractors": contractors,
            "totalCostRs": round(full_total_cost, 2),
            "totalCostPerThousandUnits": round(full_total_cost / total_output * 1000, 2),
        })

    return {
        "sourceLines": source_lines,
        "shared": slug in SHARED_PRODUCTS,
        "months": months_result,
    }


def compute_output_reconciliation(slug: str, records: list[dict]) -> dict | None:
    """Compares this dashboard's own OEE-tracked monthly output ("Produced"
    -- summed from `records`, the same day records every other endpoint
    uses) against the labor-cost workbook's own Output Input figure for the
    same source line(s) ("Received").

    These are two independently-maintained numbers for two different
    points in the pipeline -- machine-counted output vs. the quantity
    actually received into sellable finished-goods stock -- not the same
    quantity reported twice, so a gap between them is a genuine yield
    figure to track, not a data error to reconcile away.

    Uses `actualCounter` (the gross machine count, before quality-based
    rejection) rather than `stockTransferred` (already net of quality
    loss) for "Produced" -- Received can only ever be a subset of what was
    gross-produced, so actualCounter is the correct upper bound to compare
    against; stockTransferred would already have quality loss baked in,
    double-counting that loss against Received's own gap.

    Returns None if this product has no source line registered at all (see
    PRODUCT_SOURCE_LINES) -- same scope as compute_labor_cost_summary."""
    source_lines = PRODUCT_SOURCE_LINES.get(slug)
    if not source_lines:
        return None

    wb = _load_workbook()
    if wb is None or REPORT_SHEET_NAME not in wb.sheetnames:
        return None
    ws = wb[REPORT_SHEET_NAME]

    output_table = _find_table(ws, TABLE_HEADERS["output"])
    if not output_table:
        return None
    output_header_row, output_months = output_table

    department = "Production" if source_lines[0].startswith("Production") else "Packing"
    output_lines = _department_lines(ws, output_header_row, department)

    unit = ""
    for line in source_lines:
        if line in output_lines:
            unit = ws.cell(row=output_lines[line], column=3).value or ""
            break

    def sort_key(header: str) -> tuple[int, int]:
        mon, year = header.split("-")
        return int(year), MONTH_ABBR.index(mon)

    produced_by_month: dict[str, float] = {}
    for r in records:
        month_key = r["date"][:7]
        produced_by_month[month_key] = produced_by_month.get(month_key, 0.0) + r["actualCounter"]

    months_result = []
    for header in sorted(output_months, key=sort_key):
        received = sum(
            _num(ws.cell(row=output_lines[line], column=output_months[header]).value)
            for line in source_lines if line in output_lines
        )
        if received <= 0:
            continue  # month not filled in yet on the source workbook

        mon, year = header.split("-")
        month_idx = MONTH_ABBR.index(mon)
        month_key = f"{year}-{month_idx + 1:02d}"
        produced = produced_by_month.get(month_key, 0.0)
        if produced <= 0:
            continue  # no OEE-tracked data for this month (yet) -- nothing to compare

        gap = round(produced - received, 1)

        months_result.append({
            "month": month_key,
            "monthLabel": f"{MONTH_NAMES[month_idx]} {year}",
            "outputUnit": unit,
            "produced": round(produced, 1),
            "received": round(received, 1),
            "gap": gap,
            "gapPct": round(gap / produced * 100, 2),
        })

    return {
        "sourceLines": source_lines,
        "shared": slug in SHARED_PRODUCTS,
        "months": months_result,
    }


def compute_department_labor_cost(department: str, product_slugs: list[str] | None = None) -> dict | None:
    """Total Labor Cost (Rs.) -- and an accurate Cost per 1,000 units --
    for an entire department ("Packing" or "Production"), summed across
    every month filled in on the source workbook so far. Reads the
    workbook's own department TOTAL rows directly, in both the Labor Cost
    and Output tables -- already the sum of every cost-center line in
    that department, including lines with no 1:1 mapping to one of this
    dashboard's 10 products (e.g. "Packing - Printing") -- rather than
    summing our own per-product figures, which would double-count Coated
    Peanut/Namak Para's shared line and miss unmapped lines entirely.
    costPerThousandUnits is computed from these same summed totals (total
    Rs. / total output), not by averaging each month's own ratio, so it's
    correctly output-weighted across months of very different volume.

    If `product_slugs` is given (every product under this department), the
    per-item contractor bills (contractor_labor.py) are also folded into
    totalRs/costPerThousandUnits -- unlike compute_labor_cost_summary's
    per-PRODUCT figures (which keep the two deliberately separate so a
    product's own table can show both), this department-wide card is
    meant to read as one genuine "what did labor cost us" total.
    Omitting product_slugs (or passing none) leaves contractualRs at 0,
    i.e. totalRs == laborOnlyRs, same as before this parameter existed.

    For "Production", this is a straight add: `total_cost` (this
    workbook's own Total Labor Cost row) + the real contractual figure.
    For "Packing", a straight add would DOUBLE-COUNT: this workbook's own
    Total Labor Cost row already includes its OWN (confirmed understated
    -- see _corrected_packing_cost) contractual estimate for Fry-O/Pops/
    Nimco, so adding the real figure on top would count that portion
    twice. Packing instead uses _corrected_packing_cost, which replaces
    -- not adds to -- each line's own contractual estimate with the real
    one where available, keeping the line's own total unchanged where
    it isn't (Ishida, Printing). laborOnlyRs there is redefined as the
    pure Permanent-only sum (not "workbook total minus correction") so
    laborOnlyRs + contractualRs == totalRs stays true either way.

    Returns None if the workbook, either table, or this department's row
    in either can't be found, or no month has both cost and output
    filled in yet."""
    wb = _load_workbook()
    if wb is None or REPORT_SHEET_NAME not in wb.sheetnames:
        return None
    ws = wb[REPORT_SHEET_NAME]

    cost_table = _find_table(ws, TABLE_HEADERS["laborCost"])
    output_table = _find_table(ws, TABLE_HEADERS["output"])
    if not cost_table or not output_table:
        return None
    cost_header_row, cost_months = cost_table
    output_header_row, output_months = output_table

    cost_row = _department_total_row(ws, cost_header_row, department)
    output_row = _department_total_row(ws, output_header_row, department)
    if cost_row is None or output_row is None:
        return None

    unit = ws.cell(row=output_row, column=3).value or ""

    def sort_key(header: str) -> tuple[int, int]:
        mon, year = header.split("-")
        return int(year), MONTH_ABBR.index(mon)

    common_headers = set(cost_months) & set(output_months)

    total_cost = 0.0
    total_output = 0.0
    months_included = []
    for header in sorted(common_headers, key=sort_key):
        cost_value = _num(ws.cell(row=cost_row, column=cost_months[header]).value)
        output_value = _num(ws.cell(row=output_row, column=output_months[header]).value)
        if cost_value <= 0 or output_value <= 0:
            continue
        total_cost += cost_value
        total_output += output_value
        mon, year = header.split("-")
        months_included.append(f"{year}-{MONTH_ABBR.index(mon) + 1:02d}")

    if not months_included:
        return None

    if department == "Packing" and product_slugs and RAW_SHEET_NAME in wb.sheetnames:
        raw = _parse_raw_shahi1_sheet(wb[RAW_SHEET_NAME])
        combined_cost = 0.0
        permanent_sum = 0.0
        for month_key in months_included:
            month_raw = raw.get(month_key)
            if month_raw is None:
                combined_cost += 0.0  # no raw-sheet data for this month -- see fallback below
                continue
            lines, department_of = month_raw["lines"], month_raw["departmentOf"]
            combined_cost += _corrected_packing_cost(lines, department_of, month_key)
            permanent_sum += sum(
                data["permanentRs"] for label, data in lines.items() if department_of.get(label) == "Packing"
            )
        if combined_cost <= 0:
            combined_cost, permanent_sum = total_cost, total_cost  # raw sheet unavailable -- fall back to the uncorrected total
        contractual_cost = combined_cost - permanent_sum
    else:
        contractual_cost = 0.0
        for slug in product_slugs or []:
            for month_key in months_included:
                contractual_month = get_contractual_month(slug, month_key)
                if contractual_month:
                    contractual_cost += contractual_month["costRs"]
        combined_cost = total_cost + contractual_cost
        permanent_sum = total_cost - contractual_cost

    return {
        "totalRs": round(combined_cost, 2),
        "laborOnlyRs": round(permanent_sum, 2),
        "contractualRs": round(contractual_cost, 2),
        "firstMonth": months_included[0],
        "lastMonth": months_included[-1],
        "costPerThousandUnits": round(combined_cost / total_output * 1000, 2),
        "outputUnit": unit,
    }


def compute_shahi1_manufacturing_overhead(department: str) -> dict | None:
    """Month by month: this department's own direct labor cost (Packing
    gets the same correction as compute_department_labor_cost -- real
    contractor bills swapped in for Fry-O/Pops/Nimco instead of the
    workbook's own understated contractual figure, see
    _corrected_packing_cost; Production uses its own Total Labor Cost
    row unchanged, since no independent contractor-bill data exists to
    correct it with) PLUS the sum of every Support department's own
    Total Labor Cost (see SUPPORT_DEPARTMENTS) PLUS this department's own
    Maintenance & Repair cost (see maintenance_cost.py's separate
    transaction-level ERP export), divided by this department's own
    output -- "what a unit really costs once overhead is loaded onto
    it," the same concept as shahi3_cost.py's
    compute_shahi3_manufacturing_overhead (same return shape too, so one
    frontend renderer serves both units).

    No electricity component -- unlike Shahi 3's version, Shahi-1's
    electricity data (electricity.py) is only ever a single facility-wide
    total, not split by department or by Support vs. Packing/Production,
    so there's no reliable way to add it here without inventing a split
    the source data doesn't support.

    Support's and Maintenance & Repair's costs are NOT split between
    Packing and Production -- each call independently adds the FULL
    amount of both, so the two departments' own totalOverheadCostRs
    figures must never be summed together (that would double-count
    them)."""
    if department not in ("Packing", "Production"):
        return None

    wb = _load_workbook()
    if wb is None or REPORT_SHEET_NAME not in wb.sheetnames or RAW_SHEET_NAME not in wb.sheetnames:
        return None
    ws = wb[REPORT_SHEET_NAME]
    raw = _parse_raw_shahi1_sheet(wb[RAW_SHEET_NAME])
    if not raw:
        return None

    maintenance_result = compute_maintenance_repair_cost(department, unit_slug="shahi-1")
    maintenance_by_month = (
        {m["month"]: m["maintenanceRepairCostRs"] for m in maintenance_result["months"]}
        if maintenance_result else {}
    )

    output_table = _find_table(ws, TABLE_HEADERS["output"])
    if output_table is None:
        return None
    output_header_row, output_months = output_table
    output_row = _department_total_row(ws, output_header_row, department)
    if output_row is None:
        return None
    unit = ws.cell(row=output_row, column=3).value or ""

    def sort_key(header: str) -> tuple[int, int]:
        mon, year = header.split("-")
        return int(year), MONTH_ABBR.index(mon)

    months = []
    for header in sorted(output_months, key=sort_key):
        mon, year = header.split("-")
        month_idx = MONTH_ABBR.index(mon)
        month_key = f"{year}-{month_idx + 1:02d}"
        month_raw = raw.get(month_key)
        if month_raw is None:
            continue
        output_value = _num(ws.cell(row=output_row, column=output_months[header]).value)
        if not output_value or output_value <= 0:
            continue

        lines, department_of = month_raw["lines"], month_raw["departmentOf"]
        if department == "Packing":
            dept_cost = _corrected_packing_cost(lines, department_of, month_key)
        else:
            dept_cost = sum(
                data["totalRs"] for label, data in lines.items() if department_of.get(label) == "Production"
            )
        support_cost = sum(
            data["totalRs"] for label, data in lines.items() if department_of.get(label) in SUPPORT_DEPARTMENTS
        )
        maintenance_cost = maintenance_by_month.get(month_key, 0.0)
        total_cost = dept_cost + support_cost + maintenance_cost

        months.append({
            "month": month_key,
            "monthLabel": f"{MONTH_NAMES[month_idx]} {year}",
            "output": round(output_value, 1),
            "outputUnit": unit,
            "departmentCostRs": round(dept_cost, 2),
            "supportCostRs": round(support_cost, 2),
            "maintenanceRepairCostRs": round(maintenance_cost, 2),
            "totalOverheadCostRs": round(total_cost, 2),
            "costPerThousandUnits": round(total_cost / output_value * 1000, 2),
        })
    return {"months": months} if months else None
