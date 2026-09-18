import pytest

from app.parser import (
    aggregate_day,
    parse_sheet_name,
    parse_workbook,
    shift_label,
    should_skip_sheet,
)
from app.products.registry import PRODUCTS, resolve_excel_path

FRYO_CONFIG = PRODUCTS["fryo"]
POPS_CONFIG = PRODUCTS["pops"]
ISHIDA_CONFIG = PRODUCTS["ishida"]
NIMCO_CONFIG = PRODUCTS["nimco"]

ALL_DATA_PRODUCTS = [FRYO_CONFIG, POPS_CONFIG, ISHIDA_CONFIG, NIMCO_CONFIG]


def _has_file(config) -> bool:
    return resolve_excel_path(config) is not None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Summary Break Time Oct-25", True),
        ("Summary Break Down Feb26", True),
        ("Summary Break Time Aprl-26", True),
        ("Link", True),
        ("Link Sheet", True),
        ("15-06-26 (59)", True),
        ("03-08-26D (58)", True),
        ("Blank Sheet(194)", True),
        ("06-08-26", False),
        ("22-08-26D", False),
        ("30-01-26B", False),
        ("16-04-26n", False),
    ],
)
def test_should_skip_sheet(name, expected):
    assert should_skip_sheet(name) is expected


def test_parse_sheet_name():
    assert parse_sheet_name("22-08-26D") == ("2026-08-22", "D")
    assert parse_sheet_name("10-10-25") == ("2025-10-10", "SINGLE")
    assert parse_sheet_name("16-04-26n") == ("2026-04-16", "N")


def test_shift_label():
    assert shift_label("D") == "Day"
    assert shift_label("N") == "Night"
    assert shift_label("SINGLE") == "Full day"
    assert shift_label("B") == "B"


def _synthetic_shift(availability_pct, act_machines, actual_counter, performance_pct,
                      stock_transferred, total_labor, avg_speed=50.0):
    return {
        "sheet": "synthetic",
        "availMachines": act_machines,
        "availTime": 100,
        "avgSpeed": avg_speed,
        "idealTargetOutput": 1000.0,
        "actMachines": act_machines,
        "actTime": 90,
        "actualTargetOutput": 900.0,
        "availabilityPct": availability_pct,
        "targetCounter": 800,
        "actualCounter": actual_counter,
        "performancePct": performance_pct,
        "stockTransferred": stock_transferred,
        "qualityPct": stock_transferred / actual_counter * 100,
        "oeePct": availability_pct * performance_pct * (stock_transferred / actual_counter * 100) / 10000,
        "totalLabor": total_labor,
        "outputPerLabor": stock_transferred / total_labor,
        "downtime": {k: 0.0 for k in [
            "Shift Startup", "Shift End", "Wrapper Changeover", "Product Changeover",
            "KE Breakdown", "Nitrogen/Air Issue", "Electrical Breakdown",
            "Mechanical Breakdown", "Labor Short", "Material Delay",
            "Operator Maintenance", "Cleaning",
        ]},
        "shiftCode": "D",
        "shiftLabel": "Day",
    }


def test_aggregate_day_two_shifts():
    day = _synthetic_shift(availability_pct=80.0, act_machines=10, actual_counter=1000,
                            performance_pct=90.0, stock_transferred=950, total_labor=20)
    night = dict(_synthetic_shift(availability_pct=60.0, act_machines=5, actual_counter=500,
                                   performance_pct=70.0, stock_transferred=400, total_labor=10))
    night["shiftCode"] = "N"
    night["shiftLabel"] = "Night"

    result = aggregate_day("2026-01-01", [day, night])

    # Availability: (80*10 + 60*5) / (10+5) = 1100/15
    expected_availability = (80.0 * 10 + 60.0 * 5) / 15
    assert result["availabilityPct"] == pytest.approx(expected_availability, abs=0.005)

    # Quality: sum(stockTransferred)/sum(actualCounter)*100 = 1350/1500*100 = 90.0
    expected_quality = (950 + 400) / (1000 + 500) * 100
    assert result["qualityPct"] == pytest.approx(expected_quality, abs=0.005)

    # Output/Labor: sum(stockTransferred)/sum(totalLabor) = 1350/30 = 45.0
    expected_output_per_labor = (950 + 400) / (20 + 10)
    assert result["outputPerLabor"] == pytest.approx(expected_output_per_labor, abs=0.05)

    # Performance: actualCounter-weighted average = (90*1000 + 70*500)/1500
    expected_performance = (90.0 * 1000 + 70.0 * 500) / 1500
    assert result["performancePct"] == pytest.approx(expected_performance, abs=0.005)

    # OEE derived from the day-level availability/performance/quality
    expected_oee = expected_availability * expected_performance * expected_quality / 10000
    assert result["oeePct"] == pytest.approx(expected_oee, abs=0.01)

    assert result["shiftCount"] == 2
    assert len(result["shifts"]) == 2


@pytest.fixture(scope="module")
def ishida_parsed():
    if not _has_file(ISHIDA_CONFIG):
        pytest.skip("Ishida workbook not present in backend/data/raw/ishida/")
    return parse_workbook(ISHIDA_CONFIG)


def test_ishida_single_shift_spot_check(ishida_parsed):
    day = next(r for r in ishida_parsed.records if r["date"] == "2025-10-01")
    shift = next(s for s in day["shifts"] if s["sheet"] == "01-10-25D")
    assert shift["availMachines"] == 3
    assert shift["actMachines"] == 2
    assert shift["availabilityPct"] == pytest.approx(30.83, abs=0.01)
    assert shift["performancePct"] == pytest.approx(99.45, abs=0.01)
    assert shift["qualityPct"] == pytest.approx(97.29, abs=0.01)
    assert shift["oeePct"] == pytest.approx(29.83, abs=0.01)
    assert shift["actualCounter"] == 14160
    assert shift["totalLabor"] == 21


@pytest.fixture(scope="module")
def fryo_parsed():
    if not _has_file(FRYO_CONFIG):
        pytest.skip("Fry-O workbook not present in backend/data/raw/fryo/")
    return parse_workbook(FRYO_CONFIG)


def test_fryo_no_double_counting(fryo_parsed):
    assert len(fryo_parsed.records) >= 200
    assert all(r["shiftCount"] == 1 for r in fryo_parsed.records)

    dates_seen = set()
    for record in fryo_parsed.records:
        assert record["date"] not in dates_seen
        dates_seen.add(record["date"])


def test_fryo_spot_check(fryo_parsed):
    record = next(r for r in fryo_parsed.records if r["date"] == "2026-08-06")
    assert record["availMachines"] == 18
    assert record["actMachines"] == 15
    assert record["availabilityPct"] == pytest.approx(81.25, abs=0.01)
    assert record["performancePct"] == pytest.approx(96.09, abs=0.01)
    assert record["qualityPct"] == 100
    assert record["oeePct"] == pytest.approx(78.07, abs=0.01)
    assert record["actualCounter"] == 232272


@pytest.mark.skipif(
    not all(_has_file(c) for c in ALL_DATA_PRODUCTS),
    reason="all four product workbooks must be present in backend/data/raw/",
)
def test_all_four_workbooks_parse_cleanly():
    for config in ALL_DATA_PRODUCTS:
        result = parse_workbook(config)
        if config.slug == "nimco":
            assert len(result.errors) == 1, f"nimco errors: {result.errors}"
            assert "18-03-25" in result.errors[0] or "197-day gap" in result.errors[0]
        else:
            assert result.errors == [], f"{config.slug} errors: {result.errors}"
