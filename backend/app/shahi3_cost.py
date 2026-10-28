"""Labor + electricity (+ gas, Production only) cost for Shahi 3, read from
the monthly "Dept.Wise Cost Sheet Labor & Energy S3(<Mon>-26).xlsx" workbooks
(backend/data/Shahi 3/Labour and Energy/) -- one file per month (currently
Aug-26, Sep-26). Entirely separate from Shahi 1's labor_cost.py/
contractor_labor.py/electricity.py (three separate workbooks there); here
labor, electricity, and the department-cost breakdown all live in ONE file
per month, which is actually simpler to read than Shahi 1's setup.

Each file has a pre-computed "<Mon>-<Year> Summary" sheet (ratios only --
Rs./Pack, Rs./Kg) used here only as a cross-check, and two source sheets
with the real absolute figures this module actually reads:

- "Packing" sheet: one row per item, grouped under "Total <X> Department"
  subtotal rows (Total Packs, Total Weight, Total Payroll, Packing
  Contractor Payment, Labor Cost/Pack, Total Electricity Cost, ...).
  Columns are located by their own header text (spread across rows 3-4,
  since the sheet's left item-detail columns and right Labor/Energy
  columns use different header rows), not hardcoded letters.
- "Plants" sheet: one row per department already at summary grain
  (Production(kgs), Total Payroll, Labor Cost/Kg, Total Electricity
  Cost, Per Kg Electricity Cost, ...), headers all in one row.
- "Support Department" sheet: 6 named support departments (Factory
  Admin & HR, Maintenance, FG Store, Quality Assurance, RM Store, Tech.
  Store) plus one shared-equipment electricity-only line, each with
  Total Payroll + Total Electricity Cost -- see
  compute_shahi3_manufacturing_overhead for how this feeds the
  overhead-loaded Packing/Production cost-per-unit figures.

Department-label -> dashboard-product-slug mapping (confirmed with the
person running this dashboard, 2026-10-27):

- "BB R10"            -> lhr-nimco-1 (the R-10 packing line)
- "BB R20/B30/SN50"   -> lhr-nimco-2 (the R-20 packing line; no raw OEE
  file uploaded for it yet -- cost-only until one is)
- "Ishida" (this sheet) / "Saminato" (the Summary sheet's OWN label for
  the exact same line -- confirmed via an identical Rs. figure in both
  tabs of the same file) -> lhr-siminato
- "FryO" + "Pops" (Packing sheet) -> lhr-snacks, SUMMED together. These
  are NOT two different products -- confirmed with the person running
  the dashboard that Shahi 3's "Snacks" business line is exactly the
  items filed under these two Packing-sheet department rows (WheatO,
  Popstar, Tacoz, Thunder Pops under "Pops"; Fry O itself under "FryO"),
  same pattern as Shahi 1's Nimco summing its own R-10 + R-20 lines.
- "Production - H&C - 2" (Plants sheet) -> shahi3-hnc-2-lhr
- "Production - Pops" (Plants sheet) -> shahi3-extruder, by analogy with
  Shahi 1's OWN "Extruder" line being filed as "Production - Pops" there
  (Extruder is Pops' upstream production-stage machine, not a separate
  product -- see labor_cost.py's docstring) -- same naming convention
  repeating at Shahi 3, even though no raw OEE file has been uploaded
  for shahi3-extruder yet. NOT independently confirmed the way the
  Packing-side mappings above were -- flagged to the person running the
  dashboard as an inference, not a certainty.
- "Production - Batch Frying" / "Production - Mixing" /
  "Production -Flavor Grinding" / "Production -Sorting-Sor-Sifter(...)"
  are NOT mapped to any registered product (none of Shahi 3's existing
  Production stub slugs -- hnc-1/hnc-3/kuiper/nomak-para -- matched with
  any confidence) -- their cost is real but currently unsurfaced on any
  product page until that's resolved.

Gas Cost/Kg is only ever filled in on the Plants sheet's own "Total"
row (every individual department row shows 0 there, with "All Plants"
as a text marker on one row) -- i.e. gas use isn't metered per
department at Shahi 3, only a whole-Production-Dept total exists, so
this module only exposes it at that facility-wide grain, not per
product (parallel to Shahi 1's Gas Generator figure never being split
by department either).
"""
from __future__ import annotations

