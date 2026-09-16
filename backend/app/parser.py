"""Generic Excel-parsing engine for daily OEE report workbooks.

The workbook layout (one sheet per day, a fixed AK/AL summary block, a "Total"
downtime row) is described in detail in the project spec. This module is
written against a ProductConfig rather than a bare file path so that the
skip-rules and expected label list could, in principle, differ per product
later even though today every registered product shares the same template.
"""
from __future__ import annotations

from dataclasses import dataclass

import openpyxl

from .products.registry import ProductConfig

EXPECTED_LABELS = [
    "Machines", "Time", "Average Speed", "Target Output",
    "Machines", "Time", "Target Output", "Availability %",
    "Target counter", "Actual Counter", "Performance %",
    "Stock Transferred", "Quality %", "OEE %", "Total Labor", "Output/Labor",
]

DOWNTIME_COLS = {
    "Shift Startup": "J", "Shift End": "K", "Wrapper Changeover": "L",
    "Product Changeover": "M", "KE Breakdown": "N", "Nitrogen/Air Issue": "O",
    "Electrical Breakdown": "P", "Mechanical Breakdown": "Q",
    "Labor Short": "R", "Material Delay": "S",
    "Operator Maintenance": "T", "Cleaning": "U",
}


@dataclass
class ParseResult:
    records: list[dict]
    errors: list[str]
    skipped_sheets: list[str]


def should_skip_sheet(name: str, config: ProductConfig) -> bool:
    if any(keyword in name for keyword in config.sheet_skip_keywords):
        return True
    if config.skip_if_paren_in_name and "(" in name:
        return True
    return False


def parse_date_from_sheet_name(name: str) -> str:
    core = name[:8]  # "06-08-26" even from "22-08-26D"
    d, m, y = core.split("-")
    return f"20{y}-{m}-{d}"


def find_total_row(ws, max_search_row: int = 60) -> int | None:
    for r in range(15, max_search_row):
        if ws[f"A{r}"].value == "Total":
            return r
    return None


def _num(value, default=0):
    return value if value is not None else default


def parse_sheet(ws, sheet_name: str) -> tuple[dict | None, str | None]:
    labels = [ws[f"AK{r}"].value for r in range(8, 24)]
    if labels != EXPECTED_LABELS:
        return None, f"unexpected AK8:AK23 layout in sheet '{sheet_name}'"

    vals = [ws[f"AL{r}"].value for r in range(8, 24)]
    (
        avail_machines, avail_time, avg_speed, ideal_target_output,
        act_machines, act_time, actual_target_output,
        availability_pct, target_counter, actual_counter, performance_pct,
        stock_transferred, quality_pct, oee_pct, total_labor, output_per_labor,
    ) = vals

    total_row = find_total_row(ws)
    if total_row is None:
        return None, f"no 'Total' row found in sheet '{sheet_name}'"

    downtime = {
        label: _num(ws[f"{col}{total_row}"].value)
        for label, col in DOWNTIME_COLS.items()
    }

    try:
        record = {
            "date": parse_date_from_sheet_name(sheet_name),
            "sheet": sheet_name,
            "availMachines": int(_num(avail_machines)),
            "availTime": int(_num(avail_time)),
            "avgSpeed": round(float(_num(avg_speed)), 2),
            "idealTargetOutput": round(float(_num(ideal_target_output)), 1),
            "actMachines": int(_num(act_machines)),
            "actTime": int(_num(act_time)),
            "actualTargetOutput": round(float(_num(actual_target_output)), 1),
            "availabilityPct": round(float(_num(availability_pct)), 2),
            "targetCounter": int(_num(target_counter)),
            "actualCounter": int(_num(actual_counter)),
            "performancePct": round(float(_num(performance_pct)), 2),
            "stockTransferred": int(_num(stock_transferred)),
            "qualityPct": round(float(_num(quality_pct)), 2),
            "oeePct": round(float(_num(oee_pct)), 2),
            "totalLabor": int(_num(total_labor)),
            "outputPerLabor": round(float(_num(output_per_labor)), 1),
            "downtime": {
                k: round(float(v), 1) if isinstance(v, (int, float)) else 0
                for k, v in downtime.items()
            },
        }
    except (TypeError, ValueError) as exc:
        return None, f"could not coerce values in sheet '{sheet_name}': {exc}"

    return record, None


def parse_workbook(config: ProductConfig) -> ParseResult:
    path = config.resolved_excel_path
    wb = openpyxl.load_workbook(path, data_only=True)

    records: list[dict] = []
    errors: list[str] = []
    skipped_sheets: list[str] = []

    for name in wb.sheetnames:
        if should_skip_sheet(name, config):
            skipped_sheets.append(name)
            continue
        record, error = parse_sheet(wb[name], name)
        if error:
            errors.append(error)
        else:
            records.append(record)

    seen_dates: dict[str, str] = {}
    deduped: list[dict] = []
    for record in records:
        existing_sheet = seen_dates.get(record["date"])
        if existing_sheet:
            errors.append(
                f"duplicate date {record['date']} in sheets "
                f"'{existing_sheet}' and '{record['sheet']}' -- keeping the first"
            )
            continue
        seen_dates[record["date"]] = record["sheet"]
        deduped.append(record)

    deduped.sort(key=lambda r: r["date"])
    return ParseResult(records=deduped, errors=errors, skipped_sheets=skipped_sheets)
