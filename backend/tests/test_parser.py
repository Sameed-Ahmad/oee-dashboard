import openpyxl
import pytest

from app.parser import (
    aggregate_day,
    find_downtime_range,
    is_blank_record,
    parse_sheet_name,
    parse_workbook,
    shift_label,
    should_skip_sheet,
    split_shift_code_suffix,
)
from app.products.registry import PRODUCTS, ProductConfig, resolve_excel_path

FRYO_CONFIG = PRODUCTS["fryo"]
POPS_CONFIG = PRODUCTS["pops"]
ISHIDA_CONFIG = PRODUCTS["ishida"]
NIMCO_CONFIG = PRODUCTS["nimco"]
COATED_PEANUT_CONFIG = PRODUCTS["coated-peanut"]
NAMAK_PARA_CONFIG = PRODUCTS["namak-para"]
HNC_1_CONFIG = PRODUCTS["hnc-1"]
HNC_3_CONFIG = PRODUCTS["hnc-3"]
EXTRUDER_CONFIG = PRODUCTS["extruder"]
KUIPER_CONFIG = PRODUCTS["kuiper"]

ALL_DATA_PRODUCTS = [
    FRYO_CONFIG, POPS_CONFIG, ISHIDA_CONFIG, NIMCO_CONFIG,
    COATED_PEANUT_CONFIG, NAMAK_PARA_CONFIG, HNC_1_CONFIG, HNC_3_CONFIG,
    EXTRUDER_CONFIG, KUIPER_CONFIG,
]


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
        ("Link BreakDown Summary Sheet", True),
        ("Blank Sheet(194)", True),
        ("Sheet4", True),
        ("Sheet13", True),
        ("06-08-26", False),
        ("22-08-26D", False),
        ("30-01-26B", False),
        ("16-04-26n", False),
        # Numbered/duplicate-or-parallel-line sheets are NOT skipped at the
        # name level any more -- whether a "(NN)" sheet is a duplicate to
        # discard or a genuine parallel line to keep depends on whether a
        # clean sibling exists for that date, which only parse_workbook's
        # two-pass logic can determine (see test_dedup_* below).
        ("15-06-26 (59)", False),
        ("03-08-26D (58)", False),
        ("26-10-25 (31)", False),
    ],
)
def test_should_skip_sheet(name, expected):
    assert should_skip_sheet(name) is expected


def test_parse_sheet_name():
    assert parse_sheet_name("22-08-26D") == ("2026-08-22", "D")
    assert parse_sheet_name("10-10-25") == ("2025-10-10", "SINGLE")
    assert parse_sheet_name("16-04-26n") == ("2026-04-16", "N")
    assert parse_sheet_name("10-02-2026") == ("2026-02-10", "SINGLE")
    assert parse_sheet_name("30-1-26") == ("2026-01-30", "SINGLE")


def test_shift_label():
    assert shift_label("D") == "Day"
    assert shift_label("N") == "Night"
    assert shift_label("SINGLE") == "Full day"
    assert shift_label("B") == "B"


def test_split_shift_code_suffix():
    assert split_shift_code_suffix("D (56)") == ("D", "56")
    assert split_shift_code_suffix("(62)") == ("SINGLE", "62")
    assert split_shift_code_suffix("(31)") == ("SINGLE", "31")
    assert split_shift_code_suffix("D") == ("D", None)
    assert split_shift_code_suffix("SINGLE") == ("SINGLE", None)


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


def test_ishida_all_zero_shift_kept_visible(ishida_parsed):
    """A clean (unsuffixed) sheet that's genuinely all-zero (e.g. a Night
    shift that never ran) must stay visible in shiftCount/shifts, not be
    silently dropped by blank-filtering -- that only applies to numbered/
    suffixed sheets, where duplication is the actual concern."""
    day = next(r for r in ishida_parsed.records if r["date"] == "2026-09-07")
    assert day["shiftCount"] == 2
    assert {s["shiftCode"] for s in day["shifts"]} == {"D", "N"}


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


