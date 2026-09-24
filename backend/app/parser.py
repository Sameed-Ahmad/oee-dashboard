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
from collections import Counter
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
    groups: dict[str, list[dict]] = None  # group label -> day records, e.g. Ishida's named machines


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


def corrected_day_availability(ws) -> tuple[int, int, float] | None:
    """Recomputes the WHOLE DAY's available time, actual run time, and
    Availability % for PRODUCTION DEPT sheets only (HNC 1/HNC 3/Coated
    Peanut/Namak Para/Extruder/Kuiper), so that "planned shut down" minutes
    (a genuinely scheduled non-production interval, e.g. a break) are
    excluded from the baseline BEFORE measuring how much of the remaining
    time was lost to unplanned downtime (breakdowns, changeovers, ...).

    Production Dept's rows genuinely split the day's schedule across
    distinct named products (e.g. HNC 1's Masoor/Peanut/Sev/... each get
    their own slice, which sum back to the day's real total), and -- this
    is the actual bug -- their own "Planned run Time" does NOT have
    "planned shut down" subtracted (verified against real cells: "Total
    Time in minutes" == "Planned run Time" exactly, ignoring "planned shut
    down" entirely, so the sheet's own Run Time/Availability % never
    account for it).

    Packing Dept (Fry-O/Pops/Ishida/Nimco) is deliberately EXCLUDED from
    this correction, despite having the same-looking columns: verified
    against real cells, their "Planned run Time" already HAS shutdown
    subtracted (it always equals the summary anchor's own "Plant operating
    time" minus "planned shut down", identically on every row -- whether
    that's many machine-asset rows sharing one product [Fry-O: ~20 rows,
    the same 570/50 pair] or several named machines [Ishida: each active
    row still carries the one shared value, e.g. 480/30, not a per-machine
    split]), and their own reported Availability % already exactly matches
    what recomputing it from scratch produces -- there's nothing to fix.
    An earlier version of this function "corrected" Packing Dept too,
    which was wrong twice over: it double-subtracted shutdown (already
    baked into "Planned run Time"), and separately, naively summing the
    Total row's own "Planned run Time" multiplies that one shared window by
    however many rows happen to share it (Fry-O's own Total row reports
    8038 minutes of "planned run time" for what is really one ~520-minute
    shift).

    Which layout a sheet has is decided the same deterministic, header-text
    way parse_machine_group_records already tells the two departments
    apart: Packing Dept's per-row table has a "Speed" column that
    Production Dept's never does (it has "Standard Output" instead -- see
    MACHINE_ROW_HEADERS/PRODUCTION_ROW_HEADERS). An earlier version of this
    check instead compared each row's own "Planned run Time" against the
    anchor block's own reported time and took a majority vote -- wrong,
    because a sheet with very few real rows (e.g. only 1-2 products
    actually run that day) can hit a coincidental match on that vote and
    get misclassified as Packing Dept, leaving a genuine Production Dept
    bug uncorrected (verified: HNC 1's 2026-02-24 sheet, with just 2 real
    rows, had exactly this coincidence). Production Dept sheets get
    corrected by summing every row's own (shutdown-adjusted) window --
    including a product listed on more than one row for genuinely distinct
    time slots, which must both count -- and weighting each row's own
    ratio by that window when averaging Availability %.

    Returns None if this sheet doesn't have a per-row table with these
    columns and an identifiable group column at all, or turns out to be
    the Packing Dept pattern -- callers should leave the sheet's own
    reported values untouched in either case.
    """
    header_row, dt_cols = find_downtime_range(ws)
    total_row = find_total_row(ws)
    if header_row is None or total_row is None:
        return None

    planned_run_col = find_exact_header_column(ws, header_row, PLANNED_RUN_TIME_HEADER)
    planned_shutdown_col = find_exact_header_column(ws, header_row, PLANNED_SHUTDOWN_HEADER)
    if planned_run_col is None or planned_shutdown_col is None:
        return None

    group_col, _ = find_group_column(ws, header_row, 7, total_row)
    if group_col is None:
        return None

    if find_exact_header_column(ws, header_row, "speed") is not None:
        return None  # Packing Dept pattern -- already correct, nothing to fix

    raw_rows: list[tuple[float, float, float]] = []  # (planned_run_row, planned_shutdown_row, raw downtime_row)
    for r in range(7, total_row):
        group_val = ws.cell(row=r, column=group_col).value
        if group_val in (None, "") or str(group_val).strip().lower() in NON_GROUP_ROW_LABELS:
            continue
        planned_run_row = _num(ws.cell(row=r, column=planned_run_col).value)
        planned_shutdown_row = _num(ws.cell(row=r, column=planned_shutdown_col).value)
        if planned_run_row <= 0:
            continue  # not scheduled on this row -- doesn't count either way
        downtime_raw_row = sum(_num(ws.cell(row=r, column=c).value) for c in dt_cols)
        raw_rows.append((planned_run_row, planned_shutdown_row, downtime_raw_row))

    if not raw_rows:
        return None

    # Each row is its own product's genuinely distinct slice of the day
    # (never a shared constant repeated across rows -- that's the Packing
    # Dept pattern, already excluded above), so every row counts, including
    # a product listed more than once for two distinct time slots (e.g.
    # Kuiper's "FryO Sweet & Sour") -- both slots are real time and both
    # must be summed, not deduped by product name.
    all_rows: list[tuple[float, float]] = []
    for planned_run_row, planned_shutdown_row, downtime_raw_row in raw_rows:
        available_row = max(0, planned_run_row - planned_shutdown_row)
        if available_row <= 0:
            continue
        downtime_row = min(available_row, downtime_raw_row)
        all_rows.append((available_row, downtime_row))

    if not all_rows:
        return 0, 0, 0.0

    total_available = sum(avail for avail, _ in all_rows)
    availability_pct = sum(avail - dt for avail, dt in all_rows) / total_available * 100
    run_time = round(sum(avail - dt for avail, dt in all_rows))

    return int(round(total_available)), int(run_time), round(availability_pct, 2)


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

    # Override the anchor block's own availTime/actTime/availabilityPct
    # (which don't account for planned shutdown -- see
    # corrected_day_availability) with the corrected figures, and re-derive
    # OEE % to match. Returns None (leaving the sheet's own reported values
    # untouched) only if this sheet has no per-row table with these columns
    # at all.
    corrected = corrected_day_availability(ws)
    if corrected is not None:
        avail_time_corrected, act_time_corrected, availability_pct_corrected = corrected
        record["availTime"] = avail_time_corrected
        record["actTime"] = act_time_corrected
        record["availabilityPct"] = round(availability_pct_corrected, 2)
        record["oeePct"] = round(
            availability_pct_corrected * record["performancePct"] * record["qualityPct"] / 10000, 2
        )

    return record, None