from pathlib import Path

import openpyxl

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "Shahi 3" / "Labour and Energy"

MONTH_ABBR_TO_NUM = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Packing-sheet "Total <X> Department" label -> the slug(s) it feeds.
# Where more than one label maps to the same slug, their absolute figures
# (payroll, electricity cost, packs, weight) are SUMMED before any ratio
# is recomputed -- never averaging the two lines' own per-unit ratios.
PACKING_LABEL_TO_SLUGS: dict[str, str] = {
    "total bb r10 department": "lhr-nimco-1",
    "total bb r20/b30/sn50 department": "lhr-nimco-2",
    "total ishida department": "lhr-siminato",
    "total fryo department": "lhr-snacks",
    "total pops department": "lhr-snacks",
}

# Plants-sheet department label -> slug. See module docstring for the
# shahi3-extruder inference and the departments deliberately left out.
PLANTS_LABEL_TO_SLUG: dict[str, str] = {
    "production - h&c - 2": "shahi3-hnc-2-lhr",
    "production - pops": "shahi3-extruder",
}

_cache: dict | None = None  # {"packing": {slug: {month_key: {...}}}, "production": {...}, "facility": {month_key: {...}}}


def _num(v):
    return v if isinstance(v, (int, float)) else None


def _find_header_cell(ws, label: str, rows: range, max_col: int = 25) -> tuple[int, int] | tuple[None, None]:
    target = label.strip().lower()
    for r in rows:
        for c in range(1, max_col + 1):
            v = ws.cell(row=r, column=c).value
            if isinstance(v, str) and target in " ".join(v.split()).lower():
                return r, c
    return None, None


def _month_key_from_filename(path: Path) -> tuple[str, str] | None:
    """"...(Aug-26).xlsx" -> ("2026-08", "August 2026")."""
    stem = path.stem
    if "(" not in stem or ")" not in stem:
        return None
    inner = stem.split("(")[-1].split(")")[0]  # "Aug-26"
    parts = inner.split("-")
    if len(parts) != 2:
        return None
    mon_abbr, yy = parts[0].strip().lower()[:3], parts[1].strip()
    if mon_abbr not in MONTH_ABBR_TO_NUM or not yy.isdigit():
        return None
    month_num = MONTH_ABBR_TO_NUM[mon_abbr]
    year = 2000 + int(yy) if len(yy) == 2 else int(yy)
    return f"{year:04d}-{month_num:02d}", f"{MONTH_NAMES[month_num - 1]} {year}"


def _parse_packing_sheet(ws) -> dict[str, dict]:
    """Returns {department_label_lower: {totalPacks, totalWeightTon,
    totalPayroll, packingContractorPaymentRs, totalElectricityCostRs}}."""
    header_rows = range(2, 6)
    # "Total Packs" (bare) is also a different column's header (the per-item
    # pack-size multiplier, e.g. "144") -- must match the longer, more
    # specific "Total Packs ( Pcs )" header to land on the real output total.
    _, col_packs = _find_header_cell(ws, "Total Packs ( Pcs )", header_rows)
    _, col_weight = _find_header_cell(ws, "Total Weight", header_rows)
    _, col_payroll = _find_header_cell(ws, "Total Payroll", header_rows)
    _, col_contractor = _find_header_cell(ws, "Packing Contractor Payment", header_rows)
    # Same ambiguity: "Total Electricity units consumed" sits left of the
    # real "Total Electricity Cost" column and would match a bare "Total
    # Electricity" search first.
    _, col_elec_cost = _find_header_cell(ws, "Total Electricity Cost", header_rows)
    if None in (col_packs, col_weight, col_payroll, col_contractor, col_elec_cost):
        return {}

    results: dict[str, dict] = {}
    for r in range(1, ws.max_row + 1):
        label = ws.cell(row=r, column=2).value
        if not isinstance(label, str):
            continue
        norm = " ".join(label.split()).lower()
        if not norm.startswith("total ") or "department" not in norm:
            continue
        results[norm] = {
            "totalPacks": _num(ws.cell(row=r, column=col_packs).value) or 0.0,
            "totalWeightTon": _num(ws.cell(row=r, column=col_weight).value) or 0.0,
            "totalPayroll": _num(ws.cell(row=r, column=col_payroll).value) or 0.0,
            "packingContractorPaymentRs": _num(ws.cell(row=r, column=col_contractor).value) or 0.0,
            "totalElectricityCostRs": _num(ws.cell(row=r, column=col_elec_cost).value) or 0.0,
        }
    return results


