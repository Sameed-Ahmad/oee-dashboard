"""All /api/* endpoints. Serves data from the in-memory/JSON cache, never
re-parsing the workbook on a normal request (see POST /refresh for that)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ..cache import compute_summary, load_cache, save_cache
from ..models import DayRecord, ProductInfo, ProductSummary
from ..parser import parse_workbook
from ..products.registry import PRODUCTS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# In-memory cache of parsed records, keyed by product slug.
_records_by_slug: dict[str, list[dict]] = {}


def _get_records(slug: str) -> list[dict]:
    if slug not in PRODUCTS:
        raise HTTPException(status_code=404, detail=f"unknown product '{slug}'")

    if slug in _records_by_slug:
        return _records_by_slug[slug]

    records = load_cache(slug)
    if records is None:
        logger.warning("no cache found for '%s', building it now", slug)
        result = parse_workbook(PRODUCTS[slug])
        records = result.records
        save_cache(slug, records)

    _records_by_slug[slug] = records
    return records


@router.get("/products", response_model=list[ProductInfo])
def list_products():
    return [
        ProductInfo(slug=config.slug, displayName=config.display_name)
        for config in PRODUCTS.values()
    ]


@router.get("/products/{slug}/days", response_model=list[str])
def list_days(slug: str):
    records = _get_records(slug)
    return [r["date"] for r in records]


@router.get("/products/{slug}/days/{date}", response_model=DayRecord)
def get_day(slug: str, date: str):
    records = _get_records(slug)
    for r in records:
        if r["date"] == date:
            return DayRecord(**r)
    raise HTTPException(status_code=404, detail=f"no record for '{slug}' on {date}")


@router.get("/products/{slug}/overview", response_model=ProductSummary)
def get_overview(slug: str):
    records = _get_records(slug)
    if not records:
        raise HTTPException(status_code=404, detail=f"no records for '{slug}'")
    return compute_summary(PRODUCTS[slug], records)


@router.post("/products/{slug}/refresh", response_model=ProductSummary)
def refresh_product(slug: str):
    if slug not in PRODUCTS:
        raise HTTPException(status_code=404, detail=f"unknown product '{slug}'")

    result = parse_workbook(PRODUCTS[slug])
    if not result.records:
        raise HTTPException(
            status_code=422,
            detail=f"refresh produced 0 records for '{slug}': {result.errors}",
        )

    save_cache(slug, result.records)
    _records_by_slug[slug] = result.records
    return compute_summary(PRODUCTS[slug], result.records)
