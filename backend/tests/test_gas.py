from app import gas as gas_module
from app.gas import MMBTU_PRICE_RS, compute_department_gas_cost_per_thousand_units, compute_gas_summary


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


def test_compute_gas_summary_extruder_output_unit_is_kg():
    """The gas meter is filed under Extruder (Pops' upstream production
    line), not Pops itself -- see gas.py module docstring. Extruder's own
    output is tracked in KG, like the rest of Production Dept, confirmed
    against its labor-cost workbook line (see labor_cost.py)."""
    result = compute_gas_summary("extruder", [])
    assert result is not None
    for m in result["months"]:
        assert m["outputUnit"] == "KG"


def test_compute_gas_summary_zero_production_month_has_zero_ratio():
    result = compute_gas_summary("extruder", [])
    for m in result["months"]:
        assert m["unitsProduced"] == 0
        assert m["gasPerThousandUnits"] == 0.0
        assert m["gasCostPerUnit"] == 0.0


def test_compute_department_gas_cost_per_thousand_units_averages_only_products_with_gas_data():
    records = [_day(f"2026-06-{d:02d}", 1000) for d in range(1, 31)]
    # kuiper/nimco have no gas readings registered at all -- only hnc-1 and
    # hnc-3 should contribute (both KG, so they share one group).
    result = compute_department_gas_cost_per_thousand_units(
        ["hnc-1", "hnc-3", "kuiper", "nimco"], {"hnc-1": records, "hnc-3": records}
    )
    assert len(result) == 1
    group = result[0]
    assert group["outputUnit"] == "KG"
    assert group["products"] == ["hnc-1", "hnc-3"]

    hnc1_only = compute_gas_summary("hnc-1", records)
    hnc3_only = compute_gas_summary("hnc-3", records)
    hnc1_avg = sum(m["gasCostPerUnit"] for m in hnc1_only["months"]) / len(hnc1_only["months"]) * 1000
    hnc3_avg = sum(m["gasCostPerUnit"] for m in hnc3_only["months"]) / len(hnc3_only["months"]) * 1000
    assert group["costPerThousandUnits"] == round((hnc1_avg + hnc3_avg) / 2, 2)


def test_compute_department_gas_cost_per_thousand_units_splits_by_unit_instead_of_blending(monkeypatch):
    """Two gas-tracked products with DIFFERENT output units must not be
    averaged together -- that would blend two different physical
    quantities into one meaningless number. Each unit gets its own group.
    (In today's real data every gas-tracked product happens to be KG, so
    this simulates a mixed-unit case rather than relying on that
    coincidence holding forever.)"""
    monkeypatch.setitem(gas_module.PRODUCT_OUTPUT_UNIT, "extruder", "Packets")
    records = [_day(f"2026-06-{d:02d}", 1000) for d in range(1, 31)]
    result = compute_department_gas_cost_per_thousand_units(
        ["hnc-1", "extruder"], {"hnc-1": records, "extruder": records}
    )
    units = {g["outputUnit"]: g for g in result}
    assert set(units) == {"KG", "Packets"}
    assert units["KG"]["products"] == ["hnc-1"]
    assert units["Packets"]["products"] == ["extruder"]


def test_compute_department_gas_cost_per_thousand_units_no_products_have_gas_data_returns_empty_list():
    assert compute_department_gas_cost_per_thousand_units(["fryo", "ishida", "nimco"], {}) == []
