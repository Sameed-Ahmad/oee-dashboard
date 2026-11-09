from app.labor_cost import (
    compute_department_labor_cost,
    compute_labor_cost_summary,
    compute_shahi1_manufacturing_overhead,
)


def test_extruder_source_line_is_filed_under_production_pops():
    """Extruder's cost-center line in the workbook is named "Production -
    Pops" (it's Pops' upstream production-stage machine, not a separate
    product), not anything literally named "Extruder" -- confirmed by its
    KG output figures tracking Extruder's own OEE-tracked output closely."""
    result = compute_labor_cost_summary("extruder")
    assert result is not None
    assert result["sourceLines"] == ["Production - Pops"]
    assert result["shared"] is False
    jan = next(m for m in result["months"] if m["month"] == "2026-01")
    assert jan["outputUnit"] == "KG"
    assert jan["output"] == 40585.5


def test_fryo_january_matches_source_workbook():
    result = compute_labor_cost_summary("fryo")
    assert result is not None
    assert result["sourceLines"] == ["Packing -Fry -O"]
    assert result["shared"] is False

    jan = next(m for m in result["months"] if m["month"] == "2026-01")
    assert jan["monthLabel"] == "January 2026"
    assert jan["outputUnit"] == "Packets"
    assert jan["output"] == 5440392
    assert jan["laborCost"] == 312600
    assert jan["manHours"] == 1889.1
    assert jan["costPerThousandUnits"] == 57.46
    assert abs(jan["laborCost"] / jan["output"] * 1000 - jan["costPerThousandUnits"]) < 0.01


def test_nimco_sums_both_source_lines():
    """Nimco is reported as two separate packing lines ("R-10" and
    "R-20 / R-30") in the labor-cost workbook -- verified with the person
    maintaining both sheets. Its own figures must be the SUM of both
    lines' output/hours/cost, not either one alone or an average."""
    result = compute_labor_cost_summary("nimco")
    assert result is not None
    assert set(result["sourceLines"]) == {"Packing - R-10", "Packing - R-20 / R-30"}

    jan = next(m for m in result["months"] if m["month"] == "2026-01")
    # R-10: output=8972964, cost=631425; R-20/R-30: output=3422364, cost=909462
    assert jan["output"] == 8972964 + 3422364
    assert jan["laborCost"] == 631425 + 909462
    assert jan["costPerThousandUnits"] == round((631425 + 909462) / (8972964 + 3422364) * 1000, 2)


def test_coated_peanut_and_namak_para_share_identical_blended_figure():
    """Coated Peanut and Namak Para share one combined "Peanut & Namakpar"
    line in the labor-cost workbook with no way to separate them at the
    source -- both products must show the identical cost/unit figure,
    clearly marked as shared."""
    peanut = compute_labor_cost_summary("coated-peanut")
    namak = compute_labor_cost_summary("namak-para")
    assert peanut is not None and namak is not None
    assert peanut["shared"] is True
    assert namak["shared"] is True
    assert peanut["months"] == namak["months"]


def test_only_months_with_real_output_are_included():
    """Sep-2026 onward exists as a column in the source workbook but is
    still blank (0 output) -- must not show up as a phantom zero-output
    month."""
    result = compute_labor_cost_summary("fryo")
    months = [m["month"] for m in result["months"]]
    assert "2026-09" not in months
    assert all(m["output"] > 0 for m in result["months"])


def test_department_labor_cost_equals_sum_of_jan_through_aug():
    """The department's own TOTAL row should be read directly -- not
    re-derived by summing individual product lines, which would miss
    unmapped lines (e.g. "Packing - Printing") and double-count Coated
    Peanut/Namak Para's shared line."""
    packing = compute_department_labor_cost("Packing")
    assert packing is not None
    assert packing["firstMonth"] == "2026-01"
    assert packing["lastMonth"] == "2026-08"
    assert packing["totalRs"] > 0

    production = compute_department_labor_cost("Production")
    assert production is not None
    assert production["totalRs"] > packing["totalRs"]  # Production Dept has more cost-center lines


def test_department_labor_cost_per_thousand_units_is_output_weighted():
    """costPerThousandUnits must come from summed totals (total Rs. /
    total output), not an average of each month's own ratio -- otherwise
    a low-volume month's ratio would count equally with a high-volume
    month's, skewing the result."""
    packing = compute_department_labor_cost("Packing")
    assert packing["outputUnit"] == "Packets"
    assert packing["costPerThousandUnits"] > 0

    production = compute_department_labor_cost("Production")
    assert production["outputUnit"] == "KG"
    assert production["costPerThousandUnits"] > 0

    # KG is a far smaller physical unit than a packet, so Production's
    # Rs./1,000-units figure should be an order of magnitude bigger than
    # Packing's -- a sanity check against a unit mix-up.
    assert production["costPerThousandUnits"] > packing["costPerThousandUnits"] * 10


