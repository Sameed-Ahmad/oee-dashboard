"""Maintenance & Repair cost for Shahi 1 and Shahi 3, each read from its
own standalone transaction-level ERP export
(backend/data/<Unit>/ERP/*csi*item*.xlsx -- Shahi 1: "all trasaction csi
item jan oct2026.xlsx"; Shahi 3: "ALL TRASACTION SHAHI 3 CSI ITEM JAN TO
OCT2026.xlsx") -- one row per spare-part/consumable transaction,
entirely separate from finished_goods.py's monthly Transfer Order
Shipment files in Shahi 1's same ERP folder. Same column layout and
rules for both units (Shahi 3's file even uses the identical "-PKF-"/
"-PRF-" warehouse-code convention, just under a "U3-" prefix instead of
"U1-"), so one module serves both -- column lookup is by header text,
not position, since Shahi 3's file has "WAREHOUSE" one column over from
where Shahi 1's "warehouse" sits.

Only rows with Issue == "Sold" count (confirmed with the person running
the dashboard: every genuine spend transaction in this export is marked
"Sold" there; Shahi 1's file also has blank-Issue rows, pending/unposted
and excluded -- Shahi 3's file has none at all, every row is "Sold").
The "Financial cost amount" column is negative (a stores-issue
convention, cost leaving the store) and is summed as its absolute value.

Each row's "warehouse" column decides which department(s) it counts
against -- confirmed with the person running the dashboard, not guessed:

- A code containing "-PKF-" (e.g. "U1-PKF-NMK", "U3-PKF-SNK") -> Packing
  Dept ONLY.
- A code containing "-PRF-" (e.g. "U1-PRF-FRY", "U3-PRF-EXT") ->
  Production Dept ONLY. Matched case-insensitively -- both files have a
  lowercase typo variant of one of their own real codes ("U1-PRF-Fry",
  "U3-PRF-ext", "U3-PKF-snk").
- Anything else -- Maintenance/Admin/FG-Warehouse/QA/RM-Store/Tech-
  Store/R&D-type codes, AND, for Shahi 1 specifically, two large
  "neither" buckets confirmed with the person running the dashboard
  despite their size: "#N/A" (a broken warehouse lookup in that export,
  not a real category) and "U1-PWH-SEP" (Shahi 3's own file has no
  equivalent -- every one of its rows already has a clean warehouse
  code) -- counts in BOTH Packing and Production. "Both" means each
  department's own Maintenance & Repair figure independently includes
  the full amount, same non-split principle as
  compute_*_manufacturing_overhead's Support Department cost: never sum
  Packing's and Production's own totals together, that double-counts
  this shared portion.

Monthly, using each row's own "Financial date" (confirmed identical to
"Physical date" for every Sold row in both exports, so there's no
ambiguity about which to use).
"""
from __future__ import annotations

from pathlib import Path

import openpyxl

DATA_DIRS = {
    "shahi-1": Path(__file__).resolve().parent.parent / "data" / "Shahi 1" / "ERP",
    "shahi-3": Path(__file__).resolve().parent.parent / "data" / "Shahi 3" / "ERP",
}

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

_cache: dict[str, dict[str, dict]] = {}  # unit_slug -> month_key -> {monthLabel, packingRs, productionRs}


def _num(v):
    return v if isinstance(v, (int, float)) else None


def _find_header_columns(ws) -> dict[str, int] | None:
    header = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=1, column=c).value
        if isinstance(v, str):
            header[v.strip().lower()] = c
    required = ["financial date", "warehouse", "financial cost amount", "issue"]
    if not all(k in header for k in required):
        return None
    return {
        "date": header["financial date"],
        "warehouse": header["warehouse"],
        "cost": header["financial cost amount"],
        "issue": header["issue"],
    }


def _bucket_for_warehouse(warehouse) -> str:
    """Returns "packing", "production", or "both" -- see module
    docstring for the full rule and why Shahi 1's #N/A/U1-PWH-SEP go to
    "both"."""
    norm = str(warehouse).strip().lower() if warehouse is not None else ""
    if "-pkf-" in norm:
        return "packing"
    if "-prf-" in norm:
        return "production"
    return "both"


def _load_all(unit_slug: str) -> dict[str, dict]:
    if unit_slug in _cache:
        return _cache[unit_slug]

    result: dict[str, dict] = {}
    data_dir = DATA_DIRS.get(unit_slug)
    if data_dir is not None and data_dir.exists():
        candidates = [
            p for p in data_dir.glob("*csi*item*.xlsx")
            if not p.name.startswith("~$")
        ]
        if candidates:
            path = max(candidates, key=lambda p: p.stat().st_mtime)
            wb = openpyxl.load_workbook(path, data_only=True)
            ws = wb[wb.sheetnames[0]]
            cols = _find_header_columns(ws)
            if cols is not None:
                for r in range(2, ws.max_row + 1):
                    if ws.cell(row=r, column=cols["issue"]).value != "Sold":
                        continue
                    cost = _num(ws.cell(row=r, column=cols["cost"]).value)
                    if not cost:
                        continue
                    date = ws.cell(row=r, column=cols["date"]).value
                    if not hasattr(date, "year"):
                        continue
                    month_key = f"{date.year:04d}-{date.month:02d}"
                    bucket = _bucket_for_warehouse(ws.cell(row=r, column=cols["warehouse"]).value)

                    entry = result.setdefault(month_key, {
                        "monthLabel": f"{MONTH_NAMES[date.month - 1]} {date.year}",
                        "packingRs": 0.0, "productionRs": 0.0,
                    })
                    amount = abs(cost)
                    if bucket == "packing":
                        entry["packingRs"] += amount
                    elif bucket == "production":
                        entry["productionRs"] += amount
                    else:
                        entry["packingRs"] += amount
                        entry["productionRs"] += amount
            wb.close()

    _cache[unit_slug] = result
    return result


def compute_maintenance_repair_cost(department: str, unit_slug: str = "shahi-1") -> dict | None:
    """Returns {"months": [{"month", "monthLabel", "maintenanceRepairCostRs"}]}
    for "Packing" or "Production" in the given unit ("shahi-1" or
    "shahi-3"), or None if no CSI transaction file is registered for
    that unit. "Both"-bucketed rows are included in full in BOTH
    departments' own figures -- see module docstring for why the two
    departments' own totals must never be summed together."""
    if department not in ("Packing", "Production"):
        return None
    data = _load_all(unit_slug)
    if not data:
        return None
    key = "packingRs" if department == "Packing" else "productionRs"
    months = [
        {
            "month": month_key,
            "monthLabel": m["monthLabel"],
            "maintenanceRepairCostRs": round(m[key], 2),
        }
        for month_key, m in sorted(data.items())
    ]
    return {"months": months} if months else None