def _parse_plants_sheet(ws) -> dict[str, dict]:
    """Returns {department_label_lower: {productionKg, totalPayroll,
    totalElectricityCostRs}} -- excludes the sheet's own "Total" row
    (facility-wide figures come from _parse_expense_detail_sheet instead,
    a more complete source -- see its docstring)."""
    header_row = 2
    _, col_kg = _find_header_cell(ws, "Production(kgs)", range(1, 4))
    _, col_payroll = _find_header_cell(ws, "Total Payroll", range(1, 4))
    # Same "units consumed" vs "Cost" ambiguity as the Packing sheet.
    _, col_elec_cost = _find_header_cell(ws, "Total Electricity Cost", range(1, 4))
    if None in (col_kg, col_payroll, col_elec_cost):
        return {}

    results: dict[str, dict] = {}
    for r in range(header_row + 1, ws.max_row + 1):
        label = ws.cell(row=r, column=1).value
        if not isinstance(label, str) or not label.strip():
            continue
        norm = " ".join(label.split()).lower()
        if norm == "total":
            continue
        results[norm] = {
            "productionKg": _num(ws.cell(row=r, column=col_kg).value) or 0.0,
            "totalPayroll": _num(ws.cell(row=r, column=col_payroll).value) or 0.0,
            "totalElectricityCostRs": _num(ws.cell(row=r, column=col_elec_cost).value) or 0.0,
        }
    return results


def _parse_support_department_sheet(ws) -> dict:
    """Returns {"totalPayroll", "totalElectricityCostRs"} summed across
    every row of the "Support Department" sheet: 6 named departments
    (Factory Admin & HR, Maintenance, FG Store, Quality Assurance, RM
    Store, Tech. Store) at rows 4-9, plus one shared-equipment
    electricity-only line ("Compressor/Cargo Lift/nitrogen" -- no payroll
    of its own, its label sits under the "Labor Cost/Kg" header by
    coincidence of the sheet's layout) at row 10, stopping at the sheet's
    own "Total" marker row. Verified this reproduces that row's own
    pre-computed totals exactly, for both payroll and electricity, across
    all 9 months checked (Jan-26 through Sep-26) -- located by header
    text and a name/label check per row, not hardcoded row numbers, so a
    department added or removed later still sums correctly.

    This is the whole-of-Shahi-3 "overhead" pool used by
    compute_shahi3_manufacturing_overhead -- support staff and shared
    utilities that serve the whole factory, not attributable to Packing
    or Production individually at the source."""
    header_rows = range(1, 4)
    _, col_elec_cost = _find_header_cell(ws, "Total Electricity Cost", header_rows)
    if col_elec_cost is None:
        return {"totalPayroll": None, "totalElectricityCostRs": None}

    total_payroll = 0.0
    total_elec = 0.0
    for r in range(1, ws.max_row + 1):
        if any(ws.cell(row=r, column=c).value == "Total" for c in range(5, 8)):
            break
        dept_label = ws.cell(row=r, column=1).value
        equip_label = ws.cell(row=r, column=4).value
        elec = _num(ws.cell(row=r, column=col_elec_cost).value) or 0.0
        if isinstance(dept_label, str) and dept_label.strip():
            total_payroll += _num(ws.cell(row=r, column=2).value) or 0.0
            total_elec += elec
        elif isinstance(equip_label, str) and equip_label.strip():
            # The shared-equipment row's own column-2 cell holds the
            # sheet's running PAYROLL TOTAL (sum of the 6 departments
            # above), not this row's own payroll -- only its electricity
            # figure is real, new data to add.
            total_elec += elec
    return {"totalPayroll": round(total_payroll, 2), "totalElectricityCostRs": round(total_elec, 2)}