def test_fryo_duplicate_sheets_excluded(fryo_parsed):
    """15-06-26 has six leftover edit-history duplicates ("(62)".."(67)")
    alongside the real "15-06-26" sheet. Because a clean sibling exists,
    all six must be treated as duplicates and excluded -- not aggregated
    in, which would inflate the day's numbers well past 100%."""
    record = next(r for r in fryo_parsed.records if r["date"] == "2026-06-15")
    assert record["shiftCount"] == 1
    assert record["oeePct"] <= 150


@pytest.fixture(scope="module")
def hnc1_parsed():
    if not _has_file(HNC_1_CONFIG):
        pytest.skip("HNC 1 workbook not present in backend/data/raw/hnc-1/")
    return parse_workbook(HNC_1_CONFIG)


def test_hnc1_spot_check(hnc1_parsed):
    record = next(r for r in hnc1_parsed.records if r["date"] == "2026-01-01")
    assert record["availMachines"] == 1
    assert record["actMachines"] == 1
    assert record["availabilityPct"] == pytest.approx(69.93, abs=0.01)
    assert record["performancePct"] == pytest.approx(96.24, abs=0.01)
    assert record["qualityPct"] == pytest.approx(99.70, abs=0.01)
    assert record["oeePct"] == pytest.approx(67.10, abs=0.01)
    assert record["actualCounter"] == 4373
    assert record["totalLabor"] == 9


@pytest.fixture(scope="module")
def hnc3_workbook():
    if not _has_file(HNC_3_CONFIG):
        pytest.skip("HNC 3 workbook not present in backend/data/raw/hnc-3/")
    return openpyxl.load_workbook(resolve_excel_path(HNC_3_CONFIG), data_only=True)


def test_hnc3_shifted_header_row(hnc3_workbook):
    """Every HNC 3 sheet has its downtime header at row 6, except '14-01-26'
    -- a one-off copy/paste artifact that shifted it up to row 5. Nothing
    should be hardcoded to row 6."""
    header_row, cols = find_downtime_range(hnc3_workbook["14-01-26"])
    assert header_row == 5
    assert cols is not None


@pytest.fixture(scope="module")
def coated_peanut_parsed():
    if not _has_file(COATED_PEANUT_CONFIG):
        pytest.skip("Coated Peanut workbook not present in backend/data/raw/coated-peanut/")
    return parse_workbook(COATED_PEANUT_CONFIG)


def test_coated_peanut_blank_parallel_line_excluded(coated_peanut_parsed):
    """'26-10-25 (31)' (the inactive "BIJ FRI 5" line) has no clean sibling
    for that date, so it's parsed (not skipped by should_skip_sheet), but
    is_blank_record excludes it from aggregation since it's genuinely
    all-zero -- unlike the Ishida clean-sheet case, this one just contributes
    nothing rather than being kept as reportable zero data, since it's one
    of several candidate lines for that date rather than the sole record."""
    wb = openpyxl.load_workbook(resolve_excel_path(COATED_PEANUT_CONFIG), data_only=True)
    assert "26-10-25 (31)" in wb.sheetnames
    from app.parser import parse_shift_sheet
    record, error = parse_shift_sheet(wb["26-10-25 (31)"], "26-10-25 (31)")
    assert error is None
    assert is_blank_record(record) is True

    # And it must not appear in the parsed day records for that date.
    matching = [r for r in coated_peanut_parsed.records if r["date"] == "2025-10-26"]
    for r in matching:
        assert "26-10-25 (31)" not in r["sheets"]


