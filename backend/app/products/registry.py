"""Registry of the full company org chart: sub-enterprises, units, departments,
and products. Most products have no Excel data source yet (excel_dir=None) --
they're registered so the org chart is real and complete, but are excluded
from anything data-driven (see registry.resolve_excel_path / product_has_data
in api/routes.py).

To onboard a new product that already has a workbook:
  1. Drop its workbook into backend/data/raw/<slug>/ (any filename; the newest
     .xlsx by modified time in that folder is used automatically -- see
     resolve_excel_path).
  2. Add a ProductConfig entry below with that excel_dir.
  3. Run `python backend/scripts/build_cache.py --product <slug>` (or --all).
No changes to the parser, API, or cache layers are required -- see parser.py,
which is fully generic across products (section 1 of the spec).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import PROJECT_ROOT

COMPANY_NAME = "Shahi Enterprises"


@dataclass
class SubEnterpriseConfig:
    slug: str
    display_name: str


@dataclass
class UnitConfig:
    slug: str
    display_name: str
    sub_enterprise_slug: str


@dataclass
class DepartmentConfig:
    slug: str
    display_name: str
    unit_slug: str


@dataclass
class ProductConfig:
    slug: str
    display_name: str
    department_slug: str
    excel_dir: Path | None = None  # None = no data source registered yet


SUB_ENTERPRISES: dict[str, SubEnterpriseConfig] = {
    "shahi": SubEnterpriseConfig("shahi", "Shahi Enterprises"),
    "zain": SubEnterpriseConfig("zain", "Zain Enterprises"),
}

UNITS: dict[str, UnitConfig] = {
    "shahi-1": UnitConfig("shahi-1", "Shahi 1", "shahi"),
    "shahi-3": UnitConfig("shahi-3", "Shahi 3", "shahi"),
    "zain-1": UnitConfig("zain-1", "Zain 1", "zain"),
    "zain-2": UnitConfig("zain-2", "Zain 2", "zain"),
}

DEPARTMENTS: dict[str, DepartmentConfig] = {
    "shahi-1-packing": DepartmentConfig("shahi-1-packing", "Packing Dept", "shahi-1"),
    "shahi-1-production": DepartmentConfig("shahi-1-production", "Production Dept", "shahi-1"),
    "shahi-3-packing": DepartmentConfig("shahi-3-packing", "Packing Dept", "shahi-3"),
    "shahi-3-production": DepartmentConfig("shahi-3-production", "Production Dept", "shahi-3"),
    "zain-1-packing": DepartmentConfig("zain-1-packing", "Packing Dept", "zain-1"),
    "zain-1-production": DepartmentConfig("zain-1-production", "Production Dept", "zain-1"),
    "zain-2-production": DepartmentConfig("zain-2-production", "Production Dept", "zain-2"),
}

PRODUCTS: dict[str, ProductConfig] = {
    # --- shahi-1-packing: the only department with real data today ---
    "fryo": ProductConfig("fryo", "Fry-O", "shahi-1-packing", Path("backend/data/raw/fryo")),
    "pops": ProductConfig("pops", "Pops", "shahi-1-packing", Path("backend/data/raw/pops")),
    "ishida": ProductConfig("ishida", "Ishida", "shahi-1-packing", Path("backend/data/raw/ishida")),
    "nimco": ProductConfig("nimco", "Nimco", "shahi-1-packing", Path("backend/data/raw/nimco")),

    # --- shahi-1-production: real data ---
    "coated-peanut": ProductConfig("coated-peanut", "Coated Peanut", "shahi-1-production", Path("backend/data/raw/coated-peanut")),
    "namak-para": ProductConfig("namak-para", "Namak Para", "shahi-1-production", Path("backend/data/raw/namak-para")),
    "hnc-1": ProductConfig("hnc-1", "HNC 1", "shahi-1-production", Path("backend/data/raw/hnc-1")),
    "hnc-3": ProductConfig("hnc-3", "HNC 3", "shahi-1-production", Path("backend/data/raw/hnc-3")),
    "extruder": ProductConfig("extruder", "Extruder", "shahi-1-production", Path("backend/data/raw/extruder")),
    "kuiper": ProductConfig("kuiper", "Kuiper", "shahi-1-production", Path("backend/data/raw/kuiper")),

    # --- shahi-3-packing: known products, no data source yet ---
    "lhr-snacks": ProductConfig("lhr-snacks", "LHR Snacks", "shahi-3-packing"),
    "lhr-siminato": ProductConfig("lhr-siminato", "LHR Siminato", "shahi-3-packing"),
    "lhr-nimco-1": ProductConfig("lhr-nimco-1", "LHR Nimco-1", "shahi-3-packing"),
    "lhr-nimco-2": ProductConfig("lhr-nimco-2", "LHR Nimco-2", "shahi-3-packing"),

    # --- shahi-3-production: known products, no data source yet ---
    "shahi3-hnc-2-lhr": ProductConfig("shahi3-hnc-2-lhr", "HNC-2 LHR", "shahi-3-production"),
    "shahi3-extruder": ProductConfig("shahi3-extruder", "Extruder", "shahi-3-production"),
    "shahi3-hnc-1": ProductConfig("shahi3-hnc-1", "HNC 1", "shahi-3-production"),
    "shahi3-hnc-3": ProductConfig("shahi3-hnc-3", "HNC 3", "shahi-3-production"),
    "shahi3-kuiper": ProductConfig("shahi3-kuiper", "Kuiper", "shahi-3-production"),
    "shahi3-nomak-para": ProductConfig("shahi3-nomak-para", "Nomak Para", "shahi-3-production"),

    # --- zain-1-packing: known products, no data source yet ---
    "aas-pass": ProductConfig("aas-pass", "Aas Pass", "zain-1-packing"),
    "deewan": ProductConfig("deewan", "Deewan", "zain-1-packing"),
    "delux-mewa": ProductConfig("delux-mewa", "Delux & Mewa", "zain-1-packing"),
    "elachi": ProductConfig("elachi", "Elachi", "zain-1-packing"),

    # --- zain-1-production: known products, no data source yet ---
    "zain1-energy-bar": ProductConfig("zain1-energy-bar", "Energy Bar", "zain-1-production"),
    "zain1-roasting-1": ProductConfig("zain1-roasting-1", "Roasting 1", "zain-1-production"),
    "zain1-roasting-2": ProductConfig("zain1-roasting-2", "Roasting 2", "zain-1-production"),
    "zain1-roasting-3": ProductConfig("zain1-roasting-3", "Roasting 3", "zain-1-production"),

    # --- zain-2-production: known products, no data source yet ---
    "zain2-a-pass-mix": ProductConfig("zain2-a-pass-mix", "A-Pass Mix", "zain-2-production"),
    "zain2-coated-sort": ProductConfig("zain2-coated-sort", "Coated Sort", "zain-2-production"),
    "zain2-coco-ball": ProductConfig("zain2-coco-ball", "Coco Ball", "zain-2-production"),
    "zain2-vanilla-ball": ProductConfig("zain2-vanilla-ball", "Vanilla Ball", "zain-2-production"),
}


def get_product(slug: str) -> ProductConfig | None:
    return PRODUCTS.get(slug)


def get_department(slug: str) -> DepartmentConfig | None:
    return DEPARTMENTS.get(slug)


def get_unit(slug: str) -> UnitConfig | None:
    return UNITS.get(slug)


def get_sub_enterprise(slug: str) -> SubEnterpriseConfig | None:
    return SUB_ENTERPRISES.get(slug)


def products_in_department(dept_slug: str) -> list[ProductConfig]:
    return [p for p in PRODUCTS.values() if p.department_slug == dept_slug]


def departments_in_unit(unit_slug: str) -> list[DepartmentConfig]:
    return [d for d in DEPARTMENTS.values() if d.unit_slug == unit_slug]


def units_in_sub_enterprise(sub_slug: str) -> list[UnitConfig]:
    return [u for u in UNITS.values() if u.sub_enterprise_slug == sub_slug]


def resolve_excel_path(config: ProductConfig) -> Path | None:
    """Picks the newest (by modified time) .xlsx file in the product's
    excel_dir. The plant re-exports these workbooks periodically with the
    export date baked into the filename, so we never hardcode a filename --
    dropping a fresh export into the folder just works. Modified time (not
    filename) is used as the tiebreaker since real filenames in the wild
    vary in spacing/case (e.g. "Nimco OEE  15-09-26.xlsx" with a double
    space), which makes lexicographic-last unreliable.
    """
    if config.excel_dir is None:
        return None
    excel_dir = config.excel_dir
    if not excel_dir.is_absolute():
        excel_dir = PROJECT_ROOT / excel_dir
    if not excel_dir.is_dir():
        return None
    candidates = [
        f for f in excel_dir.glob("*.xlsx")
        if not f.name.startswith("~$")  # exclude Excel's own lock files
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda f: f.stat().st_mtime)
