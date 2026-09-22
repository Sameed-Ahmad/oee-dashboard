"""All /api/* endpoints. Serves data from the in-memory/JSON cache, never
re-parsing the workbook on a normal request (see POST /refresh for that)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ..cache import compute_summary, load_cache, save_cache
from ..models import (
    CompanyOrgInfo,
    DayRecord,
    DepartmentAvgSummary,
    DepartmentDetail,
    DepartmentOrgInfo,
    DepartmentOverview,
    DepartmentProductEntry,
    ProductInfo,
    ProductMachines,
    ProductOrgInfo,
    ProductSummary,
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

# In-memory cache of parsed records + warnings + machine groups, keyed by product slug.
_records_by_slug: dict[str, list[dict]] = {}
_warnings_by_slug: dict[str, list[str]] = {}
_groups_by_slug: dict[str, dict[str, list[dict]]] = {}


def _load(slug: str) -> tuple[list[dict], list[str], dict[str, list[dict]]]:
    """Loads (records, warnings, groups) for a product, cache-first.
    Products with no excel_dir registered yet return ([], [], {}) without
    attempting to parse."""
    if slug in _records_by_slug:
        return _records_by_slug[slug], _warnings_by_slug[slug], _groups_by_slug[slug]

    config = PRODUCTS[slug]
    if config.excel_dir is None:
        records, warnings, groups = [], [], {}
    else:
        cached = load_cache(slug)
        if cached is None:
            logger.warning("no cache found for '%s', building it now", slug)
            result = parse_workbook(config)
            records, warnings, groups = result.records, result.errors, result.groups or {}
            save_cache(slug, records, warnings, groups)
        else:
            records, warnings, groups = cached["records"], cached["warnings"], cached["groups"]

    _records_by_slug[slug] = records
    _warnings_by_slug[slug] = warnings
    _groups_by_slug[slug] = groups
    return records, warnings, groups


def _get_records(slug: str) -> list[dict]:
    if slug not in PRODUCTS:
        raise HTTPException(status_code=404, detail=f"unknown product '{slug}'")
    records, _, _ = _load(slug)
    return records


def _get_groups(slug: str) -> dict[str, list[dict]]:
    if slug not in PRODUCTS:
        raise HTTPException(status_code=404, detail=f"unknown product '{slug}'")
    _, _, groups = _load(slug)
    return groups


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


@router.post("/products/{slug}/refresh", response_model=ProductSummary)
def refresh_product(slug: str):
    if slug not in PRODUCTS:
        raise HTTPException(status_code=404, detail=f"unknown product '{slug}'")
    config = PRODUCTS[slug]
    if config.excel_dir is None:
        raise HTTPException(status_code=404, detail=f"no data source registered for '{slug}' yet")

    result = parse_workbook(config)
    if not result.records:
        raise HTTPException(
            status_code=422,
            detail=f"refresh produced 0 records for '{slug}': {result.errors}",
        )

    groups = result.groups or {}
    save_cache(slug, result.records, result.errors, groups)
    _records_by_slug[slug] = result.records
    _warnings_by_slug[slug] = result.errors
    _groups_by_slug[slug] = groups
    return compute_summary(config, result.records, result.errors)


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
        entries.append(DepartmentProductEntry(slug=p.slug, displayName=p.display_name, summary=summary))

    return DepartmentOverview(department=dept_detail, products=entries)


@router.get("/units/{unit_slug}/overview", response_model=UnitOverview)
def get_unit_overview(unit_slug: str):
    unit = get_unit(unit_slug)
    if unit is None:
        raise HTTPException(status_code=404, detail=f"unknown unit '{unit_slug}'")
    sub_enterprise = get_sub_enterprise(unit.sub_enterprise_slug)

    dept_entries = []
    for dept in departments_in_unit(unit_slug):
        summaries = []
        for p in products_in_department(dept.slug):
            if not product_has_data(p.slug):
                continue
            records = _get_records(p.slug)
            _, warnings, _ = _load(p.slug)
            summaries.append(compute_summary(p, records, warnings))

        if not summaries:
            continue  # department has no data yet -- omit rather than show a meaningless zero average

        n = len(summaries)
        avg_summary = DepartmentAvgSummary(
            avgAvailabilityPct=round(sum(s.avgAvailabilityPct for s in summaries) / n, 2),
            avgPerformancePct=round(sum(s.avgPerformancePct for s in summaries) / n, 2),
            avgQualityPct=round(sum(s.avgQualityPct for s in summaries) / n, 2),
            avgOeePct=round(sum(s.avgOeePct for s in summaries) / n, 2),
        )
        dept_entries.append(UnitOverviewDepartmentEntry(
            slug=dept.slug,
            displayName=dept.display_name,
            productCount=n,
            summary=avg_summary,
        ))

    return UnitOverview(
        unit=UnitDetail(
            slug=unit.slug,
            displayName=unit.display_name,
            subEnterprise=SlugName(slug=sub_enterprise.slug, displayName=sub_enterprise.display_name),
        ),
        departments=dept_entries,
    )