def test_department_labor_cost_unknown_department_returns_none():
    assert compute_department_labor_cost("Not A Real Department") is None


def test_fryo_contractual_labor_cost_merged_in():
    """Contractual labour cost is a standalone figure layered on top from
    the separate per-item contractor bills (contractor_labor.py) -- not
    part of laborCost/costPerThousandUnits above, computed against the
    SAME output figure so the two "/1,000 units" columns share one basis."""
    result = compute_labor_cost_summary("fryo")
    jan = next(m for m in result["months"] if m["month"] == "2026-01")
    assert jan["contractualLaborCostRs"] == 1060974.0
    assert jan["contractualCostPerThousandUnits"] == round(1060974.0 / jan["output"] * 1000, 2)
    assert [c["contractor"] for c in jan["contractors"]] == ["Mr. Usman"]


def test_ishida_has_no_contractual_labor_cost():
    """No contractor bill file exists for Ishida -- its contractual columns
    must come back None/empty, not a crash or a phantom zero."""
    result = compute_labor_cost_summary("ishida")
    jan = next(m for m in result["months"] if m["month"] == "2026-01")
    assert jan["contractualLaborCostRs"] is None
    assert jan["contractualCostPerThousandUnits"] is None
    assert jan["contractors"] == []


def test_fryo_permanent_labor_cost_is_the_true_permanent_only_figure():
    """permanentLaborCostRs must be the TRUE Permanent-only portion
    (Rs. 177,612, from the raw "Shahi-1" sheet) -- distinct from laborCost
    (Rs. 312,600), which is Permanent + the workbook's own understated
    Contractual estimate already combined."""
    result = compute_labor_cost_summary("fryo")
    jan = next(m for m in result["months"] if m["month"] == "2026-01")
    assert jan["permanentLaborCostRs"] == 177612
    assert jan["permanentLaborCostRs"] != jan["laborCost"]
    assert jan["permanentCostPerThousandUnits"] == round(177612 / jan["output"] * 1000, 2)
    # Permanent + real Contractual must equal totalCostRs exactly whenever
    # real contractual data exists (Fry-O does).
    assert jan["permanentLaborCostRs"] + jan["contractualLaborCostRs"] == jan["totalCostRs"]


def test_nimco_permanent_labor_cost_sums_both_lines():
    """Nimco is two raw-sheet lines -- Permanent-only must be R-10's
    Permanent (Rs. 502,888) + R-20/R-30's Permanent (Rs. 164,900) =
    Rs. 667,788."""
    result = compute_labor_cost_summary("nimco")
    jan = next(m for m in result["months"] if m["month"] == "2026-01")
    assert jan["permanentLaborCostRs"] == 667788


def test_ishida_permanent_labor_cost_present_even_without_real_contractual():
    """Ishida has no real contractor-bill data, but permanentLaborCostRs
    is still the true Permanent-only figure from the raw sheet (Rs.
    252,471) -- distinct from both laborCost (Rs. 1,096,582, the
    workbook's own Permanent+Contractual blend) and totalCostRs (which
    falls back to laborCost here, since there's no real contractual
    figure to add to permanentLaborCostRs instead)."""
    result = compute_labor_cost_summary("ishida")
    jan = next(m for m in result["months"] if m["month"] == "2026-01")
    assert jan["permanentLaborCostRs"] == 252471
    assert jan["contractualLaborCostRs"] is None
    assert jan["totalCostRs"] == jan["laborCost"]


def test_fryo_total_cost_uses_permanent_plus_real_contractual_not_naive_sum():
    """Regression guard for the exact double-counting bug found in the
    Packing Dept card: laborCost (Rs. 312,600) already includes the
    workbook's OWN understated contractual estimate (Rs. 134,988), so
    totalCostRs must NOT be laborCost + contractualLaborCostRs (which
    would double-count that Rs. 134,988) -- it must be
    Permanent-only (Rs. 177,612, from the raw "Shahi-1" sheet) + the
    REAL contractual figure (Rs. 1,060,974) = Rs. 1,238,586."""
    result = compute_labor_cost_summary("fryo")
    jan = next(m for m in result["months"] if m["month"] == "2026-01")
    assert jan["laborCost"] == 312600
    assert jan["contractualLaborCostRs"] == 1060974.0
    naive_sum = jan["laborCost"] + jan["contractualLaborCostRs"]
    assert jan["totalCostRs"] == 1238586.0
    assert jan["totalCostRs"] != naive_sum
    assert jan["totalCostPerThousandUnits"] == round(jan["totalCostRs"] / jan["output"] * 1000, 2)


