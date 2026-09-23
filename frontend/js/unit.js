// Unit-overview landing page: compares departments within one unit (today,
// only Shahi 1's Packing vs Production). This is the default landing page,
// one level above the department-overview page (department.js). Kept light
// on purpose -- just comparison cards + a ranked chart, no small multiples.
const Unit = (() => {
  const el = (id) => document.getElementById(id);

  async function show(unitSlug) {
    const overview = await Api.getUnitOverview(unitSlug);
    renderHeader(overview);
    renderCards(overview);
    renderMonthlyTrendChart(overview);
  }

  function renderHeader(overview) {
    const unit = overview.unit;
    el("headerHeading").textContent = "Shahi Enterprises";
    el("headerSubtitle").textContent = unit.displayName;
    el("headerRightDynamic").innerHTML = "";

    el("unitHeading").textContent = unit.displayName;
    el("unitSub").textContent =
      `${overview.departments.length} department${overview.departments.length === 1 ? "" : "s"} with data in this unit`;
  }

  function renderCards(overview) {
    const container = el("departmentCards");
    container.innerHTML = "";

    overview.departments
      .slice()
      .sort((a, b) => b.summary.avgOeePct - a.summary.avgOeePct)
      .forEach((d) => {
        const s = d.summary;
        const tier = Utils.tierFor(s.avgOeePct);
        const card = document.createElement("a");
        card.className = "product-card";
        card.href = `#/department/${d.slug}`;
        card.innerHTML = `
          <div class="product-card-top">
            <h3>${d.displayName}</h3>
            <span class="tier-tag ${tier.cls}">${tier.label}</span>
          </div>
          <div class="product-card-oee">${Utils.pct(s.avgOeePct)}</div>
          <div class="product-card-metrics">
            <div><span>Availability</span><strong>${Utils.pct(s.avgAvailabilityPct)}</strong></div>
            <div><span>Performance</span><strong>${Utils.pct(s.avgPerformancePct)}</strong></div>
            <div><span>Quality</span><strong>${Utils.pct(s.avgQualityPct)}</strong></div>
          </div>
          <div class="product-card-footer">
            <span>${d.productCount} product${d.productCount === 1 ? "" : "s"}</span>
          </div>
        `;
        container.appendChild(card);
      });
  }

  // Builds the shared-label-axis series shape renderDepartmentTrendChart
  // needs from each department's own sparse point list -- a department
  // missing a given month/year (e.g. it started later) gets a null there
  // rather than a fabricated value, so the line shows a genuine gap.
  function alignedSeries(departments, pointsKey) {
    const labels = Array.from(new Set(departments.flatMap((d) => d[pointsKey].map((p) => p.label)))).sort();
    const series = departments.map((d) => {
      const byLabel = {};
      d[pointsKey].forEach((p) => { byLabel[p.label] = p.avgOeePct; });
      return { label: d.displayName, data: labels.map((l) => (l in byLabel ? byLabel[l] : null)) };
    });
    return { labels, series };
  }

  function renderMonthlyTrendChart(overview) {
    const { labels, series } = alignedSeries(overview.departments, "monthlyOee");
    Charts.renderDepartmentTrendChart("monthlyDeptChart", labels.map(Calendar.monthNameOnly), series);
  }

  return { show };
})();
