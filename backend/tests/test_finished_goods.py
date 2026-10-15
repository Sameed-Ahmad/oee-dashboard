from app.finished_goods import (
    FLAG_THRESHOLD_PCT,
    _pack_multiplier,
    _product_slug,
    compute_fg_reconciliation,
    compute_received_by_day,
)


def test_pack_multiplier_two_numbers():
    assert _pack_multiplier("FryO-R20-SnS-(12X6)") == 72
    assert _pack_multiplier("PS-R20-CHEESE-(6X6)") == 36
    assert _pack_multiplier("FryO-R20-SnS-(48X1)") == 48


def test_pack_multiplier_three_numbers():
    assert _pack_multiplier("SN-R200-Dahi Phulki-(1X1X36)-BoxPack") == 36


def test_pack_multiplier_missing_pattern_returns_none():
    assert _pack_multiplier("Some Item With No Pack Code") is None


def test_product_slug_ishida_locations_override_brand():
    # SN is otherwise a Nimco brand, but the Ishida/Saminato *location*
    # wins -- confirmed explicitly: whatever runs on these machines
    # counts as Ishida's own received output, regardless of brand.
    assert _product_slug("Ishida 2", "SN-R100-Chewra-(36X1)") == "ishida"
    assert _product_slug("Ishida1", "BB-R20-Dal Moth-(12X6)") == "ishida"
    assert _product_slug("Saminato", "SN-R100-Chewra-(36X1)") == "ishida"
    assert _product_slug("Saminato", "PS-R20-CHEESE-(6X6)") == "ishida"


def test_product_slug_known_locations_match_their_own_brand():
    assert _product_slug("Fry O", "FryO-R20-SnS-(12X6)") == "fryo"
    assert _product_slug("BB-R10", "BB-R10-Dal Chaska-(12X12)") == "nimco"
    assert _product_slug("BB-R20", "BB-R20-Dal Chaska-(12X6)") == "nimco"
    assert _product_slug("Pops", "PS-R20-CHEESE-(6X6)") == "pops"


def test_product_slug_brand_wins_even_at_a_different_named_location():
    """Regression test: a FryO-branded batch logged at the "Pops"
    location (2026-07-21, 3166 units) was wrongly counted as Pops'
    received output before this fix -- a recognized brand prefix always
    wins over a non-Ishida location. Verified against the OEE sheet's own
    Produced figure for that day, which included this batch under
    Fry-O."""
    assert _product_slug("Pops", "FryO-R20-SnS-(12X6)") == "fryo"
    assert _product_slug("Pops", "BB-R20-Dal Chaska-(12X12)") == "nimco"


def test_product_slug_unrecognized_brand_falls_back_to_known_location():
    """Regression test: "DAAL-R10-ACHARI NAMKEEN" doesn't start with any
    recognized brand prefix, despite genuinely being a Nimco-line item
    (confirmed by its own location, BB-R10, and Item Group FG-NIMKO).
    Before this fix, rows like this were silently dropped entirely
    (~245,000 packets across 7 dates) since there was no fallback once
    the brand prefix lookup failed."""
    assert _product_slug("BB-R10", "DAAL-R10-ACHARI NAMKEEN (12X6)") == "nimco"
    assert _product_slug("Fry O", "Unrecognized-Item-(12X6)") == "fryo"
    assert _product_slug("Pops", "Unrecognized-Item-(12X6)") == "pops"


def test_product_slug_unrecognized_brand_and_location_falls_back_to_item_group():
    """Location "01" isn't a tracked OEE machine -- when the brand prefix
    ALSO isn't recognized, fall back to the Item Group column. Item Group
    can only distinguish Nimco from everything else (fryo/pops/ishida
    snacks can all be filed under "FG-SNACKS"), so a FG-SNACKS row that
    reaches this point is left unmapped."""
    assert _product_slug("01", "Unrecognized-Item-(12X6)", "FG-NIMKO") == "nimco"
    assert _product_slug("01", "Unrecognized-Item-(12X6)", "FG-SNACKS") is None
    assert _product_slug("01", "Unrecognized-Item-(12X6)", None) is None


