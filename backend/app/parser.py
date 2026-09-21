"""Generic Excel-parsing engine for daily OEE report workbooks.

One parser for every product, across both departments now wired up (Packing:
Fry-O/Pops/Ishida/Nimco; Production: Coated Peanut/Namak Para/HNC 1/HNC 3/
Extruder/Kuiper). Production Dept's workbooks do NOT share Packing Dept's
exact column layout (summary block at AI/AJ/AK instead of AJ/AK/AL, no
reliable label text, completely different and per-product-varying downtime
category sets, occasional one-off row-shifted sheets, inconsistent date
formatting) -- so nothing here is keyed by a hardcoded column letter, label
string, or downtime category name. Everything is located by content, per
sheet, at parse time.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

import openpyxl

from .products.registry import ProductConfig, resolve_excel_path

# 1-2 digit day/month, 4-or-2-digit year. Try the 4-digit alternative FIRST --
# regex alternation is tried left-to-right, so reversing this order would
# silently mis-parse any 4-digit-year sheet name (e.g. "10-02-2026" would
# match the 2-digit branch as day=10, month=02, year=20, leaving "26" to leak
# into the shift-code group).
SHEET_NAME_RE = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4}|\d{2})(.*)$")

SHIFT_LABELS = {"D": "Day", "N": "Night", "SINGLE": "Full day"}

PAREN_SUFFIX_RE = re.compile(r"^(.*?)\s*\((\d+)\)$")


def shift_label(code: str) -> str:
    return SHIFT_LABELS.get(code, code.title())  # unknown codes (e.g. "B") -> "B"


def split_shift_code_suffix(shift_code: str) -> tuple[str, str | None]:
    """Splits a trailing '(NN)' numeric suffix off a shift code, e.g.
    "D (56)" -> ("D", "56"), "(62)" -> ("SINGLE", "62"), "D" -> ("D", None).

    Some workbooks reuse a "(N)" suffix for two structurally different
    things: Fry-O/Nimco use it for leftover duplicate/edit-history copies of
    an already-reported shift (a "clean", unsuffixed sheet for that same
    date+shift always exists alongside them), while Coated Peanut uses it to
    distinguish genuinely separate parallel production lines reported for
    the same date (no clean/unsuffixed sheet ever exists for those dates at
    all). Both cases produce the same suffix pattern, so which one applies
    can only be decided later, per date, by checking whether a clean sibling
    exists -- see parse_workbook.
    """
    m = PAREN_SUFFIX_RE.match(shift_code)
    if not m:
        return shift_code, None
    base = m.group(1).strip().upper() or "SINGLE"
    return base, m.group(2)


@dataclass
class ParseResult:
    records: list[dict]
    errors: list[str]
    skipped_sheets: list[str]


def should_skip_sheet(name: str) -> bool:
    low = name.lower()
    return "summary" in low or "link" in low or "blank" in low or low.startswith("sheet")


def parse_sheet_name(name: str) -> tuple[str | None, str | None]:
    """Returns (date_iso, shift_code), or (None, None) if it doesn't look
    like a date-named sheet at all."""
    m = SHEET_NAME_RE.match(name)
    if not m:
        return None, None
    d, mo, y, rest = m.groups()
    year = int(y) if len(y) == 4 else 2000 + int(y)
    try:
        datetime.date(year, int(mo), int(d))  # validates a real calendar date
    except ValueError:
        return None, None
    return f"{year:04d}-{int(mo):02d}-{int(d):02d}", (rest.strip().upper() or "SINGLE")


def find_summary_anchor(ws, max_row: int = 60, max_col: int = 45) -> tuple[int | None, int | None]:
    """Finds the (row, label_column) of the 16-row summary block by searching
    for the 'Available'/'Machines'/<number> triplet in ANY column -- Packing
    Dept has it at AJ/AK/AL, Production Dept at AI/AJ/AK, and it could in
    principle land anywhere. Returns the column holding 'Machines' (the
    label); values are one column further right."""
    for r in range(1, min(ws.max_row, max_row) + 1):
        for c in range(1, min(ws.max_column, max_col) + 1):
            if ws.cell(row=r, column=c).value == "Available":
                label = ws.cell(row=r, column=c + 1).value
                value = ws.cell(row=r, column=c + 2).value
                if label == "Machines" and isinstance(value, (int, float)):
                    return r, c + 1
    return None, None


def find_row_with_label(ws, label: str, start_row: int = 1, max_row: int = 90) -> int | None:
    target = label.strip().lower()
    for r in range(start_row, min(ws.max_row, max_row) + 1):
        v = ws[f"A{r}"].value
        if isinstance(v, str) and v.strip().lower() == target:
            return r
    return None


def find_total_row(ws, max_row: int = 80) -> int | None:
    return find_row_with_label(ws, "Total", start_row=1, max_row=max_row)


def find_downtime_range(ws, max_header_row: int = 15) -> tuple[int | None, list[int] | None]:
    """Finds the header row and downtime column range by locating the
    'total time' marker (end of the time-tracking columns) and 'total down
    time' marker (start of the totals columns) in whichever row actually has
    them -- Packing Dept has this at row 6, but at least one real sheet
    (HNC 3's "14-01-26") has everything shifted up by one row, and the
    downtime categories themselves differ per product, so nothing here is
    positionally hardcoded."""
    for hr in range(1, min(ws.max_row, max_header_row) + 1):
        start_col = end_col = None
        for c in range(1, ws.max_column + 1):
            v = ws.cell(row=hr, column=c).value
            if isinstance(v, str):
                lv = v.lower()
                if start_col is None and "total time" in lv:
                    start_col = c
                if start_col is not None and "total down time" in lv:
                    end_col = c
                    break
        if start_col and end_col and end_col > start_col + 1:
            return hr, list(range(start_col + 1, end_col))
    return None, None


def _num(value, default=0):
    """Treats missing cells and Excel error values (#DIV/0!, #N/A, ...) as 0.
    In practice these show up on legitimate all-zero shifts (e.g. a Night
    shift that didn't run has 0 labor, so the sheet's own Output/Labor
    formula divides by zero) rather than indicating corrupted data."""
    if isinstance(value, (int, float)):
        return value
    return default


def parse_shift_sheet(ws, sheet_name: str) -> tuple[dict | None, str | None]:
    """Parses ONE shift-sheet into a raw shift record. Positional, not label-
    text-based, since Production Dept's summary-block labels are sometimes
    just blank even though the values are still correctly positioned."""
    anchor_row, label_col = find_summary_anchor(ws)
    if anchor_row is None:
        return None, f"no summary anchor found in sheet '{sheet_name}'"

    vals = [ws.cell(row=anchor_row + i, column=label_col + 1).value for i in range(16)]
    (
        avail_machines, avail_time, avg_speed, ideal_target_output,
        act_machines, act_time, actual_target_output,
        availability_pct, target_counter, actual_counter, performance_pct,
        stock_transferred, quality_pct, oee_pct, total_labor, output_per_labor,
    ) = vals

    total_row = find_total_row(ws)
    if total_row is None:
        return None, f"no 'Total' row found in sheet '{sheet_name}'"

    header_row, dt_cols = find_downtime_range(ws)
    if dt_cols is None:
        return None, f"no downtime column range found in sheet '{sheet_name}'"

    downtime = {}
    for c in dt_cols:
        label = ws.cell(row=header_row, column=c).value or f"Category {c}"
        downtime[label] = float(_num(ws.cell(row=total_row, column=c).value))

    try:
        record = {
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


def is_blank_record(rec: dict) -> bool:
    """A sub-record that contributed nothing real that date -- either a
    leftover empty template copy or an inactive parallel production line
    (Coated Peanut reports multiple lines as separate same-date sheets, not
    all of which ran every day). Either way, exclude it from that date's
    aggregation rather than counting it as a zero-output shift."""
    return (rec["availTime"] == 0 and rec["actTime"] == 0 and
            rec["idealTargetOutput"] == 0 and rec["actualCounter"] == 0)


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
    data across all four Packing Dept products), the day-level figure is
    that reconstructed sum, re-summed across shifts and divided by the day's
    total actMachines -- exact, not an approximation, with no extra parsing
    needed.

    Performance is an actualCounter-weighted average of each shift's own
    reported Performance % -- the sheet's hidden formula for Performance %
    doesn't reproduce from summed target/actual counters, verified against
    real data. OEE is then derived from the day-level Availability/
    Performance/Quality so the three keep multiplying out to the fourth at
    the day level, same as they do per-shift.

    Downtime category names are read per-sheet rather than hardcoded (two
    products can legitimately use different category names), so the day's
    downtime totals are keyed by the union of whatever categories actually
    appear across this date's shift records.
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

    downtime_keys = set()
    for r in shift_records:
        downtime_keys.update(r["downtime"].keys())
    downtime_totals = {
        k: sum(r["downtime"].get(k, 0) for r in shift_records)
        for k in downtime_keys
    }

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


def parse_workbook(config: ProductConfig) -> ParseResult:
    path = resolve_excel_path(config)
    if path is None:
        return ParseResult(records=[], errors=[f"no Excel file found for '{config.slug}'"], skipped_sheets=[])

    wb = openpyxl.load_workbook(path, data_only=True)

    by_date: dict[str, list[dict]] = {}
    errors: list[str] = []
    skipped_sheets: list[str] = []

    # Pass 1: classify every date-named sheet as "clean" (no numeric "(NN)"
    # suffix) or "suffixed", so a suffixed sheet can be told apart from a
    # true duplicate (Fry-O/Nimco: a clean sibling for that same date+shift
    # already exists) vs a genuinely distinct parallel line (Coated Peanut:
    # no clean sibling ever exists for those dates at all).
    sheet_info: dict[str, tuple[str, str, str, str | None]] = {}  # name -> (date, shift_code, base_code, suffix)
    clean_bases: dict[str, set[str]] = {}
    for name in wb.sheetnames:
        if should_skip_sheet(name):
            skipped_sheets.append(name)
            continue
        date_iso, shift_code = parse_sheet_name(name)
        if date_iso is None:
            errors.append(f"sheet name doesn't match the expected date pattern: '{name}'")
            continue
        base_code, suffix = split_shift_code_suffix(shift_code)
        sheet_info[name] = (date_iso, shift_code, base_code, suffix)
        if suffix is None:
            clean_bases.setdefault(date_iso, set()).add(base_code)

    # Pass 2: parse everything that isn't a confirmed duplicate.
    for name, (date_iso, shift_code, base_code, suffix) in sheet_info.items():
        if suffix is not None and base_code in clean_bases.get(date_iso, ()):
            skipped_sheets.append(name)  # duplicate/edit-history copy of the clean sheet
            continue

        record, error = parse_shift_sheet(wb[name], name)
        if error:
            errors.append(error)
            continue

        # Blank-filtering only applies to suffixed sheets (where duplication
        # -- an inactive parallel line, or a stray empty copy -- is the
        # actual concern). A clean/unsuffixed sheet is the sole record for
        # its date+shift, so an all-zero result is real, reportable data
        # (e.g. a Night shift that's honestly never run), not junk to hide.
        if suffix is not None and is_blank_record(record):
            continue

        record["sheet"] = name
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
