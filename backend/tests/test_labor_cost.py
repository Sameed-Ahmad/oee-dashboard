from app.labor_cost import compute_department_labor_cost, compute_labor_cost_summary


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


def test_department_labor_cost_folds_in_contractual_cost_when_slugs_given():
    """Passing product_slugs (as the unit-page cards do) must fold the
    per-item contractor bills into totalRs/costPerThousandUnits -- the
    department card is meant to read as one genuine total, unlike
    compute_labor_cost_summary's per-product figures which keep the two
    separate on purpose."""
    packing_only = compute_department_labor_cost("Packing")
    packing_combined = compute_department_labor_cost("Packing", ["fryo", "ishida", "pops", "nimco"])
    assert packing_combined["laborOnlyRs"] == packing_only["totalRs"]
    assert packing_combined["contractualRs"] > 0
    assert packing_combined["totalRs"] == round(packing_combined["laborOnlyRs"] + packing_combined["contractualRs"], 2)
    assert packing_combined["costPerThousandUnits"] > packing_only["costPerThousandUnits"]


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
