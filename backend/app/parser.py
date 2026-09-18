"""Generic Excel-parsing engine for daily OEE report workbooks.

One parser for every product (Fry-O, Pops, Ishida, Nimco, and future ones):
every column from F onward is in the identical position with the identical
meaning across all four real workbooks -- only the leftmost identifier
columns (A-E) vary cosmetically and aren't used. The only real per-product
differences are the file location and the shift structure (some products
report one sheet per day, others a Day + Night sheet per day, occasionally
with a single sheet or an oddball shift code) -- both handled generically
below rather than configured per product.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

import openpyxl

from .products.registry import ProductConfig, resolve_excel_path

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

SHEET_NAME_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{2})(.*)$")

SHIFT_LABELS = {"D": "Day", "N": "Night", "SINGLE": "Full day"}


def shift_label(code: str) -> str:
    return SHIFT_LABELS.get(code, code.title())  # unknown codes (e.g. "B") -> "B"


@dataclass
class ParseResult:
    records: list[dict]
    errors: list[str]
    skipped_sheets: list[str]


def should_skip_sheet(name: str) -> bool:
    low = name.lower()
    return "summary" in low or "link" in low or "(" in name


def parse_sheet_name(name: str) -> tuple[str | None, str | None]:
    """Returns (date_iso, shift_code), or (None, None) if it doesn't look
    like a date-named sheet at all."""
    m = SHEET_NAME_RE.match(name)
    if not m:
        return None, None
    d, mo, y, rest = m.groups()
    try:
        datetime.date(int(f"20{y}"), int(mo), int(d))  # validates a real calendar date
    except ValueError:
        return None, None
    return f"20{y}-{mo}-{d}", (rest.strip().upper() or "SINGLE")


def find_summary_anchor(ws, max_row: int = 60) -> int | None:
    """Locates the row where the AK/AL summary block starts, by finding the
    'Machines'/'Available' anchor rather than assuming a fixed row -- this
    drifts between products (row 8 for Fry-O/Pops/Ishida, row 7 for Nimco)."""
    for r in range(1, min(ws.max_row, max_row) + 1):
        if ws[f"AJ{r}"].value == "Available" and ws[f"AK{r}"].value == "Machines":
            return r
    return None


def find_row_with_label(ws, label: str, start_row: int = 1, max_row: int = 90) -> int | None:
    target = label.strip().lower()
    for r in range(start_row, min(ws.max_row, max_row) + 1):
        v = ws[f"A{r}"].value
        if isinstance(v, str) and v.strip().lower() == target:
            return r
    return None


def find_total_row(ws, max_row: int = 80) -> int | None:
    return find_row_with_label(ws, "Total", start_row=1, max_row=max_row)


def _num(value, default=0):
    """Treats missing cells and Excel error values (#DIV/0!, #N/A, ...) as 0.
    In practice these show up on legitimate all-zero shifts (e.g. a Night
    shift that didn't run has 0 labor, so the sheet's own Output/Labor
    formula divides by zero) rather than indicating corrupted data."""
    if value is None:
        return default
    if isinstance(value, str) and value.strip().startswith("#"):
        return default
    return value


def parse_shift_sheet(ws, sheet_name: str) -> tuple[dict | None, str | None]:
    """Parses ONE shift-sheet into a raw shift record."""
    anchor = find_summary_anchor(ws)
    if anchor is None:
        return None, f"no summary anchor found in sheet '{sheet_name}'"

    labels = [ws[f"AK{r}"].value for r in range(anchor, anchor + 16)]
    if labels != EXPECTED_LABELS:
        return None, f"unexpected summary label sequence in sheet '{sheet_name}': {labels}"

    vals = [ws[f"AL{r}"].value for r in range(anchor, anchor + 16)]
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
        label: float(_num(ws[f"{col}{total_row}"].value))
        for label, col in DOWNTIME_COLS.items()
    }

    try:
        record = {
            "sheet": sheet_name,
            "availMachines": int(_num(avail_machines)),
            "availTime": int(_num(avail_time)),
            "avgSpeed": float(_num(avg_speed)),
            "idealTargetOutput": float(_num(ideal_target_output)),
            "actMachines": int(_num(act_machines)),
            "actTime": int(_num(act_time)),
            "actualTargetOutput": float(_num(actual_target_output)),
            "availabilityPct": float(_num(availability_pct)),
            "targetCounter": int(_num(target_counter)),
            "actualCounter": int(_num(actual_counter)),
            "performancePct": float(_num(performance_pct)),
            "stockTransferred": int(_num(stock_transferred)),
            "qualityPct": float(_num(quality_pct)),
            "oeePct": float(_num(oee_pct)),
            "totalLabor": int(_num(total_labor)),
            "outputPerLabor": float(_num(output_per_labor)),
            "downtime": downtime,
        }
    except (TypeError, ValueError) as exc:
        return None, f"could not coerce values in sheet '{sheet_name}': {exc}"

    return record, None


def aggregate_day(date_iso: str, shift_records: list[dict]) -> dict:
    """Combines 1+ shift records for the same date into one DayRecord.

    Additive fields are summed. Quality and Output-per-labor are recomputed
    from those sums (exact, not an approximation, since they reuse the same
    ratio definition each shift already uses: Quality = stockTransferred /
    actualCounter, Output/Labor = stockTransferred / totalLabor).

    Availability is NOT actualTargetOutput/idealTargetOutput -- verified
    against real data, the sheet's own Availability % is actually
    SUM(per-machine Availability %) / actMachines (a per-machine column we
    don't otherwise parse). But since availabilityPct * actMachines
    reconstructs that same per-machine sum exactly (verified against real
    data across all four products), the day-level figure is that
    reconstructed sum, re-summed across shifts and divided by the day's
    total actMachines -- exact, not an approximation, with no extra parsing
    needed.

    Performance is an actualCounter-weighted average of each shift's own
    reported Performance % -- the sheet's hidden formula for Performance %
    doesn't reproduce from summed target/actual counters, verified against
    real data. OEE is then derived from the day-level Availability/
    Performance/Quality so the three keep multiplying out to the fourth at
    the day level, same as they do per-shift.
    """
    def s(field):
        return sum(r[field] for r in shift_records)

    sum_ideal = s("idealTargetOutput")
    sum_actual_target = s("actualTargetOutput")
    sum_stock = s("stockTransferred")
    sum_actual_counter = s("actualCounter")
    sum_labor = s("totalLabor")
    sum_act_machines = s("actMachines")
    avail_pct_weight_sum = sum(r["availabilityPct"] * r["actMachines"] for r in shift_records)

    availability_pct = (avail_pct_weight_sum / sum_act_machines) if sum_act_machines else 0.0
    quality_pct = (sum_stock / sum_actual_counter * 100) if sum_actual_counter else 0.0
    output_per_labor = (sum_stock / sum_labor) if sum_labor else 0.0

    perf_weight_sum = sum(r["performancePct"] * r["actualCounter"] for r in shift_records)
    performance_pct = (perf_weight_sum / sum_actual_counter) if sum_actual_counter else 0.0

    oee_pct = availability_pct * performance_pct * quality_pct / 10000

    speed_weight_sum = sum(r["avgSpeed"] * r["actualCounter"] for r in shift_records)
    avg_speed = (
        (speed_weight_sum / sum_actual_counter) if sum_actual_counter
        else (sum(r["avgSpeed"] for r in shift_records) / len(shift_records))
    )

    downtime_totals = {k: s_downtime(shift_records, k) for k in DOWNTIME_COLS}

    return {
        "date": date_iso,
        "sheets": [r["sheet"] for r in shift_records],
        "shiftCount": len(shift_records),
        "shifts": shift_records,
        "availMachines": s("availMachines"),
        "actMachines": sum_act_machines,
        "avgSpeed": round(avg_speed, 2),
        "availTime": s("availTime"),
        "actTime": s("actTime"),
        "idealTargetOutput": round(sum_ideal, 1),
        "actualTargetOutput": round(sum_actual_target, 1),
        "availabilityPct": round(availability_pct, 2),
        "targetCounter": s("targetCounter"),
        "actualCounter": sum_actual_counter,
        "performancePct": round(performance_pct, 2),
        "stockTransferred": sum_stock,
        "qualityPct": round(quality_pct, 2),
        "oeePct": round(oee_pct, 2),
        "totalLabor": sum_labor,
        "outputPerLabor": round(output_per_labor, 1),
        "downtime": {k: round(v, 1) for k, v in downtime_totals.items()},
    }


def s_downtime(shift_records: list[dict], key: str) -> float:
    return sum(r["downtime"][key] for r in shift_records)


def parse_workbook(config: ProductConfig) -> ParseResult:
    path = resolve_excel_path(config)
    if path is None:
        return ParseResult(records=[], errors=[f"no Excel file found for '{config.slug}'"], skipped_sheets=[])

    wb = openpyxl.load_workbook(path, data_only=True)

    by_date: dict[str, list[dict]] = {}
    errors: list[str] = []
    skipped_sheets: list[str] = []

    for name in wb.sheetnames:
        if should_skip_sheet(name):
            skipped_sheets.append(name)
            continue

        date_iso, shift_code = parse_sheet_name(name)
        if date_iso is None:
            errors.append(f"sheet name doesn't match the expected date pattern: '{name}'")
            continue

        record, error = parse_shift_sheet(wb[name], name)
        if error:
            errors.append(error)
            continue

        record["shiftCode"] = shift_code
        record["shiftLabel"] = shift_label(shift_code)
        by_date.setdefault(date_iso, []).append(record)

    day_records = [aggregate_day(d, recs) for d, recs in by_date.items()]
    day_records.sort(key=lambda r: r["date"])

    # Outlier check: flag any date isolated by a large gap from its neighbors.
    # This is exactly how a real typo was caught in the Nimco file (a sheet
    # named "18-03-25N" sitting between "17-03-26D" and "19-03-26D" --
    # almost certainly meant to say 26, not 25). We don't silently drop or
    # "fix" these, just warn loudly so a human can check the source file.
    dates = [datetime.date.fromisoformat(r["date"]) for r in day_records]
    for i in range(1, len(dates)):
        gap = (dates[i] - dates[i - 1]).days
        if gap > 20:
            errors.append(
                f"WARNING: {gap}-day gap between {dates[i - 1]} and {dates[i]} -- "
                f"check for a date typo in one of the source sheet names"
            )

    return ParseResult(records=day_records, errors=errors, skipped_sheets=skipped_sheets)