GROUP_HEADER_KEYWORDS = ("product", "machine", "sku")

# Exact header text for the two columns used to correct Availability % (see
# corrected_day_availability) -- pulled out as constants since they're read
# both at the whole-day level (Total row) and per-row level, in both
# departments' layouts.
PLANNED_RUN_TIME_HEADER = "planed run time in minutes"  # sic -- real header typo
PLANNED_SHUTDOWN_HEADER = "planned shut down in minutes"

# Per-machine-row metric columns, located by exact header text (verified
# identical across Fry-O/Pops/Ishida/Nimco). Unlike the downtime columns,
# these aren't found via a start/end marker pair, so each needs its own
# exact match -- "speed" and "target counter" in particular have other
# columns nearby ("Speed losses in minutes", "Target Counter in minutes")
# that a loose substring match would wrongly pick up instead.
MACHINE_ROW_HEADERS = {
    "speed": "speed",
    "actual_count": "actual total count",
    "performance_pct": "performance percentage",
    "target_counter": "target counter",
    "stock_transferred": "good conter transfer to warehouse",
    "planned_run_time": PLANNED_RUN_TIME_HEADER,
    "planned_shutdown": PLANNED_SHUTDOWN_HEADER,
}

# Production Dept's per-product-row table uses a completely different column
# set from Packing Dept's (verified identical across Coated Peanut/Namak
# Para/HNC 1/HNC 3/Extruder/Kuiper) -- tried as a fallback whenever
# MACHINE_ROW_HEADERS doesn't fully match a sheet. Unlike Packing Dept,
# "Actual Ouput without Wastage" (good output) / "Output With Wastage"
# (total output) ARE both tracked per product row here (verified: their
# ratio reproduces the sheet's own "Quality Percentage" exactly), so
# Quality %/OEE % are real at this granularity, not forced to "not tracked".
PRODUCTION_ROW_HEADERS = {
    "speed": "standard output",
    "actual_count": "output with wastage",
    "performance_pct": "performance percentage",
    "target_counter": "target output with wastage",
    "stock_transferred": "actual ouput without wastage",  # sic -- real header typo
    "planned_run_time": PLANNED_RUN_TIME_HEADER,
    "planned_shutdown": PLANNED_SHUTDOWN_HEADER,
}


