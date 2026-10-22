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
    maxAvailMachines: int  # peak machines/lines available across the range -- a fixed capacity figure, not an average
    downtimeTotals: dict[str, float]
    bestDay: DayRecord
    worstDay: DayRecord
    dataQualityWarnings: list[str]


class GasMonthEntry(BaseModel):
    month: str  # "2026-06"
    monthLabel: str  # "June 2026"
    startDate: str
    endDate: str
    gasConsumed: float  # MMBTU
    unitsProduced: int
    outputUnit: str  # "Packets" | "KG"
    gasPerThousandUnits: float
    gasCostPerUnit: float  # Rs. per unit produced, at ProductGasSummary.mmbtuPriceRs


class ProductGasSummary(BaseModel):
    slug: str
    mmbtuPriceRs: float
    months: list[GasMonthEntry]


class LaborCostMonthEntry(BaseModel):
    month: str  # "2026-01"
    monthLabel: str  # "January 2026"
    manHours: float
    laborCost: float
    output: float
    outputUnit: str  # "Packets" | "KG"
    costPerThousandUnits: float  # Rs. per 1,000 units of output (more readable than the raw per-unit fraction)
    manHoursPerThousandUnits: float


class ProductLaborCostSummary(BaseModel):
    slug: str
    sourceLines: list[str]
    shared: bool
    months: list[LaborCostMonthEntry]


class ReconciliationMonthEntry(BaseModel):
    month: str  # "2026-01"
    monthLabel: str  # "January 2026"
    outputUnit: str  # "Packets" | "KG"
    produced: float  # OEE-tracked, summed from this dashboard's own day records
    received: float  # from the labor-cost workbook's Output Input sheet
    gap: float  # produced - received
    gapPct: float  # gap as a % of produced


class ProductReconciliationSummary(BaseModel):
    slug: str
    sourceLines: list[str]
    shared: bool
    months: list[ReconciliationMonthEntry]


class FgReconciliationDayEntry(BaseModel):
    date: str  # "2026-07-31"
    produced: float  # OEE-tracked stockTransferred for this day
    received: float  # finished-goods warehouse receipts for this day (see finished_goods.py)
    gap: float  # produced - received
    gapPct: float  # gap as a % of produced
    flagged: bool  # produced exceeded received by more than flagThresholdPct


class FgReconciliationMonthEntry(BaseModel):
    month: str  # "2026-07"
    monthLabel: str  # "July 2026"
    produced: float
    received: float
    gap: float
    gapPct: float
    flagged: bool  # this month's own total: produced exceeded received by more than flagThresholdPct
    days: list[FgReconciliationDayEntry]


class ProductFgReconciliationSummary(BaseModel):
    slug: str
    flagThresholdPct: float
    produced: float  # overall total across every month shown
    received: float
    gap: float
    gapPct: float
    flagged: bool  # same shortfall-only rule as a day, applied to the overall total
    months: list[FgReconciliationMonthEntry]


class ElectricitySourceEntry(BaseModel):
    name: str  # "Gas Generator" | "Diesel Generator" | "K-Electric" | "Solar"
    units: float | None  # None for a month this source has no reading at all
    billRs: float | None  # None for Solar (free/self-generated, no bill)
    unitCost: float | None


class ElectricityMonthEntry(BaseModel):
    month: str  # "2026-01"
    monthLabel: str  # "January 2026"
    unitsConsumed: float  # Shahi-1's own share (see electricity.py)
    costRs: float  # derived: unitsConsumed x that month's blended unit cost
    sharePct: float | None  # Shahi-1's % of the combined Zain-1/Shahi-1 facility total that month
    facilityTotalUnits: float | None  # combined Zain-1 + Shahi-1 total, for context
    facilityTotalCostRs: float | None
    facilityAvgUnitCost: float  # blended Rs./unit across all 4 sources (including solar)
    sources: list[ElectricitySourceEntry]  # facility-wide (Zain-1 + Shahi-1 combined) per-source breakdown
    packingOutputUnits: float | None  # Packing Dept's own OEE-tracked output that month (Packets); None if no records that month
    productionOutputUnits: float | None  # Production Dept's own OEE-tracked output that month (KG); None if no records that month


class ElectricitySummary(BaseModel):
    months: list[ElectricityMonthEntry]


class GasLpgMonthEntry(BaseModel):
    month: str  # "2026-01"
    monthLabel: str  # "January 2026"
    gasM3: float | None  # Shahi-1's own direct-production gas use (NOT the Gas Generator -- see electricity.py)
    gasCostRs: float | None
    gasRatePerM3: float | None
    lpgKg: float | None
    lpgCostRs: float | None
    lpgRatePerKg: float | None
    totalCostRs: float  # gasCostRs + lpgCostRs (0 for whichever is missing that month)


class GasLpgSummary(BaseModel):
    months: list[GasLpgMonthEntry]


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
    fgGapFlagged: bool | None = None  # overall Produced-vs-Received gap over threshold; None if not tracked for this product


class DepartmentOverview(BaseModel):
    department: DepartmentDetail
    products: list[DepartmentProductEntry]


class DepartmentAvgSummary(BaseModel):
    avgAvailabilityPct: float
    avgPerformancePct: float
    avgQualityPct: float
    avgOeePct: float


class DepartmentGasCostGroup(BaseModel):
    outputUnit: str  # "Packets" | "KG"
    costPerThousandUnits: float  # avg across this unit's contributing products
    products: list[str]  # which products contributed to this group's average


class DepartmentCostSummary(BaseModel):
    totalLaborCostRs: float | None  # None if no labor-cost data found for this department
    laborCostFirstMonth: str | None  # "2026-01"
    laborCostLastMonth: str | None  # "2026-08"
    laborCostPerThousandUnits: float | None  # output-weighted, from the workbook's own department totals
    laborCostOutputUnit: str | None  # "Packets" | "KG"
    gasCostGroups: list[DepartmentGasCostGroup]  # one per distinct output unit among gas-tracked products; empty if none
    electricityCostPerUnitRs: float | None  # Rs. per unit of laborCostOutputUnit; see _department_electricity_cost_per_unit for why this is a partial/approximate figure


class UnitOverviewDepartmentEntry(BaseModel):
    slug: str
    displayName: str
    productCount: int
    summary: DepartmentAvgSummary
    costs: DepartmentCostSummary


class UnitDetail(BaseModel):
    slug: str
    displayName: str
    subEnterprise: SlugName


class UnitOverview(BaseModel):
    unit: UnitDetail
    departments: list[UnitOverviewDepartmentEntry]
