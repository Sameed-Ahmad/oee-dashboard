from app.electricity import _num, compute_electricity_summary


def test_num_parses_thousands_separator():
    assert _num("85,075.71") == 85075.71


def test_num_blank_returns_none():
    assert _num("") is None
    assert _num("   ") is None


def test_num_non_numeric_placeholder_returns_none():
    assert _num("Closed") is None


def test_compute_electricity_summary_january_matches_hand_calculation():
    """Hand-verified against the source CSV's own January row: Shahi-1's
    "Including Compressor" units (85,075.71) x that month's blended
    "Average unit cost Including Solar" (44.38) -- both read directly off
    the sheet, not re-derived here."""
    result = compute_electricity_summary()
    assert result is not None
    jan = next(m for m in result["months"] if m["month"] == "2026-01")
    assert jan["monthLabel"] == "January 2026"
    assert jan["unitsConsumed"] == 85075.71
    assert jan["costRs"] == round(85075.71 * 44.38, 2)
    assert jan["sharePct"] == 73.98
    assert jan["facilityTotalUnits"] == 115005.0
    assert jan["facilityTotalCostRs"] == 5104460.0
    assert jan["facilityAvgUnitCost"] == 44.38


def test_compute_electricity_summary_january_source_breakdown():
    """Hand-verified against the source CSV's own January row, one block
    per source. Solar has no bill/unit-cost columns in the sheet (it's
    free/self-generated), so those are None."""
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


def test_compute_electricity_summary_handles_blank_source_cell():
    """April's Gas Generator Units/Unit Cost cells are literally " - "
    (blank placeholder) in the source sheet, while its Bill Amount is
    still filled in -- must parse as None rather than crashing or
    silently becoming 0."""
    result = compute_electricity_summary()
    april = next(m for m in result["months"] if m["month"] == "2026-04")
    gas = next(s for s in april["sources"] if s["name"] == "Gas Generator")
    assert gas["units"] is None
    assert gas["unitCost"] is None
    assert gas["billRs"] == 43841.0


def test_compute_electricity_summary_only_filled_in_months_included():
    """September onward exists as a row in the source sheet but is still
    blank -- must not show up as a phantom zero-cost month."""
    result = compute_electricity_summary()
    months = [m["month"] for m in result["months"]]
    assert "2026-09" not in months
    assert months == sorted(months)


def test_compute_electricity_summary_months_are_internally_consistent():
    """Every included month must have a positive units/cost figure --
    guards against a parsing regression silently producing zeros."""
    result = compute_electricity_summary()
    for m in result["months"]:
        assert m["unitsConsumed"] > 0
        assert m["costRs"] > 0
