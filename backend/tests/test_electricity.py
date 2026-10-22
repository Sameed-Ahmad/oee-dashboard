from app.electricity import _num, compute_electricity_summary, compute_gas_lpg_summary


def test_num_passes_through_numeric_values():
    assert _num(85075.71) == 85075.71
    assert _num(0) == 0.0


def test_num_non_numeric_returns_none():
    """openpyxl hands back native types for real cells, and a handful of
    cells on these sheets use non-numeric placeholders ("Closed", "-")
    for a month that isn't filled in yet -- both must come back None,
    never raise."""
    assert _num(None) is None
    assert _num("Closed") is None
    assert _num("-") is None


def test_compute_electricity_summary_january_matches_hand_calculation():
    """Hand-verified against the source workbook's own January row:
    Shahi-1's "Including Compressor" units (85,075.71) x that month's
    blended "Average unit cost Including Solar" (44.38) -- both read
    directly off the sheet, not re-derived here."""
    result = compute_electricity_summary()
    assert result is not None
    jan = next(m for m in result["months"] if m["month"] == "2026-01")
    assert jan["monthLabel"] == "January 2026"
    assert jan["unitsConsumed"] == 85075.71
    # 85075.71000000002 x 44.38467892700317 (both the sheet's true
    # unrounded values), rounded only at the very end -- NOT
    # round(85075.71, 2) x round(44.38..., 2), which would be a
    # less-accurate double-rounding.
    assert jan["costRs"] == round(85075.71000000002 * 44.38467892700317, 2)
    assert jan["sharePct"] == 73.98
    assert jan["facilityTotalUnits"] == 115005.0
    assert jan["facilityTotalCostRs"] == 5104460.0
    assert jan["facilityAvgUnitCost"] == 44.38


def test_compute_electricity_summary_january_source_breakdown():
    """Hand-verified against the source workbook's own January row, one
    block per source. Solar has no bill/unit-cost columns in the sheet
    (it's free/self-generated), so those are None."""
    result = compute_electricity_summary()
    sources = {s["name"]: s for s in result["months"][0]["sources"]}
    assert set(sources) == {"Gas Generator", "Diesel Generator", "K-Electric", "Solar"}

    gas = sources["Gas Generator"]
    assert gas["units"] == 5705.0
    assert gas["billRs"] == 467088.0
    assert gas["unitCost"] == 81.87

    ke = sources["K-Electric"]
    assert ke["units"] == 89603.0
    assert ke["billRs"] == 4228572.0
    assert ke["unitCost"] == 47.19

    solar = sources["Solar"]
    assert solar["units"] == 15588.0
    assert solar["billRs"] is None
    assert solar["unitCost"] is None


def test_compute_electricity_summary_handles_non_numeric_placeholder_cell():
    """April's Gas Generator Unit Cost cell is literally "-" (blank
    placeholder, since Units is 0 that month) -- must parse as None
    rather than crashing or silently becoming 0."""
    result = compute_electricity_summary()
    april = next(m for m in result["months"] if m["month"] == "2026-04")
    gas = next(s for s in april["sources"] if s["name"] == "Gas Generator")
    assert gas["units"] == 0.0
    assert gas["unitCost"] is None
    assert gas["billRs"] == 43841.0


def test_compute_electricity_summary_only_filled_in_months_included():
    """October onward exists as a row in the source sheet but is still
    blank -- must not show up as a phantom zero-cost month, and the
    sheet's own "Total" row (not a real month) must never be mistaken
    for one."""
    result = compute_electricity_summary()
    months = [m["month"] for m in result["months"]]
    assert "2026-10" not in months
    assert months == sorted(months)


def test_compute_electricity_summary_months_are_internally_consistent():
    """Every included month must have a positive units/cost figure --
    guards against a parsing regression silently producing zeros."""
    result = compute_electricity_summary()
    for m in result["months"]:
        assert m["unitsConsumed"] > 0
        assert m["costRs"] > 0


def test_compute_gas_lpg_summary_january_matches_hand_calculation():
    """Hand-verified against the source workbook's "Gas Consumption-26"
    sheet, January row: "Shahi -1 Production" gas (27,147 m3, Rs.
    2,576,175) and the "Shahi" sub-column of "Total LPG" (1,310 KG, Rs.
    288,200) -- NOT the sheet's "Power Generation" gas column, which is
    the same expense already counted under Electricity's Gas Generator
    (confirmed by an identical Bill Amount, Rs. 467,088, in both)."""
    result = compute_gas_lpg_summary()
    assert result is not None
    jan = next(m for m in result["months"] if m["month"] == "2026-01")
    assert jan["monthLabel"] == "January 2026"
    assert jan["gasM3"] == 27147.0
    assert jan["gasCostRs"] == 2576175.0
    assert jan["gasRatePerM3"] == round(2576175.0 / 27147.0, 2)
    assert jan["lpgKg"] == 1310.0
    assert jan["lpgCostRs"] == 288200.0
    assert jan["lpgRatePerKg"] == round(288200.0 / 1310.0, 2)
    assert jan["totalCostRs"] == 2576175.0 + 288200.0


def test_compute_gas_lpg_summary_does_not_double_count_power_generation_gas():
    """The "Power Generation" gas column shares its Bill Amount with
    Electricity's own Gas Generator figure -- this module must read
    "Shahi -1 Production" instead, not that column, for every included
    month (not just January)."""
    result = compute_gas_lpg_summary()
    electricity = compute_electricity_summary()
    elec_gas_bills = {
        m["month"]: next(s["billRs"] for s in m["sources"] if s["name"] == "Gas Generator")
        for m in electricity["months"]
    }
    for m in result["months"]:
        assert m["gasCostRs"] != elec_gas_bills.get(m["month"])


def test_compute_gas_lpg_summary_only_filled_in_months_included():
    result = compute_gas_lpg_summary()
    months = [m["month"] for m in result["months"]]
    assert "2026-10" not in months
    assert months == sorted(months)
