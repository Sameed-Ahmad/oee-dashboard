from datetime import date

import pytest

from app.parser import parse_date_from_sheet_name, parse_workbook, should_skip_sheet
from app.products.registry import PRODUCTS, ProductConfig

FRYO_CONFIG = PRODUCTS["fryo"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Summary Break Time Oct-25", True),
        ("Link", True),
        ("15-06-26 (59)", True),
        ("06-08-26", False),
        ("22-08-26D", False),
    ],
)
def test_should_skip_sheet(name, expected):
    assert should_skip_sheet(name, FRYO_CONFIG) is expected


def test_parse_date_from_sheet_name():
    assert parse_date_from_sheet_name("22-08-26D") == "2026-08-22"


@pytest.fixture(scope="module")
def parsed():
    if not FRYO_CONFIG.resolved_excel_path.exists():
        pytest.skip("Fry-O workbook not present in backend/data/raw/fryo/")
    return parse_workbook(FRYO_CONFIG)


def test_parse_workbook_integration(parsed):
    assert len(parsed.records) >= 200

    dates_seen = set()
    for record in parsed.records:
        assert 0 <= record["oeePct"] <= 150
        # Raises ValueError if not a valid ISO date string.
        date.fromisoformat(record["date"])
        assert record["date"] not in dates_seen
        dates_seen.add(record["date"])


def test_parse_workbook_spot_check(parsed):
    record = next(r for r in parsed.records if r["date"] == "2026-08-06")
    assert record["availMachines"] == 18
    assert record["actMachines"] == 15
    assert record["availabilityPct"] == pytest.approx(81.25, abs=0.01)
    assert record["performancePct"] == pytest.approx(96.09, abs=0.01)
    assert record["qualityPct"] == 100
    assert record["oeePct"] == pytest.approx(78.07, abs=0.01)
    assert record["actualCounter"] == 232272
