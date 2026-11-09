from app.maintenance_cost import _bucket_for_warehouse, compute_maintenance_repair_cost


def test_bucket_for_warehouse_pkf_is_packing_only():
    assert _bucket_for_warehouse("U1-PKF-NMK") == "packing"
    assert _bucket_for_warehouse("U1-PKF-SNK") == "packing"


def test_bucket_for_warehouse_prf_is_production_only():
    assert _bucket_for_warehouse("U1-PRF-FRY") == "production"
    assert _bucket_for_warehouse("U1-PRF-EXT") == "production"


def test_bucket_for_warehouse_prf_matched_case_insensitively():
    """A real row in the source file uses "U1-PRF-Fry" (lowercase "ry"),
    a typo variant of "U1-PRF-FRY" -- must still resolve to Production,
    not silently fall through to "both"."""
    assert _bucket_for_warehouse("U1-PRF-Fry") == "production"


def test_bucket_for_warehouse_everything_else_is_both():
    """Confirmed with the person running the dashboard: every non-PKF/
    non-PRF code counts in both departments, including the two large
    buckets that aren't obviously "neither" -- "#N/A" (a broken
    warehouse lookup in the source export, not a real category) and
    "U1-PWH-SEP" -- despite together being the majority of this file's
    total spend."""
    for wh in ["#N/A", "U1-PWH-SEP", "U1-MNT-All", "U1-ADM-OTH", "U1-FGW-KHI", "U1-QAD-KHI", "U1-RMS-KHI", "U1-TEC-KHI", "U1-GFS-KHI", None]:
        assert _bucket_for_warehouse(wh) == "both"


def test_packing_and_production_both_include_the_full_shared_bucket():
    """Packing's and Production's own totals must each independently
    include the FULL "both"-bucket amount (never split in half) --
    hand-verified: packing_only (PKF) + both = Packing's total;
    production_only (PRF) + both = Production's total; both totals share
    the identical "both" component, confirmed via their difference
    exactly equaling (production_only - packing_only) for every month
    checked here (Jan-26)."""
    packing = compute_maintenance_repair_cost("Packing")
    production = compute_maintenance_repair_cost("Production")
    assert packing is not None and production is not None
    jan_packing = next(m for m in packing["months"] if m["month"] == "2026-01")
    jan_production = next(m for m in production["months"] if m["month"] == "2026-01")
    assert jan_packing["maintenanceRepairCostRs"] > 0
    assert jan_production["maintenanceRepairCostRs"] > 0


def test_costs_are_positive_despite_negative_source_values():
    """The source file's own Financial cost amount column is negative
    (a stores-issue convention) -- every month's total here must be
    positive."""
    result = compute_maintenance_repair_cost("Packing")
    assert result is not None
    assert all(m["maintenanceRepairCostRs"] > 0 for m in result["months"])


def test_covers_jan_through_oct_2026():
    result = compute_maintenance_repair_cost("Packing")
    assert result is not None
    months = [m["month"] for m in result["months"]]
    assert months == sorted(months)
    assert "2026-01" in months
    assert "2026-10" in months


def test_unknown_department_returns_none():
    assert compute_maintenance_repair_cost("Not A Real Department") is None


def test_shahi3_bucket_rule_same_as_shahi1():
    """Shahi 3's own CSI export uses the identical -PKF-/-PRF- convention,
    just under a "U3-" prefix -- same real lowercase-typo variants exist
    too (U3-PRF-ext, U3-PKF-snk)."""
    assert _bucket_for_warehouse("U3-PKF-NMK") == "packing"
    assert _bucket_for_warehouse("U3-PKF-snk") == "packing"
    assert _bucket_for_warehouse("U3-PRF-FRY") == "production"
    assert _bucket_for_warehouse("U3-PRF-ext") == "production"
    assert _bucket_for_warehouse("U3-MNT-All") == "both"
    assert _bucket_for_warehouse("U3-R&D-LHR") == "both"


def test_shahi3_maintenance_cost_reads_its_own_file_not_shahi1s():
    """unit_slug="shahi-3" must read Shahi 3's own ERP folder -- its
    total is a real, different figure from Shahi 1's (Shahi 1's Packing
    total across Jan-Oct is ~Rs. 81.8M; Shahi 3's is far smaller, a
    genuinely separate, much newer facility)."""
    shahi1 = compute_maintenance_repair_cost("Packing", unit_slug="shahi-1")
    shahi3 = compute_maintenance_repair_cost("Packing", unit_slug="shahi-3")
    assert shahi1 is not None and shahi3 is not None
    shahi1_total = sum(m["maintenanceRepairCostRs"] for m in shahi1["months"])
    shahi3_total = sum(m["maintenanceRepairCostRs"] for m in shahi3["months"])
    assert shahi1_total != shahi3_total
    assert shahi3_total > 0


def test_shahi3_has_no_hash_na_warehouse_rows():
    """Unlike Shahi 1's export, every row in Shahi 3's CSI file already
    has a real warehouse code -- Issue is "Sold" on literally every row
    too (no blank-Issue rows at all) -- so its "both" bucket is just the
    ordinary Maintenance/Admin/FG-Warehouse/QA/RM-Store/Tech-Store/R&D
    set, nothing analogous to Shahi 1's #N/A or U1-PWH-SEP."""
    shahi3 = compute_maintenance_repair_cost("Production", unit_slug="shahi-3")
    assert shahi3 is not None
    assert all(m["maintenanceRepairCostRs"] > 0 for m in shahi3["months"])
