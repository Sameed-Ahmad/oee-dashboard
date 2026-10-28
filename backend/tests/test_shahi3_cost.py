from app.shahi3_cost import (
    compute_shahi3_cost_summary,
    compute_shahi3_department_cost,
    compute_shahi3_facility_cost,
    compute_shahi3_manufacturing_overhead,
    compute_shahi3_production_cost_summary,
)


def test_facility_cost_matches_expense_detail_sheet():
    """Hand-verified against the "Expense Detail LHR" sheet's own
    general-ledger rows: "FACTORY ELECTRICITY" (code 515131001) and
    "FACTORY APPLIANCE GAS CHARGES" (code 515131002)."""
    result = compute_shahi3_facility_cost()
    assert result is not None
    aug = next(m for m in result["months"] if m["month"] == "2026-08")
    assert aug["electricityCostRs"] == 2973300
    assert aug["gasCostRs"] == 10043260
    sep = next(m for m in result["months"] if m["month"] == "2026-09")
    assert sep["electricityCostRs"] == 3357111
    assert sep["gasCostRs"] == 9148244


def test_facility_cost_value_column_found_by_month_name_not_fixed_position():
    """Regression guard: the Expense Detail LHR sheet's value column isn't
    at a fixed position -- Jan/Feb-26 insert an extra leading GL-code
    column (shifting the value to column E instead of D), and so does
    Mar-26 for a different reason. Hand-verified against each month's own
    header-row month name and its row for "FACTORY ELECTRICITY"/
    "FACTORY APPLIANCE GAS CHARGES"."""
    result = compute_shahi3_facility_cost()
    assert result is not None
    jan = next(m for m in result["months"] if m["month"] == "2026-01")
    assert jan["electricityCostRs"] == 2232314
    assert jan["gasCostRs"] is not None
    feb = next(m for m in result["months"] if m["month"] == "2026-02")
    assert feb["electricityCostRs"] == 1673782.78
    mar = next(m for m in result["months"] if m["month"] == "2026-03")
    assert mar["electricityCostRs"] == 2094307


def test_facility_cost_excludes_april_due_to_source_data_error():
    """April-26's own Dept.Wise Cost Sheet workbook has its Expense Detail
    LHR header still reading "March" with March's own figures duplicated
    into it (apparently never updated after being copied from March's
    file) -- searching for "April" specifically must fail to find that
    column rather than silently reusing March's numbers under April's
    label."""
    result = compute_shahi3_facility_cost()
    assert result is not None
    months = [m["month"] for m in result["months"]]
    assert "2026-04" not in months
    assert "2026-03" in months and "2026-05" in months


def test_lhr_nimco_1_august_matches_hand_calculation():
    """Hand-verified against the source workbook's "Packing" sheet, "Total
    BB R10 Department" row: Total Packs 14,248,512, Total Payroll
    1,898,694 (no Packing Contractor Payment that month) -- and
    cross-checked against the same file's own "Aug-2026 Summary" tab,
    which independently reports Labor Cost/Pack = 0.13325559890043254
    (x1000 = 133.26, matching exactly). Electricity isn't part of this
    per-product figure -- it's unit-wide, see
    test_facility_cost_matches_expense_detail_sheet."""
    result = compute_shahi3_cost_summary("lhr-nimco-1")
    assert result is not None
    aug = next(m for m in result["months"] if m["month"] == "2026-08")
    assert aug["output"] == 14248512.0
    assert aug["outputUnit"] == "Packets"
    assert aug["laborCost"] == 1898694.0
    assert aug["costPerThousandUnits"] == 133.26


def test_lhr_snacks_sums_fryo_and_pops_lines():
    """LHR Snacks isn't its own line in the source sheet -- confirmed with
    the person running the dashboard that Shahi 3's "Snacks" business
    line is exactly the "Total FryO Department" + "Total Pops Department"
    rows summed (WheatO/Popstar/Tacoz/Thunder Pops under "Pops", Fry O
    itself under "FryO"), the same pattern as Shahi 1's Nimco summing its
    own R-10 + R-20 lines."""
    result = compute_shahi3_cost_summary("lhr-snacks")
    assert result is not None
    aug = next(m for m in result["months"] if m["month"] == "2026-08")
    # FryO: 30,168 packs, $0 payroll that month. Pops: 1,621,692 packs,
    # payroll 62,370 + contractor 410,966.
    assert aug["output"] == 30168.0 + 1621692.0
    assert aug["laborCost"] == 62370.0 + 410966.0


def test_lhr_siminato_matches_ishida_saminato_cross_check():
    """The source workbook itself labels this line "Ishida" on the
    Packing sheet and "Saminato" on the Summary sheet -- confirmed as the
    SAME line via an identical Labor Cost/Pack figure in both tabs
    (0.6752197145468607), not a guess."""
    result = compute_shahi3_cost_summary("lhr-siminato")
    aug = next(m for m in result["months"] if m["month"] == "2026-08")
    assert aug["costPerThousandUnits"] == round(0.6752197145468607 * 1000, 2)


def test_shahi3_production_reads_total_electricity_cost_not_units_consumed():
    """Regression guard: the Plants sheet has a "Total Electricity units
    consumed" column immediately before "Total Electricity Cost" -- an
    earlier version of this module's header search matched the former
    (a unit count in the thousands) instead of the latter (a much larger
    Rs. figure). Checked via compute_shahi3_department_cost, which reads
    the same totalElectricityCostRs this bug would have corrupted."""
    production = compute_shahi3_department_cost("Production")
    assert production is not None
    # August alone: H&C-2's 433,156.80 + Extruder's 81,216.90 = 514,373.70,
    # summed with September's own figures below in totalRs/electricityCostPerUnitRs --
    # the key regression check is simply that this is Rs.-scale, not a raw unit count.
    assert production["electricityCostPerUnitRs"] > 1.0


