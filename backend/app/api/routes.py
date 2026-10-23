"""All /api/* endpoints. Serves data from the in-memory/JSON cache, never
re-parsing the workbook on a normal request (see POST /refresh for that)."""
from __future__ import annotations

import datetime
import logging

from fastapi import APIRouter, HTTPException

from ..cache import compute_summary, load_cache, save_cache
from ..electricity import compute_electricity_summary, compute_gas_lpg_summary
from ..finished_goods import compute_fg_reconciliation
from ..gas import compute_department_gas_cost_per_thousand_units, compute_gas_summary
from ..labor_cost import compute_department_labor_cost, compute_labor_cost_summary, compute_output_reconciliation
from ..models import (
    CompanyOrgInfo,
    DayRecord,
    DepartmentAvgSummary,
    DepartmentCostSummary,
    DepartmentDetail,
    DepartmentGasCostGroup,
    DepartmentOrgInfo,
    DepartmentOverview,
    DepartmentProductEntry,
    ElectricityMonthEntry,
    ElectricitySourceEntry,
    ElectricitySummary,
    GasLpgMonthEntry,
    GasLpgSummary,
    FgReconciliationDayEntry,
    FgReconciliationMonthEntry,
    GasMonthEntry,
    LaborCostMonthEntry,
    ProductFgReconciliationSummary,
    ProductGasSummary,
    ProductInfo,
    ProductLaborCostSummary,
    ProductMachines,
    ProductOrgInfo,
    ProductReconciliationSummary,
    ProductSummary,
    ReconciliationMonthEntry,
    SlugName,
    SubEnterpriseOrgInfo,
    UnitDetail,
    UnitOrgInfo,
    UnitOverview,
    UnitOverviewDepartmentEntry,
)
from ..parser import parse_workbook
from ..products.registry import (
    COMPANY_NAME,
    DEPARTMENTS,
    PRODUCTS,
    SUB_ENTERPRISES,
    UNITS,
    departments_in_unit,
    get_department,
    get_sub_enterprise,
    get_unit,
    products_in_department,
    units_in_sub_enterprise,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# In-memory cache of parsed records + warnings + machine groups, keyed by
# product slug. ONE dict (not three parallel ones keyed the same way) so a
# rebuild updates a product's entry with a single dict assignment -- Python
# only guarantees a single __setitem__ is atomic under the GIL, not a
# sequence of them, and _load's background-thread callers (see
# rebuild_all_products_in_background) run concurrently with request
# handlers reading this same cache. Three parallel dicts let a reader land
# between two of the three writes and see a product's fresh records paired
# with its stale (or entirely absent) groups -- a real KeyError this
# produced under load, surfacing as an intermittent 500 on whichever
# endpoint happened to read mid-rebuild.
_cache_by_slug: dict[str, dict] = {}


def _apply_fresh_data(slug: str, records: list[dict], warnings: list[str], groups: dict[str, list[dict]]) -> None:
    """Pushes freshly-parsed data into the in-memory cache -- shared by
    _rebuild_one's callers so a product already loaded into memory (e.g.
    by an earlier request) picks up a later rebuild immediately, rather
    than staying locked to whatever was in memory at first load until the
    process restarts."""
    _cache_by_slug[slug] = {"records": records, "warnings": warnings, "groups": groups}


def _rebuild_one(config):
    """Parses `config`'s workbook fresh and, if it produced any records,
    writes the on-disk cache and updates the in-memory cache to match.
    Returns the parser's own result either way -- callers decide how to
    treat a 0-record result (the manual /refresh endpoint surfaces it as
    an HTTP error; the startup background sweep just logs and keeps
    whatever was already cached for that product)."""
    result = parse_workbook(config)
    if result.records:
        groups = result.groups or {}
        save_cache(config.slug, result.records, result.errors, groups)
        _apply_fresh_data(config.slug, result.records, result.errors, groups)
    return result


def rebuild_all_products_in_background() -> None:
    """Re-parses every product's raw workbook fresh, one at a time, each
    becoming visible (on disk AND in memory, via _rebuild_one) the moment
    ITS OWN parse finishes -- not all-or-nothing at the end. Intended to
    run on a background thread kicked off from main.py's lifespan at app
    startup, rather than blocking server startup on it: a full sweep
    across every product takes tens of seconds (the largest single
    workbook alone can take ~18s to parse), far past what's reasonable to
    make every launch wait on, so the server starts answering requests
    immediately with whatever cache already exists and each product
    silently upgrades to the fresh version as its own parse completes.

    A product whose workbook can't be read right now (e.g. open/locked in
    Excel, or a genuine parse failure) keeps serving its existing cache
    rather than crashing this sweep or being left with no data -- it
    picks up the fresh version on a later restart/refresh once that's
    resolved."""
    for config in PRODUCTS.values():
        if config.excel_dir is None:
            continue
        try:
            result = _rebuild_one(config)
        except Exception:
            logger.exception("background startup rebuild failed for '%s' -- keeping existing cache", config.slug)
            continue
        if not result.records:
            logger.warning("background startup rebuild for '%s' produced 0 records -- keeping existing cache", config.slug)
            continue
        logger.info("background startup rebuild done for '%s': %d records", config.slug, len(result.records))


def _load(slug: str) -> tuple[list[dict], list[str], dict[str, list[dict]]]:
    """Loads (records, warnings, groups) for a product, cache-first.
    Products with no excel_dir registered yet return ([], [], {}) without
    attempting to parse."""
    cached = _cache_by_slug.get(slug)
    if cached is not None:
        return cached["records"], cached["warnings"], cached["groups"]

    config = PRODUCTS[slug]
    if config.excel_dir is None:
        records, warnings, groups = [], [], {}
    else:
        disk_cached = load_cache(slug)
        if disk_cached is None:
            logger.warning("no cache found for '%s', building it now", slug)
            result = parse_workbook(config)
            records, warnings, groups = result.records, result.errors, result.groups or {}
            save_cache(slug, records, warnings, groups)
        else:
            records, warnings, groups = disk_cached["records"], disk_cached["warnings"], disk_cached["groups"]

    _apply_fresh_data(slug, records, warnings, groups)
    return records, warnings, groups


def _current_year() -> str:
    """The dashboard shows the current year only, everywhere -- older years
    are considered stale (explicit request). Computed dynamically rather
    than hardcoded, so it keeps advancing on its own instead of needing a
    yearly code change. Applied here, in _get_records/_get_groups, rather
    than by discarding anything: the on-disk cache and _load's raw values
    still hold full history, so relaxing this later needs no reparse."""
    return str(datetime.date.today().year)


def _is_real_day(record: dict) -> bool:
    """A record with exactly 0% OEE isn't a genuine "bad production day" to
    rank/average in -- verified against real data, it means nothing was
    actually run that day/shift (a plant shutdown, holiday, or similarly
    inactive stretch), not a worst-case performance to spotlight as the
    "Toughest day." Excluded here, the single choke point every other
    endpoint (days list, overview, best/worst day, department/unit trends)
    already funnels through, so it disappears everywhere at once rather
    than needing a special case in each. oeePct is None (not 0) for
    machine/line records where Quality %/OEE % just isn't tracked at that
    granularity -- that's "unavailable," not "zero," so it's kept."""
    return record["oeePct"] is None or record["oeePct"] != 0


def _get_records(slug: str) -> list[dict]:
    if slug not in PRODUCTS:
        raise HTTPException(status_code=404, detail=f"unknown product '{slug}'")
    records, _, _ = _load(slug)
    year = _current_year()
    return [r for r in records if r["date"].startswith(year) and _is_real_day(r)]


def _get_groups(slug: str) -> dict[str, list[dict]]:
    if slug not in PRODUCTS:
        raise HTTPException(status_code=404, detail=f"unknown product '{slug}'")
    _, _, groups = _load(slug)
    year = _current_year()
    filtered = {}
    for label, records in groups.items():
        kept = [r for r in records if r["date"].startswith(year) and _is_real_day(r)]
        if kept:  # a group with nothing left this year isn't worth listing
            filtered[label] = kept
    return filtered


def product_has_data(slug: str) -> bool:
    config = PRODUCTS.get(slug)
    if config is None or config.excel_dir is None:
        return False
    return len(_get_records(slug)) > 0


def _product_org_info(slug: str) -> ProductOrgInfo:
    config = PRODUCTS[slug]
    return ProductOrgInfo(slug=config.slug, displayName=config.display_name, hasData=product_has_data(slug))


def _department_org_info(dept_slug: str) -> DepartmentOrgInfo:
    dept = DEPARTMENTS[dept_slug]
    product_infos = [_product_org_info(p.slug) for p in products_in_department(dept_slug)]
    return DepartmentOrgInfo(
        slug=dept.slug,
        displayName=dept.display_name,
        hasData=any(p.hasData for p in product_infos),
        products=product_infos,
    )


@router.get("/products", response_model=list[ProductInfo])
def list_products():
    # Only products with actual data -- the full org chart (including
    # not-yet-populated departments/products) is served by /api/company.
    return [
        ProductInfo(slug=config.slug, displayName=config.display_name)
        for config in PRODUCTS.values()
        if product_has_data(config.slug)
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
    _, warnings, _ = _load(slug)
    return compute_summary(PRODUCTS[slug], records, warnings)


@router.get("/products/{slug}/machines", response_model=ProductMachines)
def get_product_machines(slug: str):
    """Per-machine/line breakdown for a product (e.g. Ishida's named
    machines, Nimco's SKU codes). Empty for products with no identifiable
    grouping column -- see parser.find_group_column."""
    if slug not in PRODUCTS:
        raise HTTPException(status_code=404, detail=f"unknown product '{slug}'")
    groups = _get_groups(slug)
    return ProductMachines(machines=sorted(groups.keys()), records=groups)


@router.get("/products/{slug}/gas", response_model=ProductGasSummary)
def get_product_gas(slug: str):
    """Gas meter consumption vs. production, month by month -- only
    registered for the handful of products with manually-entered gas
    meter readings (see gas.py). 404 means no gas panel for this product,
    not an error."""
    if slug not in PRODUCTS:
        raise HTTPException(status_code=404, detail=f"unknown product '{slug}'")
    records = _get_records(slug)
    result = compute_gas_summary(slug, records)
    if result is None:
        raise HTTPException(status_code=404, detail=f"no gas meter data registered for '{slug}'")
    return ProductGasSummary(
        slug=slug,
        mmbtuPriceRs=result["mmbtuPriceRs"],
        months=[GasMonthEntry(**m) for m in result["months"]],
    )


@router.get("/products/{slug}/labor-cost", response_model=ProductLaborCostSummary)
def get_product_labor_cost(slug: str):
    """Labor cost per unit of output (packets/KG), month by month -- only
    registered for products with an identifiable cost-center line in the
    separate Labor Cost Analysis workbook (see labor_cost.py). 404 means
    no labor-cost panel for this product, not an error."""
    if slug not in PRODUCTS:
        raise HTTPException(status_code=404, detail=f"unknown product '{slug}'")
    result = compute_labor_cost_summary(slug)
    if result is None:
        raise HTTPException(status_code=404, detail=f"no labor-cost data registered for '{slug}'")
    return ProductLaborCostSummary(
        slug=slug,
        sourceLines=result["sourceLines"],
        shared=result["shared"],
        months=[LaborCostMonthEntry(**m) for m in result["months"]],
    )


@router.get("/products/{slug}/reconciliation", response_model=ProductReconciliationSummary)
def get_product_reconciliation(slug: str):
    """Produced (this dashboard's own OEE-tracked output) vs. Received (the
    labor-cost workbook's Output Input figure), month by month -- see
    labor_cost.compute_output_reconciliation for why these two numbers are
    expected to differ. Same product scope as /labor-cost. 404 means no
    reconciliation panel for this product, not an error."""
    if slug not in PRODUCTS:
        raise HTTPException(status_code=404, detail=f"unknown product '{slug}'")
    records = _get_records(slug)
    result = compute_output_reconciliation(slug, records)
    if result is None:
        raise HTTPException(status_code=404, detail=f"no reconciliation data registered for '{slug}'")
    return ProductReconciliationSummary(
        slug=slug,
        sourceLines=result["sourceLines"],
        shared=result["shared"],
        months=[ReconciliationMonthEntry(**m) for m in result["months"]],
    )


@router.get("/products/{slug}/fg-reconciliation", response_model=ProductFgReconciliationSummary)
def get_product_fg_reconciliation(slug: str):
    """Produced (this dashboard's own OEE-tracked stockTransferred) vs.
    Received (finished-goods warehouse receipts -- see
    finished_goods.py), rolled up by month with each month's own days
    nested for drill-down, for the 4 Packing Dept products this data
    source covers (Fry-O, Ishida, Pops, Nimco). 404 means no
    finished-goods data registered for this product, not an error."""
    if slug not in PRODUCTS:
        raise HTTPException(status_code=404, detail=f"unknown product '{slug}'")
    records = _get_records(slug)
    result = compute_fg_reconciliation(slug, records)
    if result is None:
        raise HTTPException(status_code=404, detail=f"no finished-goods data registered for '{slug}'")
    return ProductFgReconciliationSummary(
        slug=slug,
        flagThresholdPct=result["flagThresholdPct"],
        produced=result["produced"],
        received=result["received"],
        gap=result["gap"],
        gapPct=result["gapPct"],
        flagged=result["flagged"],
        months=[
            FgReconciliationMonthEntry(**{**m, "days": [FgReconciliationDayEntry(**d) for d in m["days"]]})
            for m in result["months"]
        ],
    )


@router.post("/products/{slug}/refresh", response_model=ProductSummary)
def refresh_product(slug: str):
    if slug not in PRODUCTS:
        raise HTTPException(status_code=404, detail=f"unknown product '{slug}'")
    config = PRODUCTS[slug]
    if config.excel_dir is None:
        raise HTTPException(status_code=404, detail=f"no data source registered for '{slug}' yet")

    result = _rebuild_one(config)
    if not result.records:
        raise HTTPException(
            status_code=422,
            detail=f"refresh produced 0 records for '{slug}': {result.errors}",
        )

    # Current-year-only, consistent with every other endpoint (_get_records)
    # -- distinct from the check above, which only guards against a genuine
    # parse failure (zero records at all, any year).
    records = _get_records(slug)
    if not records:
        raise HTTPException(status_code=404, detail=f"no current-year records for '{slug}' after refresh")
    return compute_summary(config, records, result.errors)


@router.get("/company", response_model=CompanyOrgInfo)
def get_company():
    sub_enterprises = []
    for sub in SUB_ENTERPRISES.values():
        units = []
        for unit in units_in_sub_enterprise(sub.slug):
            departments = [_department_org_info(d.slug) for d in departments_in_unit(unit.slug)]
            units.append(UnitOrgInfo(slug=unit.slug, displayName=unit.display_name, departments=departments))
        sub_enterprises.append(SubEnterpriseOrgInfo(slug=sub.slug, displayName=sub.display_name, units=units))
    return CompanyOrgInfo(displayName=COMPANY_NAME, subEnterprises=sub_enterprises)


@router.get("/departments/{dept_slug}", response_model=DepartmentDetail)
def get_department_detail(dept_slug: str):
    dept = get_department(dept_slug)
    if dept is None:
        raise HTTPException(status_code=404, detail=f"unknown department '{dept_slug}'")
    unit = get_unit(dept.unit_slug)
    sub_enterprise = get_sub_enterprise(unit.sub_enterprise_slug)
    products = [_product_org_info(p.slug) for p in products_in_department(dept_slug)]
    return DepartmentDetail(
        slug=dept.slug,
        displayName=dept.display_name,
        unit=SlugName(slug=unit.slug, displayName=unit.display_name),
        subEnterprise=SlugName(slug=sub_enterprise.slug, displayName=sub_enterprise.display_name),
        products=products,
    )


@router.get("/departments/{dept_slug}/overview", response_model=DepartmentOverview)
def get_department_overview(dept_slug: str):
    dept_detail = get_department_detail(dept_slug)

    entries = []
    for p in products_in_department(dept_slug):
        if not product_has_data(p.slug):
            continue
        records = _get_records(p.slug)
        _, warnings, _ = _load(p.slug)
        summary = compute_summary(p, records, warnings)
        fg_reconciliation = compute_fg_reconciliation(p.slug, records)
        entries.append(DepartmentProductEntry(
            slug=p.slug,
            displayName=p.display_name,
            summary=summary,
            fgGapFlagged=fg_reconciliation["flagged"] if fg_reconciliation is not None else None,
        ))

    return DepartmentOverview(department=dept_detail, products=entries)


def _avg_department_summary(summaries: list[ProductSummary]) -> DepartmentAvgSummary:
    n = len(summaries)
    return DepartmentAvgSummary(
        avgAvailabilityPct=round(sum(s.avgAvailabilityPct for s in summaries) / n, 2),
        avgPerformancePct=round(sum(s.avgPerformancePct for s in summaries) / n, 2),
        avgQualityPct=round(sum(s.avgQualityPct for s in summaries) / n, 2),
        avgOeePct=round(sum(s.avgOeePct for s in summaries) / n, 2),
    )


def _department_summaries(dept_slug: str) -> list[ProductSummary]:
    """One ProductSummary per product in this department that has data
    (already current-year-only, via _get_records)."""
    summaries = []
    for p in products_in_department(dept_slug):
        if not product_has_data(p.slug):
            continue
        records = _get_records(p.slug)
        if not records:
            continue
        _, warnings, _ = _load(p.slug)
        summaries.append(compute_summary(p, records, warnings))
    return summaries


def _department_cost_summary(dept) -> DepartmentCostSummary:
    """Total Labor Cost, average Gas Cost per 1,000 units (one group per
    output unit, see compute_department_gas_cost_per_thousand_units), and
    Electricity Cost per unit of this department's own output, for the
    Shahi 1 unit cards. The workbook's own department row label is just
    the display name without " Dept" ("Packing Dept" -> "Packing"),
    matching its own spelling exactly.
    """
    workbook_label = dept.display_name.replace(" Dept", "")
    product_slugs = [p.slug for p in products_in_department(dept.slug)]
    labor = compute_department_labor_cost(workbook_label, product_slugs)

    records_by_slug = {slug: _get_records(slug) for slug in product_slugs}
    gas_groups = compute_department_gas_cost_per_thousand_units(product_slugs, records_by_slug)

    electricity_cost_per_unit = _department_electricity_cost_per_unit(dept.slug)

    return DepartmentCostSummary(
        totalLaborCostRs=labor["totalRs"] if labor else None,
        laborOnlyCostRs=labor["laborOnlyRs"] if labor else None,
        contractualLaborCostRs=labor["contractualRs"] if labor else None,
        laborCostFirstMonth=labor["firstMonth"] if labor else None,
        laborCostLastMonth=labor["lastMonth"] if labor else None,
        laborCostPerThousandUnits=labor["costPerThousandUnits"] if labor else None,
        laborCostOutputUnit=labor["outputUnit"] if labor else None,
        gasCostGroups=[DepartmentGasCostGroup(**g) for g in gas_groups],
        electricityCostPerUnitRs=electricity_cost_per_unit,
    )


def _department_electricity_cost_per_unit(dept_slug: str) -> float | None:
    """Rs. per unit of this department's own OEE-tracked output (Packets
    for Packing, KG for Production -- see laborCostOutputUnit on the same
    DepartmentCostSummary for the label), using Shahi-1's facility-wide
    electricity cost (see electricity.py -- NOT split by department, only
    the combined Shahi-1 total is available at the source) summed only
    over months this department also has output for. A partial/
    approximate figure by necessity -- this department's own true share
    of the electricity bill isn't available at the source, only the
    combined Shahi-1 total -- not an isolated per-department cost.

    Returns None if there's no overlap between electricity months and
    this department's own output months."""
    electricity = compute_electricity_summary()
    if electricity is None:
        return None
    output_by_month = _department_monthly_output(dept_slug)

    total_cost = 0.0
    total_output = 0.0
    for m in electricity["months"]:
        output = output_by_month.get(m["month"])
        if not output:
            continue
        total_cost += m["costRs"]
        total_output += output

    if total_output <= 0:
        return None
    return round(total_cost / total_output, 2)


def _department_monthly_output(dept_slug: str) -> dict[str, float]:
    """month ("2026-01") -> summed OEE-tracked stockTransferred across
    every product in this department, current-year only (same scope as
    every other endpoint, via _get_records) -- used to plot the
    Electricity chart's production-trend lines against the same months."""
    totals: dict[str, float] = {}
    for p in products_in_department(dept_slug):
        if not product_has_data(p.slug):
            continue
        for r in _get_records(p.slug):
            month = r["date"][:7]
            totals[month] = totals.get(month, 0.0) + r["stockTransferred"]
    return totals


@router.get("/units/{unit_slug}/overview", response_model=UnitOverview)
def get_unit_overview(unit_slug: str):
    unit = get_unit(unit_slug)
    if unit is None:
        raise HTTPException(status_code=404, detail=f"unknown unit '{unit_slug}'")
    sub_enterprise = get_sub_enterprise(unit.sub_enterprise_slug)

    dept_entries = []
    for dept in departments_in_unit(unit_slug):
        summaries = _department_summaries(dept.slug)
        if not summaries:
            continue  # department has no data yet -- omit rather than show a meaningless zero average

        dept_entries.append(UnitOverviewDepartmentEntry(
            slug=dept.slug,
            displayName=dept.display_name,
            productCount=len(summaries),
            summary=_avg_department_summary(summaries),
            costs=_department_cost_summary(dept),
        ))

    return UnitOverview(
        unit=UnitDetail(
            slug=unit.slug,
            displayName=unit.display_name,
            subEnterprise=SlugName(slug=sub_enterprise.slug, displayName=sub_enterprise.display_name),
        ),
        departments=dept_entries,
    )


@router.get("/units/{unit_slug}/electricity", response_model=ElectricitySummary)
def get_unit_electricity(unit_slug: str):
    """Shahi-1's own monthly electricity units/cost -- see electricity.py
    for why this is unit-wide rather than per-department (the source
    sheet only ever reports one combined facility total, not broken down
    by department or product). Each month also carries Packing/Production
    Dept's own OEE-tracked output that month (see
    _department_monthly_output) -- None for a department with no OEE
    records that month, not 0. 404 means no electricity data available,
    not an error."""
    unit = get_unit(unit_slug)
    if unit is None:
        raise HTTPException(status_code=404, detail=f"unknown unit '{unit_slug}'")
    result = compute_electricity_summary()
    if result is None:
        raise HTTPException(status_code=404, detail="no electricity data registered")

    packing_output: dict[str, float] = {}
    production_output: dict[str, float] = {}
    for dept in departments_in_unit(unit_slug):
        if dept.display_name == "Packing Dept":
            packing_output = _department_monthly_output(dept.slug)
        elif dept.display_name == "Production Dept":
            production_output = _department_monthly_output(dept.slug)

    return ElectricitySummary(months=[
        ElectricityMonthEntry(**{
            **m,
            "sources": [ElectricitySourceEntry(**s) for s in m["sources"]],
            "packingOutputUnits": packing_output.get(m["month"]),
            "productionOutputUnits": production_output.get(m["month"]),
        })
        for m in result["months"]
    ])


@router.get("/units/{unit_slug}/gas-lpg", response_model=GasLpgSummary)
def get_unit_gas_lpg(unit_slug: str):
    """Shahi-1's own monthly direct-production Gas (m3) and LPG (KG)
    consumption/cost -- see electricity.py's module docstring for why
    this reads the "Gas Consumption-26" sheet's "Shahi -1 Production" and
    "Shahi" (LPG) columns specifically, not its "Power Generation" gas
    (already counted in /electricity's Gas Generator figure) or Wood
    Pellets (no Shahi-only split available). 404 means no gas/LPG data
    available, not an error."""
    if get_unit(unit_slug) is None:
        raise HTTPException(status_code=404, detail=f"unknown unit '{unit_slug}'")
    result = compute_gas_lpg_summary()
    if result is None:
        raise HTTPException(status_code=404, detail="no gas/LPG data registered")
    return GasLpgSummary(months=[GasLpgMonthEntry(**m) for m in result["months"]])
