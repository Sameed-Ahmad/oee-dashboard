"""Shahi 1's total electricity consumption, read from the standalone
monthly Energy Consumption Report CSV (backend/data/utility/*Energy
Consumption*.csv) -- a facility-wide report covering Zain-1 and Shahi-1
together across 4 power sources (Gas Generator, Diesel Generator,
K-Electric, Solar). Not derived from the OEE workbooks or any other
module here -- entirely its own small file, read off a utility bill each
month by hand.

This is a flattened CSV export of a spreadsheet with merged header cells
spanning multiple source rows -- Python's csv module collapses a quoted
cell's embedded newlines into one logical row, so the apparent "row
number" when eyeballing the raw file does NOT match the logical row
index; parsing here locates each month's row by its own name
(row[0] in MONTH_NAMES) rather than a fixed offset. Column positions
within a row ARE fixed, confirmed directly against the sheet's own
two-row header (see COL_* below) -- there's no repeatable per-column
label to search by the way labor_cost.py/gas.py do.

Shahi-1's own unit total isn't separately metered -- confirmed with the
person maintaining the sheet: the sheet computes it as (facility-wide
Total Units Including Solar) minus (Zain-1's own directly-metered total,
itself Zain-1's base reading plus its share of a shared "Compressor"
pool), and reports that result directly as "Shahi-1 Including
Compressor" -- this module just reads that column.

Only a facility-wide TOTAL is available for Shahi-1, not broken down by
source (Gas/Diesel/KE/Solar) -- the sheet's Zain-1/Shahi-1 split is only
ever computed on the combined total across all 4 sources, never per
source individually, so there's no way to attribute units/cost to one
source for Shahi-1 specifically (confirmed with the person running this
dashboard -- deliberately out of scope for now, not an oversight). Each
month's "sources" list is therefore the FACILITY-WIDE (Zain-1 + Shahi-1
combined) breakdown per source -- shown for context in the drill-down
alongside Shahi-1's own % share of the combined total, not an attempt to
split each source between the two facilities.

Cost per month is DERIVED, not a column the sheet provides directly:
Shahi-1's units x that month's blended "Average unit cost Including
Solar" -- the same per-unit rate the sheet itself uses to turn the
facility-wide total into a blended cost, applied to Shahi-1's own share
of that total.
"""
from __future__ import annotations

import csv
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "utility"

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Fixed column positions in the flattened CSV -- see module docstring.
COL_MONTH = 0
COL_GAS_UNITS = 1
COL_GAS_BILL_RS = 2
COL_GAS_UNIT_COST = 3
COL_DIESEL_UNITS = 4
COL_DIESEL_BILL_RS = 5
COL_DIESEL_UNIT_COST = 6
COL_KE_UNITS = 7
COL_KE_BILL_RS = 8
COL_KE_UNIT_COST = 9
COL_SOLAR_UNITS = 10
COL_TOTAL_UNITS_INCL_SOLAR = 11
COL_TOTAL_AMOUNT_RS = 13
COL_AVG_UNIT_COST_INCL_SOLAR = 15
COL_SHAHI_UNITS_INCL_COMPRESSOR = 21
COL_SHAHI_SHARE_PCT = 22

# (display name, units col, bill col, unit-cost col) -- Solar has no
# bill/unit-cost columns in the source sheet (it's free/self-generated),
# so those are None.
SOURCE_COLUMNS = [
    ("Gas Generator", COL_GAS_UNITS, COL_GAS_BILL_RS, COL_GAS_UNIT_COST),
    ("Diesel Generator", COL_DIESEL_UNITS, COL_DIESEL_BILL_RS, COL_DIESEL_UNIT_COST),
    ("K-Electric", COL_KE_UNITS, COL_KE_BILL_RS, COL_KE_UNIT_COST),
    ("Solar", COL_SOLAR_UNITS, None, None),
]

_cache: list[dict] | None = None


def _num(raw: str) -> float | None:
    """Parses a value like "1,234.56" -> 1234.56. Returns None for blank
    cells or non-numeric placeholders (e.g. "Closed", "-") rather than
    raising -- a handful of cells elsewhere in this sheet use those, even
    though none of the columns this module reads currently do."""
    raw = raw.strip().replace(",", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _load_rows() -> list[dict]:
    global _cache
    if _cache is not None:
        return _cache

    paths = list(DATA_DIR.glob("*Energy Consumption*.csv"))
    if not paths:
        _cache = []
        return _cache

    with paths[0].open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))

    results = []
    for row in rows:
        if not row or row[COL_MONTH].strip() not in MONTH_NAMES:
            continue
        shahi_units = _num(row[COL_SHAHI_UNITS_INCL_COMPRESSOR])
        avg_cost_incl_solar = _num(row[COL_AVG_UNIT_COST_INCL_SOLAR])
        if shahi_units is None or avg_cost_incl_solar is None:
            continue  # month not filled in yet on the source sheet

        month_idx = MONTH_NAMES.index(row[COL_MONTH].strip())
        sources = [
            {
                "name": name,
                "units": _num(row[units_col]),
                "billRs": _num(row[bill_col]) if bill_col is not None else None,
                "unitCost": _num(row[cost_col]) if cost_col is not None else None,
            }
            for name, units_col, bill_col, cost_col in SOURCE_COLUMNS
        ]
        results.append({
            "month": f"2026-{month_idx + 1:02d}",
            "monthLabel": f"{MONTH_NAMES[month_idx]} 2026",
            "unitsConsumed": round(shahi_units, 2),
            "costRs": round(shahi_units * avg_cost_incl_solar, 2),
            "sharePct": _num(row[COL_SHAHI_SHARE_PCT]),
            "facilityTotalUnits": _num(row[COL_TOTAL_UNITS_INCL_SOLAR]),
            "facilityTotalCostRs": _num(row[COL_TOTAL_AMOUNT_RS]),
            "facilityAvgUnitCost": avg_cost_incl_solar,
            "sources": sources,
        })
    _cache = results
    return _cache


def compute_electricity_summary() -> dict | None:
    """Shahi-1's own monthly electricity units and (derived) cost -- see
    module docstring for how these are read/computed from the
    facility-wide sheet. Returns None if the source CSV isn't found."""
    rows = _load_rows()
    if not rows:
        return None
    return {"months": rows}
