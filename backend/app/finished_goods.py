"""Finished-goods warehouse receipts for the Packing Dept (Fry-O, Ishida,
Pops, Nimco), read from the standalone monthly ERP export workbooks
(backend/data/ERP/PACKING SHAHI 1 <Mon>26 TRANSFAR ORDER SHIPMENT.xlsx)
-- NOT the day-by-day OEE workbooks parser.py handles, and not the Labor
Cost Analysis workbook either. This is a transaction-level export, one
row per batch, at day granularity -- a much finer-grained "Received"
figure than the Labor Cost workbook's monthly Output Input numbers.

Every genuine row in this export is a "Transfer order shipment" with
Issue="Sold" and a NEGATIVE Quantity -- confirmed with the person running
this dashboard: despite the "Sold"/"shipment" labeling (an artifact of
how the source ERP records a transfer-out from Production's own location
as a negative line), this is what counts as the finished-goods
warehouse's own received quantity. Quantity's sign is just bookkeeping
(negative at the shipping end of the transfer) -- the packet count is
its absolute value. (An earlier version of this module read a
differently-named, differently-shaped export -- "Production <Mon>-26
S1.xlsx", all POSITIVE-quantity "Purchased" receipt rows with occasional
"Sold" reversal rows to exclude -- see git history. That workbook is no
longer being provided; this one replaces it, with the opposite sign/
Issue convention.)

Mapping each row to one of the 4 tracked Packing products, in priority
order:

1. Location "Ishida 1" / "Ishida1" / "Ishida 2" / "Saminato" -> ishida,
   REGARDLESS of brand. These machines physically pack a mix of brands
   (PS-*, SN-*, THUNDERPOP-*, even some FryO-*/BB-* overflow) and
   whatever ran on them that day counts as Ishida's own received output
   -- confirmed explicitly even for the SN-* family, which is otherwise
   a Nimco brand.
2. Otherwise, brand prefix wins when recognized (FryO-* -> fryo,
   BB-*/SN-* -> nimco, PS-*/WHEATO-*/WheatO-*/THUNDERPOP-* -> pops) --
   even at a location whose OWN usual brand differs. A small number of
   rows show a different brand's item logged at the "Fry O"/"BB-R10"/
   "BB-R20"/"Pops" locations (e.g. a FryO-branded batch logged at "Pops"
   on 2026-07-21, 3166 units), and verified against the OEE sheet's own
   Produced figure for that day: the item's own brand, not the location
   it happened to be logged at, is what the OEE side actually counted it
   as. (This was a real bug here -- location was wrongly used to
   override brand for "Pops" too, silently moving 227,952 packets of
   Fry-O's own July 21 output into Pops' received total instead, see git
   history for the pre-fix version.)
3. Otherwise (brand prefix not recognized -- e.g. "DAAL-R10-ACHARI
   NAMKEEN", which doesn't start with any of the known brand prefixes
   despite genuinely being a Nimco-line item), fall back to the KNOWN
   location's own product: "Fry O" -> fryo, "BB-R10"/"BB-R20" -> nimco,
   "Pops" -> pops. (This step was missing entirely in an earlier version
   of step 2's brand-first rewrite -- silently dropped ~245,000 packets
   across 7 dates that had no recognized brand prefix and weren't at a
   location this step covers, since there was nothing left to fall back
   on.)
4. Otherwise (neither brand nor location resolves it -- e.g. location
   "01", not a tracked OEE machine), fall back to the Item Group column:
   "FG-NIMKO" -> nimco. Item Group can't distinguish fryo/pops/ishida
   (snack items of any of those brands can all be filed under
   "FG-SNACKS"), so a "FG-SNACKS" row that reaches this step is left
   unmapped rather than guessed at.

Each item name ends in a pack-size code like "(12X6)" or "(6X6)" --
multiplying the numbers inside the parentheses gives packets per unit
of the row's Quantity; multiplying that product by Quantity gives total
packets received for that row. The "Unit" column (HALF-DOZEN/Dozen/
CARTON) is NOT used for this -- verified it is not a reliable function
of the item name (the same pack code shows a different Unit depending
on the specific item/line it's attached to), so the name-based formula
is the only trustworthy source.

Rows with a blank/zero Quantity (trailing template rows in the sheet)
are skipped; every other row counts.
"""
from __future__ import annotations