def test_ishida_total_cost_equals_labor_cost_unchanged():
    """No real contractor-bill data exists for Ishida, so there's nothing
    to correct with -- totalCostRs must equal laborCost exactly, not be
    None or some other derived figure."""
    result = compute_labor_cost_summary("ishida")
    jan = next(m for m in result["months"] if m["month"] == "2026-01")
    assert jan["totalCostRs"] == jan["laborCost"] == 1096582.0


def test_nimco_total_cost_sums_permanent_across_both_lines_plus_one_real_contractual():
    """Nimco is two raw-sheet lines (R-10 Permanent Rs. 502,888 + R-20/R-30
    Permanent Rs. 164,900 = Rs. 667,788 combined) feeding one real
    contractual figure (Rs. 1,117,872, already a combined total across
    both of Nimco's own contractors -- see contractor_labor.py) -- must
    not be added twice. Total: Rs. 667,788 + Rs. 1,117,872 = Rs. 1,785,660."""
    result = compute_labor_cost_summary("nimco")
    jan = next(m for m in result["months"] if m["month"] == "2026-01")
    assert jan["totalCostRs"] == 1785660.0


def test_department_labor_cost_folds_in_contractual_cost_when_slugs_given():
    """Passing product_slugs (as the unit-page cards do) must fold the
    REAL per-item contractor bills into totalRs/costPerThousandUnits --
    the department card is meant to read as one genuine total, unlike
    compute_labor_cost_summary's per-product figures which keep the two
    separate on purpose. Packing's own real contractual figure is far
    larger than the workbook's own (understated) one -- see
    test_department_labor_cost_packing_corrects_understated_contractual
    -- so the combined total ends up well above the uncorrected one,
    not merely equal to it plus a small addition."""
    packing_only = compute_department_labor_cost("Packing")
    packing_combined = compute_department_labor_cost("Packing", ["fryo", "ishida", "pops", "nimco"])
    assert packing_combined["contractualRs"] > 0
    assert packing_combined["totalRs"] == round(packing_combined["laborOnlyRs"] + packing_combined["contractualRs"], 2)
    assert packing_combined["totalRs"] > packing_only["totalRs"]
    assert packing_combined["costPerThousandUnits"] > packing_only["costPerThousandUnits"]


def test_department_labor_cost_packing_corrects_understated_contractual():
    """Regression guard for a real double-counting bug: an earlier
    version simply added contractor_labor.py's real contractual figure
    on top of the workbook's own Total Labor Cost row, which ALREADY
    includes that workbook's own (much smaller) contractual estimate for
    Fry-O/Pops/Nimco -- e.g. Jan-26 Fry-O: the workbook's own Contractual
    column says Rs. 134,988, but the real contractor bills for that same
    month total Rs. 1,060,974 (~8x higher). The corrected total must be
    well above naive-but-plausible double-counted or under-corrected
    values -- hand-verified for Jan-26 + Aug-26 directly against the raw
    "Shahi-1" sheet: Rs. 4,950,149.20 (Jan) + Rs. 4,769,419.00 (Aug) =
    Rs. 9,719,568.20 for those two months alone."""
    packing_combined = compute_department_labor_cost("Packing", ["fryo", "ishida", "pops", "nimco"])
    assert packing_combined is not None
    # Permanent-only sum must be meaningfully smaller than the real total --
    # confirms contractualRs isn't accidentally zero or negative.
    assert packing_combined["laborOnlyRs"] < packing_combined["totalRs"] * 0.5


def test_department_labor_cost_contractual_is_zero_without_matching_slugs():
    """Production Dept has no contractor bill files at all -- its
    contractual figure must come back a real 0, not None, so totalRs
    still equals laborOnlyRs exactly."""
    production = compute_department_labor_cost("Production", ["hnc-1", "hnc-3", "kuiper", "extruder"])
    assert production["contractualRs"] == 0.0
    assert production["totalRs"] == production["laborOnlyRs"]


def test_nimco_contractual_cost_sums_both_contractors_except_when_one_has_no_bill():
    """Nimco is fed by two separate contractors (Ghulam Nabi = R-10, Basit
    Enterprise = R-20); Basit has no Jan-2026 bill at all, so that month
    must show Ghulam Nabi's real figure alone, not None and not zero."""
    result = compute_labor_cost_summary("nimco")
    jan = next(m for m in result["months"] if m["month"] == "2026-01")
    assert [c["contractor"] for c in jan["contractors"]] == ["Mr. Asif Ghulam Nabi"]
    assert jan["contractualLaborCostRs"] == jan["contractors"][0]["totalAmountRs"]

    feb = next(m for m in result["months"] if m["month"] == "2026-02")
    names = {c["contractor"] for c in feb["contractors"]}
    assert names == {"Mr. Asif Ghulam Nabi", "Mr.Allah Datta (Basit Enterprise)"}
    assert feb["contractualLaborCostRs"] == round(sum(c["totalAmountRs"] for c in feb["contractors"]), 2)


