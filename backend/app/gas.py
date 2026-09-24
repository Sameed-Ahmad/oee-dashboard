"""Gas meter consumption vs. production, for the handful of products with
manually-entered gas meter readings (backend/data/gas_readings.json --
currently HNC 1, HNC 3, Pops). There's no per-day meter reading, only a
start/end reading for each month, so this is inherently a MONTHLY figure,
not a day-level one: gas consumed that month is the delta between the two
readings, and production for that same window is summed from the day
records whose date falls within [startDate, endDate] inclusive.

Not derived from the Excel workbooks at all -- these numbers are read off
a physical gas meter and entered by hand, so they live in their own small
JSON file rather than the parser.
"""
from __future__ import annotations

import json
from pathlib import Path

GAS_READINGS_PATH = Path(__file__).resolve().parent.parent / "data" / "gas_readings.json"

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


def compute_gas_summary(slug: str, records: list[dict]) -> list[dict] | None:
    """Returns None if this product has no gas readings registered at all
    (callers should treat that as "no gas panel for this product," not an
    error) -- an empty list would instead mean readings exist but none
    overlap the current year's records, which is worth showing as "no data
    yet" rather than hiding the panel entirely."""
    readings = load_gas_readings().get(slug)
    if not readings:
        return None

    months = []
    for entry in readings:
        start, end = entry["startDate"], entry["endDate"]
        gas_consumed = round(entry["endReading"] - entry["startReading"], 2)
        units_produced = sum(r["stockTransferred"] for r in records if start <= r["date"] <= end)
        gas_per_thousand_units = round(gas_consumed / units_produced * 1000, 2) if units_produced else 0.0
        months.append({
            "month": start[:7],
            "monthLabel": _month_label(start),
            "startDate": start,
            "endDate": end,
            "gasConsumed": gas_consumed,
            "unitsProduced": units_produced,
            "gasPerThousandUnits": gas_per_thousand_units,
        })
    return months
