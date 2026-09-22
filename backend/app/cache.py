"""Load/save the processed-JSON cache for a product, and compute its summary."""
from __future__ import annotations

import json

from .config import processed_cache_path
from .models import DateRange, DayRecord, ProductSummary
from .products.registry import ProductConfig


def save_cache(slug: str, records: list[dict], warnings: list[str], groups: dict[str, list[dict]] | None = None) -> None:
    path = processed_cache_path(slug)
    payload = {"records": records, "warnings": warnings, "groups": groups or {}}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_cache(slug: str) -> dict | None:
    """Returns {"records": [...], "warnings": [...], "groups": {...}}, or
    None if no cache file exists yet."""
    path = processed_cache_path(slug)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("groups", {})  # tolerate caches written before per-machine groups existed
    return data


def compute_summary(config: ProductConfig, records: list[dict], warnings: list[str]) -> ProductSummary:
    if not records:
        raise ValueError(f"cannot compute summary for '{config.slug}' with no records")

    n = len(records)
    downtime_totals: dict[str, float] = {}
    for r in records:
        for cause, minutes in r["downtime"].items():
            downtime_totals[cause] = downtime_totals.get(cause, 0) + minutes

    best_day = max(records, key=lambda r: r["oeePct"])
    worst_day = min(records, key=lambda r: r["oeePct"])

    return ProductSummary(
        slug=config.slug,
        displayName=config.display_name,
        departmentSlug=config.department_slug,
        dateRange=DateRange(start=records[0]["date"], end=records[-1]["date"]),
        daysCount=n,
        avgAvailabilityPct=round(sum(r["availabilityPct"] for r in records) / n, 2),
        avgPerformancePct=round(sum(r["performancePct"] for r in records) / n, 2),
        avgQualityPct=round(sum(r["qualityPct"] for r in records) / n, 2),
        avgOeePct=round(sum(r["oeePct"] for r in records) / n, 2),
        totalIdealOutput=round(sum(r["idealTargetOutput"] for r in records), 1),
        totalActualOutput=round(sum(r["actualCounter"] for r in records), 1),
        totalStockTransferred=round(sum(r["stockTransferred"] for r in records), 1),
        avgAvailMachines=round(sum(r["availMachines"] for r in records) / n, 2),
        avgActMachines=round(sum(r["actMachines"] for r in records) / n, 2),
        downtimeTotals={k: round(v, 1) for k, v in downtime_totals.items()},
        bestDay=DayRecord(**best_day),
        worstDay=DayRecord(**worst_day),
        dataQualityWarnings=warnings,
    )