def find_exact_header_column(ws, header_row: int, exact_text: str, max_col: int = 45) -> int | None:
    target = exact_text.strip().lower()
    for c in range(1, max_col + 1):
        v = ws.cell(row=header_row, column=c).value
        if isinstance(v, str) and v.strip().lower() == target:
            return c
    return None


# Rows in the machine table that are actually trailing summary labels, not
# machine/line entries -- they sit between the last real machine row and
# the "Total" row, in the SAME column used for grouping on Fry-O/Pops, so
# they'd otherwise be picked up as spurious one-row "groups".
NON_GROUP_ROW_LABELS = {
    "oee calculation", "planned capacity utilization",
    "overall capacity utilization", "global efficiency", "total",
}


def find_group_column(ws, header_row: int, start_row: int, end_row: int) -> tuple[int | None, str | None]:
    """Finds whichever column names what's running on each machine row --
    a literal machine name for Ishida ("Machine": Ishida 1/Ishida 2/
    Simionato), a product/SKU code for Nimco ("SKU": R10 L, R20, ...), or a
    product name for Fry-O/Pops ("Product"). The header text alone isn't
    enough to pick the right column: Nimco also has a "Product Name" column
    that's always blank, and a "machine #" column of numeric ASSET TAGS that
    isn't the meaningful grouping either -- so any header containing "#" is
    excluded (an ID/tag column, not a descriptive name/code one), and among
    what's left, the first keyword-matching column that actually has data
    in the machine-row range wins."""
    candidates = []
    for c in range(1, 10):
        header = ws.cell(row=header_row, column=c).value
        if not isinstance(header, str) or "#" in header:
            continue
        if any(k in header.lower() for k in GROUP_HEADER_KEYWORDS):
            candidates.append((c, header.strip()))
    for c, header in candidates:
        for r in range(start_row, end_row):
            v = ws.cell(row=r, column=c).value
            if v not in (None, "") and str(v).strip().lower() not in NON_GROUP_ROW_LABELS:
                return c, header
    return None, None


def normalize_group_key(label: str) -> str:
    """Key used to merge group labels that differ only in whitespace, e.g.
    Nimco's "R20 L" and "R20L" -- verified to be the SAME line/SKU, not two
    distinct ones: on every date one spelling appears, the other does too,
    entered against different individual machine-asset rows on the
    identical sheet. Treating them as separate 'lines' would silently split
    one real line's daily totals across two buckets. The canonical display
    spelling is chosen later, once every sheet's been seen (see
    parse_workbook), as whichever spelling occurs most often."""
    return re.sub(r"\s+", "", label).upper()