def _write_synthetic_two_line_workbook(path):
    """Builds a minimal two-sheet workbook mimicking Coated Peanut's layout:
    two same-date sheets, NEITHER of which has a clean (unsuffixed) sibling,
    both genuinely active (non-blank). parse_workbook should combine them
    into a single two-shift day record rather than treating either as a
    duplicate to discard -- the real data doesn't currently have a case
    where both parallel lines are simultaneously active, so this is
    constructed by hand.
    """
    wb = openpyxl.Workbook()
    del wb["Sheet"]

    def fill_sheet(ws, avail_machines, avail_time, avg_speed, ideal_output,
                    act_machines, act_time, actual_output, availability_pct,
                    target_counter, actual_counter, performance_pct,
                    stock_transferred, quality_pct, oee_pct, total_labor,
                    output_per_labor, downtime_j, downtime_k):
        # Downtime header row (row 6): I=start marker, J/K=categories, L=end marker.
        ws.cell(row=6, column=9, value="Total Time in minutes")
        ws.cell(row=6, column=10, value="Startup Loss")
        ws.cell(row=6, column=11, value="Cleaning")
        ws.cell(row=6, column=12, value="Total Down Time in minutes")

        # Summary anchor block at AI(tag)/AJ(label)/AK(value), rows 8-23.
        ws.cell(row=8, column=35, value="Available")
        ws.cell(row=8, column=36, value="Machines")
        values = [avail_machines, avail_time, avg_speed, ideal_output,
                  act_machines, act_time, actual_output, availability_pct,
                  target_counter, actual_counter, performance_pct,
                  stock_transferred, quality_pct, oee_pct, total_labor,
                  output_per_labor]
        for i, v in enumerate(values):
            ws.cell(row=8 + i, column=37, value=v)

        # Total row.
        ws.cell(row=29, column=1, value="Total")
        ws.cell(row=29, column=10, value=downtime_j)
        ws.cell(row=29, column=11, value=downtime_k)

    ws1 = wb.create_sheet("01-02-26 (1)")
    fill_sheet(ws1, 2, 500, 10, 5000, 2, 480, 4800, 88.0, 4800, 4200, 92.0,
               4100, 97.6, 79.0, 8, 512.5, 20, 5)
    ws2 = wb.create_sheet("01-02-26 (2)")
    fill_sheet(ws2, 1, 500, 8, 4000, 1, 470, 3760, 75.0, 3760, 3300, 90.0,
               3200, 97.0, 65.5, 6, 533.3, 15, 10)

    wb.save(path)


def test_dedup_combines_two_active_parallel_lines(tmp_path):
    workbook_dir = tmp_path / "synthetic"
    workbook_dir.mkdir()
    _write_synthetic_two_line_workbook(workbook_dir / "synthetic.xlsx")

    config = ProductConfig(
        slug="synthetic", display_name="Synthetic", department_slug="shahi-1-production",
        excel_dir=workbook_dir,
    )
    result = parse_workbook(config)
    assert result.errors == []
    assert len(result.records) == 1

    day = result.records[0]
    assert day["date"] == "2026-02-01"
    assert day["shiftCount"] == 2
    assert {s["sheet"] for s in day["shifts"]} == {"01-02-26 (1)", "01-02-26 (2)"}
    # Both lines' machines should be summed, not one discarded as a duplicate.
    assert day["actMachines"] == 3


@pytest.mark.skipif(
    not all(_has_file(c) for c in ALL_DATA_PRODUCTS),
    reason="all ten product workbooks must be present in backend/data/raw/",
)
def test_all_ten_workbooks_parse_cleanly():
    for config in ALL_DATA_PRODUCTS:
        result = parse_workbook(config)
        if config.slug == "nimco":
            assert len(result.errors) == 1, f"nimco errors: {result.errors}"
            assert "18-03-25" in result.errors[0] or "197-day gap" in result.errors[0]
        elif config.slug in ("coated-peanut", "namak-para"):
            # Both have a real, expected early-period reporting gap (verified
            # against the source files) -- any other error is unexpected.
            for err in result.errors:
                assert "day gap" in err, f"{config.slug} unexpected error: {err}"
        else:
            assert result.errors == [], f"{config.slug} errors: {result.errors}"
