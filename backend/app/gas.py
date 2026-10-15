"""Gas meter consumption vs. production, for the handful of products with
manually-entered gas meter readings (backend/data/utility/gas_readings.json --
currently HNC 1, HNC 3, Extruder). There's no per-day meter reading, only a
start/end reading for each month, so this is inherently a MONTHLY figure,
not a day-level one: gas consumed that month is the delta between the two
readings (in MMBTU -- the unit the meters themselves are read in), and
production for that same window is summed from the day records whose date
falls within [startDate, endDate] inclusive.

Not derived from the Excel workbooks at all -- these numbers are read off
a physical gas meter and entered by hand, so they live in their own small
JSON file rather than the parser.

MMBTU_PRICE_RS turns gas consumed into a cost figure (Rs. per unit
produced) -- given directly by the person running this dashboard (their
own billed rate), not looked up automatically: published SNGPL/SSGC
tariffs vary widely by consumer category (captive power vs. process, and
by province), so there's no single "the" industrial gas price to assume.
Update this constant if the billed rate changes; the UI surfaces its
current value directly from here so it's never a hidden assumption.

This meter was originally filed under "pops" -- corrected per the person
running this dashboard: the physical meter sits on the Extruder machine
(Pops' upstream production line), not the Pops packing line itself, so
its readings must be compared against Extruder's own output, not Pops'.
"""
from __future__ import annotations

import json
from pathlib import Path

GAS_READINGS_PATH = Path(__file__).resolve().parent.parent / "data" / "utility" / "gas_readings.json"

MMBTU_PRICE_RS = 5000

# Matches the Packing="Packets"/Production="KG" convention used in
# labor_cost.py -- Extruder, despite packing Pops-brand snack items (see
# module docstring), is tracked in KG like the rest of Production Dept:
# confirmed against its own labor-cost workbook line ("Production -
# Pops", see labor_cost.py's PRODUCT_SOURCE_LINES), whose KG figures
# track Extruder's OEE-tracked output almost exactly.
PRODUCT_OUTPUT_UNIT = {
    "hnc-1": "KG",
    "hnc-3": "KG",
    "extruder": "KG",
}

_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

_cache: dict[str, list[dict]] | None = None


def _month_label(date_iso: str) -> str:
    year, month, _ = date_iso.split("-")
    return f"{_MONTH_NAMES[int(month) - 1]} {year}"


def load_gas_readings() -> dict[str, list[dict]]:
    global _cache
    if _cache is None:
        if not GAS_READINGS_PATH.exists():
            _cache = {}
        else:
            _cache = json.loads(GAS_READINGS_PATH.read_text(encoding="utf-8"))
    return _cache


def compute_gas_summary(slug: str, records: list[dict]) -> dict | None:
    """Returns None if this product has no gas readings registered at all
    (callers should treat that as "no gas panel for this product," not an
    error) -- a real result with an empty months list would instead mean
    readings exist but none overlap the current year's records, which is
    worth showing as "no data yet" rather than hiding the panel entirely."""
    readings = load_gas_readings().get(slug)
    if not readings:
        return None

    output_unit = PRODUCT_OUTPUT_UNIT.get(slug, "units")

    months = []
    for entry in readings:
        start, end = entry["startDate"], entry["endDate"]
        gas_consumed = round(entry["endReading"] - entry["startReading"], 2)
        units_produced = sum(r["stockTransferred"] for r in records if start <= r["date"] <= end)
        gas_per_thousand_units = round(gas_consumed / units_produced * 1000, 2) if units_produced else 0.0
        gas_cost_per_unit = round(gas_consumed * MMBTU_PRICE_RS / units_produced, 4) if units_produced else 0.0
        months.append({
            "month": start[:7],
            "monthLabel": _month_label(start),
            "startDate": start,
            "endDate": end,
            "gasConsumed": gas_consumed,
            "unitsProduced": units_produced,
            "outputUnit": output_unit,
            "gasPerThousandUnits": gas_per_thousand_units,
            "gasCostPerUnit": gas_cost_per_unit,
        })
    return {"mmbtuPriceRs": MMBTU_PRICE_RS, "months": months}


def compute_department_gas_cost_per_thousand_units(
    slugs: list[str], records_by_slug: dict[str, list[dict]]
) -> list[dict]:
    """Average Gas Cost per 1,000 units produced, across whichever products
    in `slugs` have gas meter data registered -- same avg-of-averages
    methodology routes._avg_department_summary uses for the department's
    OEE/Availability/etc. averages: each product's own average
    gasCostPerUnit (across its own months) is scaled to a per-1,000
    figure, then those per-product figures are averaged again, unweighted,
    within their own output unit.

    Returns ONE entry per distinct output unit among the contributing
    products, not a single blended figure -- Shahi 1's Production Dept
    mixes KG-metered (HNC 1/3) and Packets-metered (Extruder) products, and
    averaging "Rs. per 1,000 KG" together with "Rs. per 1,000 Packets"
    would be meaningless (different physical quantities), so each unit
    gets its own line instead. Only a handful of products have gas
    readings at all (see gas_readings.json) -- this reflects only
    whichever of them happen to be in `slugs`, not every cost driver in
    the department.

    Returns an empty list if none of `slugs` have any gas data
    registered."""
    per_unit_avgs: dict[str, list[float]] = {}
    per_unit_products: dict[str, list[str]] = {}
    for slug in slugs:
        result = compute_gas_summary(slug, records_by_slug.get(slug, []))
        if result is None or not result["months"]:
            continue
        unit = result["months"][0]["outputUnit"]
        avg_cost_per_unit = sum(m["gasCostPerUnit"] for m in result["months"]) / len(result["months"])
        per_unit_avgs.setdefault(unit, []).append(avg_cost_per_unit * 1000)
        per_unit_products.setdefault(unit, []).append(slug)

    return [
        {
            "outputUnit": unit,
            "costPerThousandUnits": round(sum(values) / len(values), 2),
            "products": per_unit_products[unit],
        }
        for unit, values in sorted(per_unit_avgs.items())
    ]