import re
from pathlib import Path

import openpyxl

from .labor_cost import MONTH_NAMES

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "ERP"

# A day's Produced vs. Received gap (in either direction) beyond this
# percentage is flagged -- small gaps are ordinary day-to-day timing noise
# between when a batch is physically packed and when it's logged into the
# FG warehouse; anything past this is worth a second look.
FLAG_THRESHOLD_PCT = 2.0

PACK_SIZE_RE = re.compile(r"\(((?:\d+\s*[xX]\s*)+\d+)\)")

# Step 1 of the priority order in the module docstring -- these always
# win over brand.
ISHIDA_LOCATIONS = {"ishida 1", "ishida1", "ishida 2", "saminato"}

# Order matters: checked as a prefix match against the upper-cased item name.
BRAND_PREFIX_TO_SLUG = [
    ("BB", "nimco"),
    ("SN", "nimco"),
    ("FRYO", "fryo"),
    ("WHEATO", "pops"),
    ("THUNDERPOP", "pops"),
    ("PS", "pops"),
]

# Step 3 of the priority order -- only consulted when the brand prefix
# isn't recognized at all.
LOCATION_TO_SLUG = {
    "fry o": "fryo",
    "bb-r10": "nimco",
    "bb-r20": "nimco",
    "pops": "pops",
}

_workbook_cache: dict[str, openpyxl.Workbook] | None = None


def _load_workbooks() -> list[openpyxl.Workbook]:
    global _workbook_cache
    if _workbook_cache is None:
        _workbook_cache = {}
        for path in sorted(DATA_DIR.glob("PACKING SHAHI 1 * TRANSFAR ORDER SHIPMENT.xlsx")):
            try:
                _workbook_cache[path.name] = openpyxl.load_workbook(path, data_only=True)
            except (OSError, KeyError):
                continue
    return list(_workbook_cache.values())


def _pack_multiplier(item_name: str) -> int | None:
    match = PACK_SIZE_RE.search(item_name)
    if not match:
        return None
    total = 1
    for part in re.split(r"[xX]", match.group(1)):
        total *= int(part.strip())
    return total


def _brand_slug(item_name: str) -> str | None:
    upper = item_name.upper()
    for prefix, slug in BRAND_PREFIX_TO_SLUG:
        if upper.startswith(prefix):
            return slug
    return None


def _product_slug(location: str | None, item_name: str, item_group: str | None = None) -> str | None:
    """Implements the 4-step priority order in the module docstring."""
    norm_loc = (location or "").strip().lower()
    if norm_loc in ISHIDA_LOCATIONS:
        return "ishida"
    brand = _brand_slug(item_name)
    if brand:
        return brand
    loc_slug = LOCATION_TO_SLUG.get(norm_loc)
    if loc_slug:
        return loc_slug
    if item_group == "FG-NIMKO":
        return "nimco"
    return None


def _received_rows():
    """Yields (date_iso, slug, packets) for every genuine receipt row
    across all loaded finished-goods workbooks. Quantity is negative in
    this export (see module docstring) -- packets is always a positive
    count, taken from its absolute value."""
    for wb in _load_workbooks():
        ws = wb["Sheet1"]
        headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        col = {name: i for i, name in enumerate(headers)}
        for row in ws.iter_rows(min_row=2, values_only=True):
            item_name = row[col["Item Name"]]
            quantity = row[col["Quantity"]]
            date = row[col["Physical date"]]
            if not item_name or not quantity or date is None:
                continue
            multiplier = _pack_multiplier(item_name)
            if multiplier is None:
                continue
            slug = _product_slug(row[col["Location"]], item_name, row[col["Item Group"]])
            if slug is None:
                continue
            yield date.date().isoformat(), slug, multiplier * abs(quantity)


def compute_received_by_day(slug: str) -> dict[str, float]:
    """date (YYYY-MM-DD) -> total packets received for this product,
    across every loaded finished-goods workbook."""
    totals: dict[str, float] = {}
    for date_iso, row_slug, packets in _received_rows():
        if row_slug == slug:
            totals[date_iso] = totals.get(date_iso, 0.0) + packets
    return totals