def test_shahi3_extruder_filed_under_production_pops():
    """By analogy with Shahi 1's own Extruder line being filed as
    "Production - Pops" (Extruder is Pops' upstream production-stage
    machine) -- the same naming convention repeats at Shahi 3. Flagged as
    an inference, not independently confirmed the way the Packing-side
    mappings are."""
    result = compute_shahi3_production_cost_summary("shahi3-extruder")
    assert result is not None
    aug = next(m for m in result["months"] if m["month"] == "2026-08")
    assert aug["output"] == 15096.0
    assert aug["laborCost"] == 367779.0


def test_unmapped_production_departments_return_none():
    """Batch Frying / Mixing / Flavor Grinding / Sorting have no confirmed
    product mapping -- must not silently attach to the wrong slug."""
    for slug in ["shahi3-hnc-1", "shahi3-hnc-3", "shahi3-kuiper", "shahi3-nomak-para"]:
        assert compute_shahi3_production_cost_summary(slug) is None


def test_lhr_nimco_2_has_no_oee_data_but_does_have_cost_data():
    """No raw OEE workbook has been uploaded for Nimco-2 yet, but its
    cost-sheet line (BB R20/B30/SN50) is real and already mapped --
    Jan-26 through Sep-26 now that the full range has been uploaded."""
    result = compute_shahi3_cost_summary("lhr-nimco-2")
    assert result is not None
    assert len(result["months"]) == 9


def test_department_cost_sums_every_mapped_product_all_nine_months():
    packing = compute_shahi3_department_cost("Packing")
    assert packing is not None
    assert packing["firstMonth"] == "2026-01"
    assert packing["lastMonth"] == "2026-09"
    assert packing["outputUnit"] == "Packets"

    production = compute_shahi3_department_cost("Production")
    assert production is not None
    assert production["outputUnit"] == "KG"
    # ALL 6 Plants-sheet lines (Batch Frying, Pops, H&C-2, Mixing, Flavor
    # Grinding, Sorting), not just the 2 mapped to a registered product --
    # see test_department_cost_includes_unmapped_production_lines below.
    assert production["totalRs"] == 25311267.0
    assert production["electricityCostPerUnitRs"] > 0


def test_department_cost_includes_unmapped_production_lines():
    """Regression guard: an earlier version of compute_shahi3_department_cost
    summed only the per-product `production` dict (just the 2 Plants-sheet
    lines mapped to a registered product slug, H&C-2 and Extruder),
    understating Production Dept's real total by more than half -- Aug-26
    alone: Rs. 1,266,284 from the 2 mapped lines vs. the Plants sheet's
    own true "Total" row figure, Rs. 3,068,882 payroll (confirmed via the
    Plants sheet directly). This department total must come from ALL 6
    lines (packing_total/production_total), not the per-product dicts."""
    production = compute_shahi3_department_cost("Production")
    assert production is not None
    assert production["totalRs"] > 20000000.0


def test_manufacturing_overhead_packing_august_matches_hand_calculation():
    """Hand-verified against the Aug-26 workbook directly (via
    _load_all()'s own packing_total/support buckets): Packing's own TRUE
    total (all 5 lines: Rs. 3,717,325 payroll + Rs. 410,966 contractor
    payment + Rs. 699,657.7712 electricity) plus Support Department's
    total (Rs. 4,801,995 payroll + Rs. 1,094,419.56 electricity),
    against Packing's own 21,096,432 total packs that month."""
    result = compute_shahi3_manufacturing_overhead("Packing")
    assert result is not None
    aug = next(m for m in result["months"] if m["month"] == "2026-08")
    assert aug["departmentCostRs"] == round(3717325 + 410966 + 699657.7712, 2)
    assert aug["supportCostRs"] == round(4801995 + 1094419.56, 2)
    assert aug["totalOverheadCostRs"] == round(aug["departmentCostRs"] + aug["supportCostRs"], 2)
    assert aug["costPerThousandUnits"] == round(aug["totalOverheadCostRs"] / 21096432 * 1000, 2)


def test_manufacturing_overhead_production_uses_full_support_total_not_split():
    """Packing's and Production's own overhead-loaded figures must each
    carry the FULL Support Department cost for a shared month -- Support
    isn't split between them at the source, so both legitimately show
    the same supportCostRs for August, even though they must never be
    summed together (that would double-count it)."""
    packing_aug = next(m for m in compute_shahi3_manufacturing_overhead("Packing")["months"] if m["month"] == "2026-08")
    production_aug = next(m for m in compute_shahi3_manufacturing_overhead("Production")["months"] if m["month"] == "2026-08")
    assert packing_aug["supportCostRs"] == production_aug["supportCostRs"] == round(4801995 + 1094419.56, 2)


def test_manufacturing_overhead_covers_all_nine_months():
    packing = compute_shahi3_manufacturing_overhead("Packing")
    production = compute_shahi3_manufacturing_overhead("Production")
    assert packing is not None and production is not None
    assert len(packing["months"]) == 9
    assert len(production["months"]) == 9
    assert all(m["costPerThousandUnits"] > 0 for m in packing["months"])
    assert all(m["costPerThousandUnits"] > 0 for m in production["months"])


def test_manufacturing_overhead_unknown_department_returns_none():
    assert compute_shahi3_manufacturing_overhead("Not A Real Department") is None


def test_unknown_department_returns_none():
    assert compute_shahi3_department_cost("Not A Real Department") is None
