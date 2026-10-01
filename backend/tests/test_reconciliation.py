from app.labor_cost import compute_output_reconciliation


def _day(date_iso, actual_counter):
    return {"date": date_iso, "actualCounter": actual_counter}


def test_extruder_has_no_reconciliation_line():
    assert compute_output_reconciliation("extruder", []) is None


def test_fryo_january_gap_matches_hand_calculation():
    records = [_day(f"2026-01-{d:02d}", 200000) for d in range(1, 28)]  # 27 * 200000 = 5,400,000
    result = compute_output_reconciliation("fryo", records)
    assert result is not None
    assert result["shared"] is False

    jan = next(m for m in result["months"] if m["month"] == "2026-01")
    assert jan["outputUnit"] == "Packets"
    assert jan["produced"] == 27 * 200000
    assert jan["received"] == 5440392  # Output Input's own Jan-2026 Fry-O figure
    assert jan["gap"] == round(27 * 200000 - 5440392, 1)
    assert jan["gapPct"] == round(jan["gap"] / jan["produced"] * 100, 2)


def test_month_with_no_produced_data_is_skipped():
    """A month can exist in the labor-cost workbook (Received filled in)
    while this dashboard has no OEE records for it at all -- must not show
    up as a phantom 0-produced/100%-gap month."""
    result = compute_output_reconciliation("fryo", [])
    assert result is not None
    assert result["months"] == []


def test_coated_peanut_and_namak_para_share_identical_reconciliation():
    records = [_day(f"2026-01-{d:02d}", 1000) for d in range(1, 28)]
    peanut = compute_output_reconciliation("coated-peanut", records)
    namak = compute_output_reconciliation("namak-para", records)
    assert peanut is not None and namak is not None
    assert peanut["shared"] is True
    assert namak["shared"] is True
    assert peanut["months"] == namak["months"]