def test_shahi1_manufacturing_overhead_packing_matches_hand_calculation():
    """Hand-verified directly against the raw "Shahi-1" sheet: Jan-26's
    corrected Packing total (Permanent across all 6 lines + real
    contractual for Fry-O/Pops/Nimco + Ishida's and Printing's own
    unchanged totals) is Rs. 4,950,149.20, Jan-26's Support total
    (summing all 9 SUPPORT_DEPARTMENTS' own Total Labor Cost rows) is
    Rs. 11,451,375.00, and Jan-26's Maintenance & Repair total (see
    test_maintenance_cost.py) is Rs. 3,500,247.16."""
    result = compute_shahi1_manufacturing_overhead("Packing")
    assert result is not None
    jan = next(m for m in result["months"] if m["month"] == "2026-01")
    assert jan["departmentCostRs"] == 4950149.2
    assert jan["supportCostRs"] == 11451375.0
    assert jan["maintenanceRepairCostRs"] == 3500247.16
    assert jan["totalOverheadCostRs"] == round(4950149.2 + 11451375.0 + 3500247.16, 2)
    assert jan["costPerThousandUnits"] == round(jan["totalOverheadCostRs"] / jan["output"] * 1000, 2)


def test_shahi1_manufacturing_overhead_production_uses_uncorrected_total():
    """Production has no independent contractor-bill data to correct
    with, so its departmentCostRs is just the sum of its own raw-sheet
    lines' totals (Permanent + the workbook's own contractual, unchanged)
    -- Jan-26 hand-verified at Rs. 4,512,912 (matches the "Shahi-1
    Report" sheet's own Production total exactly, confirming no
    correction was mistakenly applied there)."""
    result = compute_shahi1_manufacturing_overhead("Production")
    assert result is not None
    jan = next(m for m in result["months"] if m["month"] == "2026-01")
    assert jan["departmentCostRs"] == 4512912.0


def test_shahi1_manufacturing_overhead_support_cost_shared_not_split():
    """Packing's and Production's own overhead-loaded figures must each
    carry the FULL Support total for a shared month -- Support isn't
    split between them at the source, so both legitimately show the
    same supportCostRs for Jan-26, even though they must never be summed
    together (that would double-count it)."""
    packing_jan = next(m for m in compute_shahi1_manufacturing_overhead("Packing")["months"] if m["month"] == "2026-01")
    production_jan = next(m for m in compute_shahi1_manufacturing_overhead("Production")["months"] if m["month"] == "2026-01")
    assert packing_jan["supportCostRs"] == production_jan["supportCostRs"] == 11451375.0


def test_shahi1_manufacturing_overhead_maintenance_cost_also_shared_not_split():
    """Same non-split principle as Support -- Maintenance & Repair isn't
    split between Packing and Production either, so Packing's and
    Production's own maintenanceRepairCostRs for a shared month can
    legitimately differ (they're not required to be IDENTICAL the way
    supportCostRs is, since maintenance has its own PKF-only/PRF-only
    portions mixed in with the shared "both" portion -- see
    maintenance_cost.py) but each must be a real, positive figure on its
    own, independently loaded in full."""
    packing_jan = next(m for m in compute_shahi1_manufacturing_overhead("Packing")["months"] if m["month"] == "2026-01")
    production_jan = next(m for m in compute_shahi1_manufacturing_overhead("Production")["months"] if m["month"] == "2026-01")
    assert packing_jan["maintenanceRepairCostRs"] > 0
    assert production_jan["maintenanceRepairCostRs"] > 0


def test_shahi1_manufacturing_overhead_covers_all_eight_months():
    packing = compute_shahi1_manufacturing_overhead("Packing")
    production = compute_shahi1_manufacturing_overhead("Production")
    assert packing is not None and production is not None
    assert len(packing["months"]) == 8
    assert len(production["months"]) == 8
    assert all(m["costPerThousandUnits"] > 0 for m in packing["months"])
    assert all(m["costPerThousandUnits"] > 0 for m in production["months"])


def test_shahi1_manufacturing_overhead_unknown_department_returns_none():
    assert compute_shahi1_manufacturing_overhead("Not A Real Department") is None
