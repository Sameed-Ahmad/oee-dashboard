from app.gas import MMBTU_PRICE_RS, compute_gas_summary


def _day(date_iso, stock_transferred):
    return {"date": date_iso, "stockTransferred": stock_transferred}


def test_compute_gas_summary_unregistered_product_returns_none():
    assert compute_gas_summary("nimco", []) is None


def test_compute_gas_summary_hnc1_delta_and_ratio():
    records = (
        [_day(f"2026-06-{d:02d}", 1000) for d in range(1, 31)]
        + [_day(f"2026-07-{d:02d}", 900) for d in range(1, 32)]
        + [_day(f"2026-08-{d:02d}", 800) for d in range(1, 32)]
    )
    result = compute_gas_summary("hnc-1", records)
    assert result is not None
    assert result["mmbtuPriceRs"] == MMBTU_PRICE_RS
    months = result["months"]
    assert [m["month"] for m in months] == ["2026-06", "2026-07", "2026-08"]

    june = months[0]
    assert june["monthLabel"] == "June 2026"
    assert june["gasConsumed"] == 5327.84  # 31777.44 - 26449.60
    assert june["unitsProduced"] == 30 * 1000
    assert june["outputUnit"] == "KG"
    assert june["gasPerThousandUnits"] == round(5327.84 / 30000 * 1000, 2)
    assert june["gasCostPerUnit"] == round(5327.84 * MMBTU_PRICE_RS / 30000, 4)

    july = months[1]
    assert july["gasConsumed"] == 4792.92  # 36570.36 - 31777.44
    assert july["unitsProduced"] == 31 * 900


def test_compute_gas_summary_pops_output_unit_is_packets():
    result = compute_gas_summary("pops", [])
    assert result is not None
    for m in result["months"]:
        assert m["outputUnit"] == "Packets"


def test_compute_gas_summary_zero_production_month_has_zero_ratio():
    result = compute_gas_summary("pops", [])
    for m in result["months"]:
        assert m["unitsProduced"] == 0
        assert m["gasPerThousandUnits"] == 0.0
        assert m["gasCostPerUnit"] == 0.0
