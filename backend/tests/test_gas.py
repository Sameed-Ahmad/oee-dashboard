from app.gas import compute_gas_summary


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
    months = compute_gas_summary("hnc-1", records)
    assert months is not None
    assert [m["month"] for m in months] == ["2026-06", "2026-07", "2026-08"]

    june = months[0]
    assert june["monthLabel"] == "June 2026"
    assert june["gasConsumed"] == 5327.84  # 31777.44 - 26449.60
    assert june["unitsProduced"] == 30 * 1000
    assert june["gasPerThousandUnits"] == round(5327.84 / 30000 * 1000, 2)

    july = months[1]
    assert july["gasConsumed"] == 4792.92  # 36570.36 - 31777.44
    assert july["unitsProduced"] == 31 * 900


def test_compute_gas_summary_zero_production_month_has_zero_ratio():
    months = compute_gas_summary("pops", [])
    assert months is not None
    for m in months:
        assert m["unitsProduced"] == 0
        assert m["gasPerThousandUnits"] == 0.0
