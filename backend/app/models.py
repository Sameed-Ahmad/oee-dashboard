"""Pydantic data models shared by the parser, cache, and API layers."""
from pydantic import BaseModel


class DayRecord(BaseModel):
    date: str  # "YYYY-MM-DD"
    sheet: str
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


class ProductSummary(BaseModel):
    slug: str
    displayName: str
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


class ProductInfo(BaseModel):
    slug: str
    displayName: str