def _coverage_date_range() -> tuple[str, str] | None:
    """(earliest, latest) date, inclusive, seen across ANY product in the
    loaded finished-goods workbooks -- used to scope the day-level
    comparison to days this data source could possibly have covered,
    rather than flagging every OEE day outside these files' date range as
    a false "nothing received" anomaly."""
    dates = {date_iso for date_iso, _, _ in _received_rows()}
    if not dates:
        return None
    return min(dates), max(dates)


def compute_fg_reconciliation(slug: str, records: list[dict]) -> dict | None:
    """Produced (this dashboard's own OEE-tracked stockTransferred -- the
    day's net output actually transferred to stock, same figure each
    day's own sheet highlights, not the gross actualCounter before
    quality-based rejection) vs. Received (this module's finished-goods
    warehouse receipts), rolled up by month for the overview table, with
    each month's own days nested underneath for drill-down. Scoped to
    OEE days that fall inside the date range these finished-goods
    workbooks cover.

    A day, a month, or the overall total (the last returned alongside the
    months list for quick use on summary cards) is "flagged" when Received
    falls short of Produced by more than FLAG_THRESHOLD_PCT -- most often
    because the batch hasn't been logged into the FG warehouse yet,
    occasionally a genuine loss worth investigating. Received exceeding
    Produced is NOT flagged -- that direction is expected (a receipt can
    legitimately include an earlier day's carryover batch) and isn't the
    anomaly this is meant to catch. Each level's flag is computed
    independently from its own produced/received totals, not derived from
    the level below -- a month can be flagged even if every individual day
    inside it looks fine on its own (small shortfalls compounding), and
    vice versa.

    Returns None if this product has no finished-goods data at all (only
    fryo/ishida/pops/nimco do -- see module docstring)."""
    coverage = _coverage_date_range()
    if coverage is None:
        return None
    start, end = coverage

    received_by_day = compute_received_by_day(slug)
    if not received_by_day:
        return None

    days_by_month: dict[str, list[dict]] = {}
    for r in sorted(records, key=lambda rec: rec["date"]):
        date = r["date"]
        if date < start or date > end:
            continue
        produced = r["stockTransferred"]
        if produced <= 0:
            continue
        received = received_by_day.get(date, 0.0)
        gap = produced - received
        day_entry = {
            "date": date,
            "produced": round(produced, 1),
            "received": round(received, 1),
            "gap": round(gap, 1),
            "gapPct": round(gap / produced * 100, 2),
            "flagged": gap > produced * FLAG_THRESHOLD_PCT / 100,
        }
        days_by_month.setdefault(date[:7], []).append(day_entry)

    months_result = []
    for month_key in sorted(days_by_month):
        days = days_by_month[month_key]
        total_produced = sum(d["produced"] for d in days)
        total_received = sum(d["received"] for d in days)
        gap = total_produced - total_received
        year, month_idx = int(month_key[:4]), int(month_key[5:7])
        months_result.append({
            "month": month_key,
            "monthLabel": f"{MONTH_NAMES[month_idx - 1]} {year}",
            "produced": round(total_produced, 1),
            "received": round(total_received, 1),
            "gap": round(gap, 1),
            "gapPct": round(gap / total_produced * 100, 2) if total_produced else 0.0,
            "flagged": gap > total_produced * FLAG_THRESHOLD_PCT / 100 if total_produced else False,
            "days": days,
        })

    overall_produced = sum(m["produced"] for m in months_result)
    overall_received = sum(m["received"] for m in months_result)
    overall_gap = overall_produced - overall_received

    return {
        "flagThresholdPct": FLAG_THRESHOLD_PCT,
        "produced": round(overall_produced, 1),
        "received": round(overall_received, 1),
        "gap": round(overall_gap, 1),
        "gapPct": round(overall_gap / overall_produced * 100, 2) if overall_produced else 0.0,
        "flagged": overall_gap > overall_produced * FLAG_THRESHOLD_PCT / 100 if overall_produced else False,
        "months": months_result,
    }