def _parse_expense_detail_sheet(ws, month_name: str) -> dict:
    """Returns {"electricityCostRs", "gasCostRs"} from the "Expense Detail
    LHR" sheet's own general-ledger rows -- "FACTORY ELECTRICITY" and
    "FACTORY APPLIANCE GAS CHARGES" -- the facility-WIDE monthly expense
    (raw material/salaries/maintenance/etc. too, all in one P&L-style
    list), not split by department the way Packing/Plants are. This is
    the whole-of-Shahi-3 figure used for the company-level comparison
    against Shahi 1's own facility-wide electricity/gas totals -- more
    complete than summing Packing's + Plants' + Support's own
    Total-Electricity-Cost columns, which would still miss whatever
    electricity this workbook doesn't attribute to any single department.

    The value column is NOT at a fixed position -- it drifts between
    different months' exports (Jan/Feb-26 insert an extra leading GL-code
    column shifting everything right by one; the value sits in column E
    for Jan-Mar-26 but column D from May-26 onward). Located instead by
    finding `month_name` itself (e.g. "January") in the sheet's own
    header row, which also makes this self-correcting against a real
    data error found in the source: April-26's workbook header still
    reads "March" with March's own figures duplicated in it (apparently
    never updated after being copied from March's file) -- searching for
    "April" specifically fails to find that column, so this returns None/
    None for April rather than silently reusing March's numbers."""
    value_col = None
    for r in range(1, 6):
        for c in range(1, 10):
            v = ws.cell(row=r, column=c).value
            if isinstance(v, str) and v.strip().lower() == month_name.lower():
                value_col = c
                break
        if value_col:
            break
    if value_col is None:
        return {"electricityCostRs": None, "gasCostRs": None}

    electricity_rs = None
    gas_rs = None
    for r in range(1, ws.max_row + 1):
        label = ws.cell(row=r, column=1).value
        if not isinstance(label, str):
            continue
        norm = label.upper()
        if "FACTORY ELECTRICITY" in norm:
            electricity_rs = _num(ws.cell(row=r, column=value_col).value)
        elif "FACTORY APPLIANCE GAS CHARGES" in norm:
            gas_rs = _num(ws.cell(row=r, column=value_col).value)
    return {"electricityCostRs": electricity_rs, "gasCostRs": gas_rs}


def _load_all() -> dict:
    global _cache
    if _cache is not None:
        return _cache

    packing: dict[str, dict] = {}   # slug -> month_key -> accumulated absolute figures (only the mapped lines)
    production: dict[str, dict] = {}
    packing_total: dict[str, dict] = {}     # month_key -> TRUE Packing-dept total (every line, mapped or not)
    production_total: dict[str, dict] = {}  # month_key -> TRUE Production-dept total (every line, mapped or not)
    support: dict[str, dict] = {}           # month_key -> {monthLabel, totalPayroll, totalElectricityCostRs}
    facility: dict[str, dict] = {}  # month_key -> {monthLabel, electricityCostRs, gasCostRs}

    if DATA_DIR.exists():
        for path in sorted(DATA_DIR.glob("Dept.Wise Cost Sheet Labor & Energy S3(*).xlsx")):
            if path.name.startswith("~$"):
                continue
            month_info = _month_key_from_filename(path)
            if month_info is None:
                continue
            month_key, month_label = month_info

            wb = openpyxl.load_workbook(path, data_only=True)
            if "Packing" in wb.sheetnames:
                packing_rows = _parse_packing_sheet(wb["Packing"])
                total_bucket = packing_total.setdefault(month_key, {
                    "monthLabel": month_label, "totalPacks": 0.0, "totalWeightTon": 0.0,
                    "totalPayroll": 0.0, "packingContractorPaymentRs": 0.0, "totalElectricityCostRs": 0.0,
                })
                for label, data in packing_rows.items():
                    for key in ("totalPacks", "totalWeightTon", "totalPayroll", "packingContractorPaymentRs", "totalElectricityCostRs"):
                        total_bucket[key] += data[key]
                    slug = PACKING_LABEL_TO_SLUGS.get(label)
                    if slug is None:
                        continue
                    bucket = packing.setdefault(slug, {}).setdefault(month_key, {
                        "monthLabel": month_label, "totalPacks": 0.0, "totalWeightTon": 0.0,
                        "totalPayroll": 0.0, "packingContractorPaymentRs": 0.0, "totalElectricityCostRs": 0.0,
                    })
                    for key in ("totalPacks", "totalWeightTon", "totalPayroll", "packingContractorPaymentRs", "totalElectricityCostRs"):
                        bucket[key] += data[key]

            if "Plants" in wb.sheetnames:
                plant_rows = _parse_plants_sheet(wb["Plants"])
                total_bucket = production_total.setdefault(month_key, {
                    "monthLabel": month_label, "productionKg": 0.0, "totalPayroll": 0.0, "totalElectricityCostRs": 0.0,
                })
                for label, data in plant_rows.items():
                    for key in ("productionKg", "totalPayroll", "totalElectricityCostRs"):
                        total_bucket[key] += data[key]
                    slug = PLANTS_LABEL_TO_SLUG.get(label)
                    if slug is None:
                        continue
                    bucket = production.setdefault(slug, {}).setdefault(month_key, {
                        "monthLabel": month_label, "productionKg": 0.0, "totalPayroll": 0.0, "totalElectricityCostRs": 0.0,
                    })
                    for key in ("productionKg", "totalPayroll", "totalElectricityCostRs"):
                        bucket[key] += data[key]
            if "Support Department" in wb.sheetnames:
                support_data = _parse_support_department_sheet(wb["Support Department"])
                if support_data["totalPayroll"] is not None:
                    support[month_key] = {"monthLabel": month_label, **support_data}
            if "Expense Detail LHR" in wb.sheetnames:
                month_name = MONTH_NAMES[int(month_key[5:7]) - 1]
                expense = _parse_expense_detail_sheet(wb["Expense Detail LHR"], month_name)
                facility[month_key] = {"monthLabel": month_label, **expense}
            wb.close()

    _cache = {
        "packing": packing, "production": production,
        "packing_total": packing_total, "production_total": production_total,
        "support": support, "facility": facility,
    }
    return _cache


