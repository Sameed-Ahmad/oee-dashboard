// Small helpers shared between the department-overview page and the
// single-product dashboard page.
const Utils = (() => {
  function formatDateLong(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    return dt.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  }

  function formatDateShort(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    return dt.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  }

  function tierFor(oeePct) {
    if (oeePct >= 90) return { cls: "tier-good", label: "On target" };
    if (oeePct >= 80) return { cls: "tier-ok", label: "Below target" };
    return { cls: "tier-bad", label: "Needs attention" };
  }

  function pct(n) {
    return `${n.toFixed(1)}%`;
  }

  // Availability/Performance/Quality/OEE % should never exceed 100 by
  // definition -- mirrors backend/app/parser.py's _cap100, needed here too
  // since a few client-side computations (combineLineRecords/
  // computeRangeSummary in product.js) recompute Quality %/OEE % from raw
  // summed counters rather than averaging already-capped per-day fields.
  function cap100(n) {
    return Math.min(n, 100);
  }

  return { formatDateLong, formatDateShort, tierFor, pct, cap100 };
})();
