from app.contractor_labor import get_contractual_month


def test_fryo_january_matches_hand_calculation():
    """Hand-verified against Usman Packing Contractor Bill New S-1.xlsx's
    two Jan-2026 sheets: "01 To 15-jan-26" Total Payable Rs. 503,754 +
    "16 TO 31-jan-26" Total Payable Rs. 557,220."""
    month = get_contractual_month("fryo", "2026-01")
    assert month is not None
    assert month["costRs"] == 503754.0 + 557220.0
    assert len(month["contractors"]) == 1
    usman = month["contractors"][0]
    assert usman["contractor"] == "Mr. Usman"
    assert usman["totalAmountRs"] == month["costRs"]


def test_item_rows_sum_to_the_sheets_own_total_payable_amount():
    """Every real item row's amountRs must sum to exactly the sheet's own
    "Total Payable" row (Rs. 503,754 for Usman's "01 To 15-jan-26") --
    confirms subtotal rows ("Total 72 Pcs HD", ...) are correctly excluded
    from the per-item list rather than double-counted."""
    month = get_contractual_month("fryo", "2026-01")
    usman = month["contractors"][0]
    assert round(sum(i["amountRs"] for i in usman["items"]), 2) == month["costRs"]
    assert sum(i["quantity"] for i in usman["items"]) == usman["totalQuantity"]


def test_rate_is_derived_when_the_sheets_own_rate_cell_is_blank():
    """Usman's "01 To 15-jan-26" sheet leaves Rate blank on every row after
    the first of a same-rate group (its own merged-cell convention) -- the
    derived rate (amountRs / quantity) must still reproduce the one rate
    the sheet DOES print for that group, Rs. 14/unit."""
    month = get_contractual_month("fryo", "2026-01")
    usman = next(c for c in get_contractual_month("fryo", "2026-01")["contractors"])
    salted = next(i for i in usman["items"] if i["itemName"].startswith("Fry O Salted ( 12 x 6"))
    assert salted["rate"] == 14.0


def test_ishida_has_no_contractor_file():
    assert get_contractual_month("ishida", "2026-01") is None


def test_nimco_contractor_name_stable_across_naming_drift():
    """Ghulam Nabi's own "Contractor Name" cell alternates between "Mr.
    Asif Ghulam Nabi" and "Mr. Ghulam Nabi" across different 15-day
    periods in the same workbook (the same person/company) -- every month
    must use one canonical name, not split into near-duplicate rows."""
    for month_key in ["2026-01", "2026-07", "2026-08"]:
        month = get_contractual_month("nimco", month_key)
        names = [c["contractor"] for c in month["contractors"] if "Ghulam" in c["contractor"]]
        assert names == ["Mr. Asif Ghulam Nabi"]


def test_unknown_month_returns_none():
    assert get_contractual_month("fryo", "2099-01") is None