def compute_shahi3_cost_summary(slug: str) -> dict | None:
    """Returns {"months": [...]} for a Shahi-3 Packing product (Output in
    Pcs, Labor Cost Rs = Payroll + Packing Contractor Payment summed), or
    None if this slug has no cost data mapped (see
    PACKING_LABEL_TO_SLUGS). Electricity isn't included here -- it's a
    unit-wide figure (see compute_shahi3_facility_cost), not a per-product
    one, same as Shahi 1's own Electricity panel."""
    data = _load_all()["packing"].get(slug)
    if not data:
        return None
    months = []
    for month_key in sorted(data):
        m = data[month_key]
        output = m["totalPacks"]
        if output <= 0:
            continue
        labor_cost = m["totalPayroll"] + m["packingContractorPaymentRs"]
        months.append({
            "month": month_key,
            "monthLabel": m["monthLabel"],
            "output": round(output, 1),
            "outputUnit": "Packets",
            "laborCost": round(labor_cost, 2),
            "costPerThousandUnits": round(labor_cost / output * 1000, 2),
        })
    return {"months": months} if months else None


def compute_shahi3_production_cost_summary(slug: str) -> dict | None:
    """Same shape as compute_shahi3_cost_summary, for a Shahi-3 Production
    product (Output in KG, no per-product gas cost -- see module
    docstring)."""
    data = _load_all()["production"].get(slug)
    if not data:
        return None
    months = []
    for month_key in sorted(data):
        m = data[month_key]
        output = m["productionKg"]
        if output <= 0:
            continue
        months.append({
            "month": month_key,
            "monthLabel": m["monthLabel"],
            "output": round(output, 1),
            "outputUnit": "KG",
            "laborCost": round(m["totalPayroll"], 2),
            "costPerThousandUnits": round(m["totalPayroll"] / output * 1000, 2),
        })
    return {"months": months} if months else None


def compute_shahi3_facility_cost() -> dict | None:
    """Returns {"months": [{"month", "monthLabel", "electricityCostRs",
    "gasCostRs"}]} -- the whole-of-Shahi-3 facility electricity/gas
    expense, month by month, for comparing against Shahi 1's own
    facility-wide totals on the company overview page. None if no
    Expense Detail LHR data has been read at all."""
    facility = _load_all()["facility"]
    if not facility:
        return None
    months = [
        {"month": k, **v}
        for k, v in sorted(facility.items())
        if v.get("electricityCostRs") is not None or v.get("gasCostRs") is not None
    ]
    return {"months": months} if months else None


