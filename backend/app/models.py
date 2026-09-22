"""Pydantic data models shared by the parser, cache, and API layers."""
from pydantic import BaseModel


class ShiftRecord(BaseModel):
    sheet: str
    shiftCode: str
    shiftLabel: str
    availMachines: int
    availTime: int
    avgSpeed: float
    idealTargetOutput: float
    actMachines: int
    actTime: int
    actualTargetOutput: float
    availabilityPct: float
    targetCounter: int
    actualCounter: int
    performancePct: float
    stockTransferred: int
    qualityPct: float
    oeePct: float
    totalLabor: int
    outputPerLabor: float
    downtime: dict[str, float]


class DayRecord(BaseModel):
    date: str  # "YYYY-MM-DD"
    sheets: list[str]
    shiftCount: int
    shifts: list[ShiftRecord]
    availMachines: int
    availTime: int
    avgSpeed: float
    idealTargetOutput: float
    actMachines: int
    actTime: int
    actualTargetOutput: float
    availabilityPct: float
    targetCounter: int
    actualCounter: int
    performancePct: float
    stockTransferred: int
    qualityPct: float
    oeePct: float
    totalLabor: int
    outputPerLabor: float
    downtime: dict[str, float]


class DateRange(BaseModel):
    start: str
    end: str


class MachineDayRecord(BaseModel):
    """One day's aggregated figures for a single machine/line within a
    product (e.g. Ishida's named machines, Nimco's SKU codes) -- same shape
    as DayRecord's own metrics, minus the shift-level detail (shiftCount/
    shifts), which isn't a meaningful concept at this granularity.

    qualityPct/oeePct are null for Packing Dept machines/SKUs (Ishida,
    Nimco, ...): "good units transferred to warehouse" (needed for
    Quality %) is only tracked at the whole-shift level in those workbooks,
    never reliably per machine row -- verified against real cells, not
    assumed. Showing a computed 0% would be actively misleading, so it's
    surfaced as genuinely unavailable instead. Production Dept's per-product
    rows (HNC 1's Masoor/Peanut/..., Kuiper's FryO variants, ...) DO track
    real good/total output per row, so theirs are real, non-null values.
    """
    date: str
    availMachines: int
    availTime: int
    avgSpeed: float
    idealTargetOutput: float
    actMachines: int
    actTime: int
    actualTargetOutput: float
    availabilityPct: float
    targetCounter: int
    actualCounter: int
    performancePct: float
    stockTransferred: int
    qualityPct: float | None
    oeePct: float | None
    downtime: dict[str, float]


class ProductMachines(BaseModel):
    machines: list[str]
    records: dict[str, list[MachineDayRecord]]


class ProductSummary(BaseModel):
    slug: str
    displayName: str
    departmentSlug: str
    dateRange: DateRange
    daysCount: int
    avgAvailabilityPct: float
    avgPerformancePct: float
    avgQualityPct: float
    avgOeePct: float
    totalIdealOutput: float
    totalActualOutput: float
    totalStockTransferred: float
    avgAvailMachines: float
    avgActMachines: float
    downtimeTotals: dict[str, float]
    bestDay: DayRecord
    worstDay: DayRecord
    dataQualityWarnings: list[str]


class ProductInfo(BaseModel):
    slug: str
    displayName: str


class SlugName(BaseModel):
    slug: str
    displayName: str


class ProductOrgInfo(BaseModel):
    slug: str
    displayName: str
    hasData: bool


class DepartmentOrgInfo(BaseModel):
    slug: str
    displayName: str
    hasData: bool
    products: list[ProductOrgInfo]


class UnitOrgInfo(BaseModel):
    slug: str
    displayName: str
    departments: list[DepartmentOrgInfo]


class SubEnterpriseOrgInfo(BaseModel):
    slug: str
    displayName: str
    units: list[UnitOrgInfo]


class CompanyOrgInfo(BaseModel):
    displayName: str
    subEnterprises: list[SubEnterpriseOrgInfo]


class DepartmentDetail(BaseModel):
    slug: str
    displayName: str
    unit: SlugName
    subEnterprise: SlugName
    products: list[ProductOrgInfo]


class DepartmentProductEntry(BaseModel):
    slug: str
    displayName: str
    summary: ProductSummary


class DepartmentOverview(BaseModel):
    department: DepartmentDetail
    products: list[DepartmentProductEntry]


class DepartmentAvgSummary(BaseModel):
    avgAvailabilityPct: float
    avgPerformancePct: float
    avgQualityPct: float
    avgOeePct: float


class UnitOverviewDepartmentEntry(BaseModel):
    slug: str
    displayName: str
    productCount: int
    summary: DepartmentAvgSummary


class UnitDetail(BaseModel):
    slug: str
    displayName: str
    subEnterprise: SlugName


class UnitOverview(BaseModel):
    unit: UnitDetail
    departments: list[UnitOverviewDepartmentEntry]