def parse_machine_group_records(
    ws, sheet_name: str, avail_time: int, act_time: int
) -> tuple[dict[str, list[dict]], bool | None]:
    """Extracts one 'virtual shift record' per individual machine/line row,
    grouped by a whitespace-normalized key of whichever column names it (see
    find_group_column, normalize_group_key). These reuse the exact same
    field shape aggregate_day already knows how to combine, so a group's
    records across multiple shifts/dates are combined with the same SUM/
    RECOMPUTE/weighted-average rules as whole-shift records -- no separate
    aggregation logic needed.

    Tries Packing Dept's column layout (MACHINE_ROW_HEADERS) first, falling
    back to Production Dept's completely different one (PRODUCTION_ROW_HEADERS)
    if that doesn't fully match -- returns {} (and None) if neither does.
    The second return value says whether Quality %/OEE % are real at this
    granularity for whatever layout matched: Packing Dept never tracks good-
    unit counts per row, but Production Dept does (see PRODUCTION_ROW_HEADERS).

    `avail_time`/`act_time` are the WHOLE SHEET's shared schedule window
    (from the summary anchor block) -- the same for every row on the shift
    (verified against real formulas: "Plant operating time" is an absolute-
    reference constant, not a per-row figure). This shared window is only
    meaningful for PACKING Dept, where every row is a separate machine-asset
    running the SAME product in parallel through the whole shift, so the
    window genuinely applies to every one of them -- but summing it once per
    row would multiply a single shift's time window by however many
    machine-asset rows share that group, so only the FIRST row seen for a
    given group on this sheet carries `avail_time`/`act_time` into the
    `availTime`/`actTime` fields; the rest carry 0.

    Production Dept has no such shared window at the per-product level: each
    row genuinely occupies its own, independently-additive slice of the
    day's schedule (`available_after_shutdown_row` below), including a
    product occasionally listed twice for two distinct time slots (e.g.
    Kuiper's "FryO Sweet & Sour") -- both slots are real time and must both
    be counted, never deduped by key the way Packing Dept's shared window
    is. So Production Dept's `availTime`/`actTime`/`idealTargetOutput` all
    use this row's own baseline/run_time directly, summed across however
    many rows share that group.

Every row's own `run_time`/Availability % is computed as baseline -
    downtime, same correction as corrected_day_availability, applied at row
    granularity, rather than read directly from the sheet's own
    (uncorrected) "Run Time in minutes"/"Availability Percentage" columns --
    but the baseline itself differs by department (see
    corrected_day_availability for why): Production Dept's "Planned run
    Time" does NOT have shutdown subtracted, so it's subtracted here
    (baseline = Planned run Time - planned shutdown); Packing Dept's
    ALREADY does (baseline = Planned run Time as-is; subtracting shutdown
    again would double-count it).

    A row that's entirely zero (no run time, no output, no downtime) is
    dropped rather than kept as a zero-value day -- Production Dept's sheets
    list every candidate product every day whether or not it actually ran
    that shift, so keeping these would flood a rarely-run product's group
    with meaningless all-zero "days".
    """
    header_row, dt_cols = find_downtime_range(ws)
    total_row = find_total_row(ws)
    if header_row is None or total_row is None:
        return {}, None

    group_col, _ = find_group_column(ws, header_row, 7, total_row)
    if group_col is None:
        return {}, None

    cols = {key: find_exact_header_column(ws, header_row, text) for key, text in MACHINE_ROW_HEADERS.items()}
    quality_tracked = False
    if any(c is None for c in cols.values()):
        cols = {key: find_exact_header_column(ws, header_row, text) for key, text in PRODUCTION_ROW_HEADERS.items()}
        quality_tracked = True
        if any(c is None for c in cols.values()):
            return {}, None

    by_group: dict[str, list[dict]] = {}
    seen_time_for_key: set[str] = set()
    for r in range(7, total_row):
        group_val = ws.cell(row=r, column=group_col).value
        if group_val in (None, "") or str(group_val).strip().lower() in NON_GROUP_ROW_LABELS:
            continue
        raw_label = str(group_val).strip()
        key = normalize_group_key(raw_label)

        speed = float(_num(ws.cell(row=r, column=cols["speed"]).value))
        actual_count = int(_num(ws.cell(row=r, column=cols["actual_count"]).value))

        downtime = {
            (ws.cell(row=header_row, column=c).value or f"Category {c}"): float(_num(ws.cell(row=r, column=c).value))
            for c in dt_cols
        }

        # Same correction as corrected_day_availability, applied per row
        # instead of at the whole-sheet Total row: planned shutdown is
        # excluded from the baseline before measuring downtime against it,
        # rather than trusting the sheet's own (uncorrected) "Run Time in
        # minutes"/"Availability Percentage" columns -- but ONLY for
        # Production Dept, where "Planned run Time" genuinely does NOT
        # already have shutdown subtracted (verified). Packing Dept's
        # "Planned run Time" DOES already have it subtracted (verified: it
        # always equals the summary anchor's own "Plant operating time"
        # minus "planned shut down") -- subtracting it again here would
        # double-count it, so Packing Dept rows use "Planned run Time" as
        # the baseline directly, matching corrected_day_availability's own
        # department-aware handling.
        planned_run_time_row = _num(ws.cell(row=r, column=cols["planned_run_time"]).value)
        planned_shutdown_row = _num(ws.cell(row=r, column=cols["planned_shutdown"]).value)
        available_after_shutdown_row = (
            max(0, planned_run_time_row - planned_shutdown_row) if quality_tracked else planned_run_time_row
        )
        # Clamped at 0: a few real rows compute a negative figure (e.g. a
        # changeover logged against a product that was never scheduled that
        # shift) -- not a meaningful quantity to carry into a displayed total.
        run_time = int(round(max(0, available_after_shutdown_row - sum(downtime.values()))))
        availability_pct_row = (
            round(run_time / available_after_shutdown_row * 100, 2) if available_after_shutdown_row else 0.0
        )

        if run_time == 0 and actual_count == 0 and not any(downtime.values()):
            continue  # listed but never run this shift -- not real data

        is_first_for_key = key not in seen_time_for_key
        seen_time_for_key.add(key)

        # The run time used for the OUTPUT-CAPACITY calc is always the real,
        # undeduped figure (Production Dept: this row's own run time;
        # Packing Dept: the shared shift duration) -- output capacity is
        # genuinely additive per row regardless of layout. The stored
        # "actTime" bookkeeping FIELD is different: Production Dept's is
        # already real and per-row (no dedup needed), but Packing Dept's is
        # the shared shift duration, so -- same reasoning as availTime above
        # -- only the first row for a group on this sheet carries it there.
        capacity_act_time = run_time if quality_tracked else act_time
        stored_act_time = run_time if quality_tracked else (act_time if is_first_for_key else 0)

        # Same department split for the baseline itself. Production Dept:
        # available_after_shutdown_row is THIS product's own scheduled slice
        # of the day, genuinely additive across rows -- including a product
        # occasionally listed twice in two distinct time slots (e.g.
        # Kuiper's "FryO Sweet & Sour"), where both slices are real and must
        # both count (never dedup this the way the shared `avail_time` param
        # below is deduped, or actTime can end up exceeding it). Packing
        # Dept: `avail_time` is one shared shift-duration constant repeated
        # on every one of a product's machine-asset rows, so only the first
        # row for a group carries it; summing it across rows would multiply
        # a single shift window by however many rows share that group.
        stored_avail_time = (
            int(round(available_after_shutdown_row)) if quality_tracked
            else (avail_time if is_first_for_key else 0)
        )
        capacity_avail_time = available_after_shutdown_row if quality_tracked else avail_time

        record = {
            "sheet": sheet_name,
            "rawGroupLabel": raw_label,
            "availMachines": 1,
            "actMachines": 1 if run_time > 0 else 0,
            "avgSpeed": speed,
            "availTime": stored_avail_time,
            "actTime": stored_act_time,
            "idealTargetOutput": speed * capacity_avail_time,
            "actualTargetOutput": speed * capacity_act_time,
            "availabilityPct": round(availability_pct_row, 2),
            "targetCounter": int(_num(ws.cell(row=r, column=cols["target_counter"]).value)),
            "actualCounter": actual_count,
            "performancePct": float(_num(ws.cell(row=r, column=cols["performance_pct"]).value)),
            "stockTransferred": int(_num(ws.cell(row=r, column=cols["stock_transferred"]).value)),
            "totalLabor": 0,
            "downtime": downtime,
        }
        by_group.setdefault(key, []).append(record)

    return by_group, (quality_tracked if by_group else None)