def compute_shahi3_department_cost(department: str) -> dict | None:
    """Total labor cost + Rs./1,000-units for an entire Shahi-3 department
    ("Packing" or "Production"), summed across every month available --
    same semantics as Shahi 1's
    labor_cost.compute_department_labor_cost(department, product_slugs),
    i.e. this always reads as one genuine combined total (there's no
    separate "contractual-only" figure to keep apart here, unlike Shahi 1
    -- Shahi 3's own Labor Cost/Pack already bundles Permanent + Contractor
    + Packing Contract in one number at the source).

    Reads packing_total/production_total (every line in the Packing/
    Plants sheet, mapped to a registered product or not) rather than
    summing only the per-product `packing`/`production` dicts -- Packing's
    5 cost lines are all mapped to a product so the two would agree
    there, but Production's Plants sheet has 6 lines and only 2
    (H&C-2, Extruder) are mapped to a product; summing only those two
    understated this department's real total by more than half (e.g.
    Aug-26: Rs. 1.27M from the 2 mapped lines vs. the sheet's own true
    Rs. 3.07M total) -- a real bug in an earlier version of this
    function, not a data gap."""
    if department not in ("Packing", "Production"):
        return None
    source = _load_all()["packing_total"] if department == "Packing" else _load_all()["production_total"]
    total_cost = 0.0
    total_output = 0.0
    total_electricity_cost = 0.0
    months_seen: set[str] = set()
    for month_key, m in source.items():
        output = m.get("totalPacks") if department == "Packing" else m.get("productionKg")
        if not output:
            continue
        payroll = m["totalPayroll"] + (m.get("packingContractorPaymentRs", 0.0))
        total_cost += payroll
        total_output += output
        total_electricity_cost += m["totalElectricityCostRs"]
        months_seen.add(month_key)
    if not months_seen or total_output <= 0:
        return None
    return {
        "totalRs": round(total_cost, 2),
        "firstMonth": min(months_seen),
        "lastMonth": max(months_seen),
        "costPerThousandUnits": round(total_cost / total_output * 1000, 2),
        "outputUnit": "Packets" if department == "Packing" else "KG",
        "electricityCostPerUnitRs": round(total_electricity_cost / total_output, 4),
    }


def compute_shahi3_manufacturing_overhead(department: str) -> dict | None:
    """Month by month: this department's own TRUE direct cost (every
    Packing or Production line, see compute_shahi3_department_cost) PLUS
    the whole-of-Shahi-3 Support Department total (Factory Admin & HR,
    Maintenance, FG Store, Quality Assurance, RM Store, Tech. Store,
    shared Compressor/equipment electricity -- see
    _parse_support_department_sheet), divided by this department's own
    output -- "what a unit really costs once overhead is loaded onto
    it," which is what a manufacturing overhead figure means.

    Support's cost is NOT split between Packing and Production -- each
    call independently adds the FULL support total, matching how the
    source workbook's own "Supportive Departments" row on its Summary
    tab is computed too (confirmed: dividing the same support total by
    Packing's own weight-in-KG there reproduces its own "Labor Cost/Kg"
    ratio exactly). That means Packing's and Production's own
    overhead-loaded totals here are each independently meaningful but
    must never be summed together -- doing so would double-count
    Support."""
    if department not in ("Packing", "Production"):
        return None
    data = _load_all()
    dept_source = data["packing_total"] if department == "Packing" else data["production_total"]
    support_source = data["support"]
    output_key = "totalPacks" if department == "Packing" else "productionKg"

    months = []
    for month_key in sorted(set(dept_source) & set(support_source)):
        d = dept_source[month_key]
        s = support_source[month_key]
        output = d.get(output_key)
        if not output:
            continue
        dept_cost = d["totalPayroll"] + d.get("packingContractorPaymentRs", 0.0) + d["totalElectricityCostRs"]
        support_cost = (s["totalPayroll"] or 0.0) + (s["totalElectricityCostRs"] or 0.0)
        total_cost = dept_cost + support_cost
        months.append({
            "month": month_key,
            "monthLabel": d["monthLabel"],
            "output": round(output, 1),
            "outputUnit": "Packets" if department == "Packing" else "KG",
            "departmentCostRs": round(dept_cost, 2),
            "supportCostRs": round(support_cost, 2),
            "totalOverheadCostRs": round(total_cost, 2),
            "costPerThousandUnits": round(total_cost / output * 1000, 2),
        })
    return {"months": months} if months else None