def test_compute_received_by_day_fryo_matches_hand_computed_total():
    """2026-07-31 Fry-O rows (source workbook): FryO-R20-SnS-(12X6) qty
    3274 + FryO-R20-SnS-(48X1) qty 196 -> (12*6)*3274 + (48*1)*196."""
    received = compute_received_by_day("fryo")
    assert received["2026-07-31"] == 72 * 3274 + 48 * 196


def test_compute_received_by_day_fryo_includes_batch_logged_at_pops_location():
    """2026-07-21: FryO-R20-SnS-(12X6) qty 3166 is logged at the "Pops"
    location, and FryO-R20-Spicy-(12X6) qty 51 at "Fry O" -- both are
    Fry-O's own brand and must both count toward Fry-O's received total
    regardless of which location logged them (72*3166 + 72*51 =
    231,624, matching OEE's own Produced figure for that day exactly)."""
    received = compute_received_by_day("fryo")
    assert received["2026-07-21"] == 72 * 3166 + 72 * 51 == 231624


def test_compute_received_by_day_uses_absolute_value_of_negative_quantity():
    """Every row in this export is a negative-quantity "Sold"/"Transfer
    order shipment" row (see module docstring) -- packets must be its
    absolute value, summed across every location that maps to Ishida.
    2026-07-22: SN-R100-Savoury Mix-(36X1) qty -401 at "Ishida 2"
    (36*401) + BB-R50-CHATPATI DAL MOONG (12x12) qty -88 at "Saminato"
    (144*88, Saminato counts as Ishida too)."""
    received = compute_received_by_day("ishida")
    assert received["2026-07-22"] == 36 * 401 + 144 * 88 == 27108


def test_compute_received_by_day_unregistered_product_is_empty():
    assert compute_received_by_day("extruder") == {}


def test_flag_threshold_is_2_percent():
    assert FLAG_THRESHOLD_PCT == 2.0


def test_compute_fg_reconciliation_flags_day_with_no_receipts():
    """2026-08-01 has zero Fry-O receipts in the source workbook -- any
    real production that day should be flagged red (a 100% gap), nested
    under the August month entry."""
    records = [{"date": "2026-08-01", "stockTransferred": 1000}]
    result = compute_fg_reconciliation("fryo", records)
    assert result is not None
    month = result["months"][0]
    assert month["month"] == "2026-08"
    day = month["days"][0]
    assert day["received"] == 0
    assert day["flagged"] is True
    assert day["gapPct"] == 100.0


def test_compute_fg_reconciliation_does_not_flag_matching_day():
    """2026-07-31 Fry-O received exactly matches produced -- no flag, and
    the month total matches the single day exactly."""
    records = [{"date": "2026-07-31", "stockTransferred": 72 * 3274 + 48 * 196}]
    result = compute_fg_reconciliation("fryo", records)
    month = result["months"][0]
    day = month["days"][0]
    assert day["gap"] == 0
    assert day["gapPct"] == 0.0
    assert day["flagged"] is False
    assert month["gap"] == 0
    assert month["gapPct"] == 0.0


def test_compute_fg_reconciliation_flags_shortfall_over_threshold_even_with_nonzero_receipts():
    """A day where Received is well above zero but still falls short of
    Produced by more than FLAG_THRESHOLD_PCT must be flagged -- the rule
    is about the SIZE of the shortfall, not just "nothing came in"."""
    # 2026-07-31 Fry-O received = 245136 (hand-computed fixture, see above).
    under_threshold = compute_fg_reconciliation("fryo", [{"date": "2026-07-31", "stockTransferred": 250000}])
    day = under_threshold["months"][0]["days"][0]
    assert day["received"] == 245136
    assert day["gapPct"] < FLAG_THRESHOLD_PCT
    assert day["flagged"] is False

    over_threshold = compute_fg_reconciliation("fryo", [{"date": "2026-07-31", "stockTransferred": 260000}])
    day2 = over_threshold["months"][0]["days"][0]
    assert day2["gapPct"] > FLAG_THRESHOLD_PCT
    assert day2["flagged"] is True