def is_blank_record(rec: dict) -> bool:
    """A sub-record that contributed nothing real that date -- either a
    leftover empty template copy or an inactive parallel production line
    (Coated Peanut reports multiple lines as separate same-date sheets, not
    all of which ran every day). Either way, exclude it from that date's
    aggregation rather than counting it as a zero-output shift.

    Judged purely by OUTPUT (idealTargetOutput/actualCounter), not
    availTime/actTime: verified against real cells, an inactive parallel
    line can still carry a nonzero "Planned run Time"/"planned shut down"
    in its per-product table (apparently entered as a schedule regardless
    of whether the line actually ran) even though it produced genuinely
    nothing -- corrected_day_availability picks that up as a real time
    figure, so time alone is no longer a reliable "nothing happened" signal
    the way it was before that correction existed."""
    return rec["idealTargetOutput"] == 0 and rec["actualCounter"] == 0


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
        return ParseResult(records=[], errors=[f"no Excel file found for '{config.slug}'"], skipped_sheets=[], groups={})

    wb = openpyxl.load_workbook(path, data_only=True)

    by_date: dict[str, list[dict]] = {}
    by_group_date: dict[str, dict[str, list[dict]]] = {}  # normalized key -> date -> rows
    group_label_counts: dict[str, Counter] = {}  # normalized key -> Counter(raw spelling -> occurrences)
    group_quality_tracked: dict[str, bool] = {}  # normalized key -> whether Quality %/OEE % are real at this granularity
    errors: list[str] = []
    skipped_sheets: list[str] = []

    # Pass 1: classify every date-named sheet as "clean" (no numeric "(NN)"
    # suffix) or "suffixed", so a suffixed sheet can be told apart from a
    # true duplicate (Fry-O/Nimco: a clean sibling for that same date+shift
    # already exists) vs a genuinely distinct parallel line (Coated Peanut:
    # no clean sibling ever exists for those dates at all).
    sheet_info: dict[str, tuple[str, str, str, str | None]] = {}  # name -> (date, shift_code, base_code, suffix)
    clean_bases: dict[str, set[str]] = {}
    # (date, base_code) -> clean sheet names that resolve to it, in workbook
    # order -- catches a different duplication pattern than the "(NN)" suffix
    # above: two "clean" sheets that are literally the same date+shift but
    # spelled with inconsistent year-digit width (e.g. HNC 1 has both
    # "10-02-26" and "10-02-2026" for 2026-02-10). Neither has a suffix, so
    # neither is caught by the check above, and both would otherwise be
    # aggregated together as if they were genuinely separate shifts, doubling
    # that date's numbers.
    clean_sheet_names: dict[tuple[str, str], list[str]] = {}
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
            clean_sheet_names.setdefault((date_iso, base_code), []).append(name)

    # Keep only the first clean sheet for each (date, shift) pair; any others
    # are the same real-world shift reported twice under a different sheet
    # name, so they're treated exactly like a "(NN)" duplicate -- skipped,
    # not aggregated.
    duplicate_format_sheets: set[str] = set()
    for names in clean_sheet_names.values():
        duplicate_format_sheets.update(names[1:])

    # Pass 2: parse everything that isn't a confirmed duplicate.
    for name, (date_iso, shift_code, base_code, suffix) in sheet_info.items():
        if name in duplicate_format_sheets:
            skipped_sheets.append(name)  # same date+shift as another clean sheet, different name format
            continue
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

        # Per-machine/line breakdown, keyed by (normalized group key, date)
        # -- e.g. Ishida's named machines or Nimco's SKU codes. Empty for
        # sheets with no identifiable group column (parse_machine_group_records
        # degrades gracefully rather than erroring).
        group_rows_by_key, quality_tracked = parse_machine_group_records(
            wb[name], name, record["availTime"], record["actTime"]
        )
        for key, group_rows in group_rows_by_key.items():
            by_group_date.setdefault(key, {}).setdefault(date_iso, []).extend(group_rows)
            group_quality_tracked[key] = quality_tracked
            counts = group_label_counts.setdefault(key, Counter())
            for row in group_rows:
                counts[row["rawGroupLabel"]] += 1

    day_records = [aggregate_day(d, recs) for d, recs in by_date.items()]
    day_records.sort(key=lambda r: r["date"])

    # A group with fewer than this many real recorded days is noise -- a
    # one-off typo'd SKU/status entry (e.g. Nimco's "S/mix", "Moong 20",
    # each seen on a single day) rather than a real recurring line -- and
    # isn't worth surfacing as a selectable machine/line.
    MIN_GROUP_DAYS = 10

    groups = {}
    for key, dates in by_group_date.items():
        group_records = [aggregate_day(d, recs) for d, recs in dates.items()]
        if len(group_records) < MIN_GROUP_DAYS:
            continue
        if not group_quality_tracked.get(key):
            # Packing Dept: "Good units transferred to warehouse" (needed
            # for Quality %) is only ever populated at the whole-shift
            # aggregate level, not per machine row -- verified against real
            # cells across all four products (mostly blank, occasionally a
            # stray manually-entered value, never a real per-row formula).
            # Reusing aggregate_day's sum-based Quality %/OEE % here would
            # silently show a false 0%, so both are explicitly marked
            # unavailable at this granularity instead. Production Dept
            # tracks real per-product good/total output, so its groups skip
            # this and keep the real recomputed Quality %/OEE %.
            for r in group_records:
                r["qualityPct"] = None
                r["oeePct"] = None
        group_records.sort(key=lambda r: r["date"])
        display_label = group_label_counts[key].most_common(1)[0][0]
        groups[display_label] = group_records

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

    return ParseResult(records=day_records, errors=errors, skipped_sheets=skipped_sheets, groups=groups)
