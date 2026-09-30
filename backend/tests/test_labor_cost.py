from app.labor_cost import compute_labor_cost_summary


def test_extruder_has_no_labor_cost_line():
    assert compute_labor_cost_summary("extruder") is None


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
    assert jan["costPerUnit"] == 0.0575
    assert abs(jan["laborCost"] / jan["output"] - jan["costPerUnit"]) < 0.001


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
    assert jan["costPerUnit"] == round((631425 + 909462) / (8972964 + 3422364), 4)


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