def test_compute_fg_reconciliation_does_not_flag_received_exceeding_produced():
    """Received coming in ABOVE Produced is not flagged, even by a wide
    margin -- that direction is expected (e.g. a receipt legitimately
    including an earlier day's carryover batch), not the anomaly this
    threshold is meant to catch."""
    # 2026-07-31 Fry-O received = 245136 -- well above a small Produced figure.
    result = compute_fg_reconciliation("fryo", [{"date": "2026-07-31", "stockTransferred": 100000}])
    day = result["months"][0]["days"][0]
    assert day["received"] > day["produced"]
    assert day["flagged"] is False


def test_compute_fg_reconciliation_overall_totals_flag_card_level_shortfall():
    """The top-level produced/received/gap/flagged fields (used to flag a
    product's card on the department overview page) are the sum across
    every month shown, not just the last one, and use the same
    shortfall-only rule as a single day."""
    records = [
        {"date": "2026-07-31", "stockTransferred": 260000},  # shortfall vs. received=245136
        {"date": "2026-08-01", "stockTransferred": 1000},  # another shortfall (zero received)
    ]
    result = compute_fg_reconciliation("fryo", records)
    assert result["produced"] == 261000
    assert result["received"] == 245136
    assert result["gap"] == 261000 - 245136
    assert result["flagged"] is True


def test_compute_fg_reconciliation_overall_totals_not_flagged_when_within_threshold():
    records = [{"date": "2026-07-31", "stockTransferred": 250000}]  # 1.94% shortfall, under threshold
    result = compute_fg_reconciliation("fryo", records)
    assert result["flagged"] is False


def test_compute_fg_reconciliation_flags_month_whose_own_total_exceeds_threshold():
    """A month row on the main table must be flagged (highlighted red) when
    THAT month's own produced/received totals have a shortfall over
    threshold -- this is what drives the red row in the UI's monthly
    table, independent of which individual days inside it are flagged."""
    shortfall_month = compute_fg_reconciliation("fryo", [{"date": "2026-07-31", "stockTransferred": 260000}])
    assert shortfall_month["months"][0]["flagged"] is True

    matching_month = compute_fg_reconciliation("fryo", [{"date": "2026-07-31", "stockTransferred": 250000}])
    assert matching_month["months"][0]["flagged"] is False


def test_compute_fg_reconciliation_rolls_up_multiple_days_into_one_month():
    records = [
        {"date": "2026-07-31", "stockTransferred": 72 * 3274 + 48 * 196},  # received matches exactly
        {"date": "2026-08-01", "stockTransferred": 1000},  # zero received -- flagged
    ]
    result = compute_fg_reconciliation("fryo", records)
    months = {m["month"]: m for m in result["months"]}
    assert set(months) == {"2026-07", "2026-08"}
    assert months["2026-07"]["monthLabel"] == "July 2026"
    assert months["2026-08"]["monthLabel"] == "August 2026"
    assert months["2026-08"]["produced"] == 1000
    assert months["2026-08"]["received"] == 0
    assert len(months["2026-07"]["days"]) == 1
    assert len(months["2026-08"]["days"]) == 1


def test_compute_fg_reconciliation_excludes_days_outside_coverage_window():
    """The finished-goods workbooks only cover Jul-Sep 2026 -- a June day
    has no possible received figure to compare against and must be
    dropped rather than showing as a false 100%-flagged anomaly."""
    records = [{"date": "2026-06-30", "stockTransferred": 500}]
    result = compute_fg_reconciliation("fryo", records)
    assert result["months"] == []


def test_compute_fg_reconciliation_unregistered_product_returns_none():
    assert compute_fg_reconciliation("extruder", [{"date": "2026-07-31", "stockTransferred": 500}]) is None
