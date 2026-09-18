// Department-overview landing page: compares every product with data in one
// department (today, only shahi-1-packing has any). Not a full org-chart
// browser yet -- see the NOTE in app.js for where a company/unit/department
// switcher would eventually hook in, once more departments have data.
const Department = (() => {
  const el = (id) => document.getElementById(id);

  async function show(deptSlug) {
    const overview = await Api.getDepartmentOverview(deptSlug);
    renderHeader(overview);
    renderCards(overview);
    renderRankedChart(overview);
    renderDowntimeSmallMultiples(overview);
  }

  function renderHeader(overview) {
    const dept = overview.department;
    el("headerHeading").textContent = "Shahi Enterprises";
    el("headerSubtitle").textContent = `${dept.unit.displayName} › ${dept.displayName}`;
    el("headerRightDynamic").innerHTML = "";

    el("deptHeading").textContent = dept.displayName;
    el("deptSub").textContent = `${overview.products.length} product${overview.products.length === 1 ? "" : "s"} with data in this department`;
  }

  function renderCards(overview) {
    const container = el("productCards");
    container.innerHTML = "";

    overview.products
      .slice()
      .sort((a, b) => b.summary.avgOeePct - a.summary.avgOeePct)
      .forEach((p) => {
        const s = p.summary;
        const tier = Utils.tierFor(s.avgOeePct);
        const card = document.createElement("a");
        card.className = "product-card";
        card.href = `#/product/${p.slug}`;
        card.innerHTML = `
          <div class="product-card-top">
            <h3>${p.displayName}</h3>
            <span class="tier-tag ${tier.cls}">${tier.label}</span>
          </div>
          <div class="product-card-oee">${Utils.pct(s.avgOeePct)}</div>
          <div class="product-card-metrics">
            <div><span>Availability</span><strong>${Utils.pct(s.avgAvailabilityPct)}</strong></div>
            <div><span>Performance</span><strong>${Utils.pct(s.avgPerformancePct)}</strong></div>
            <div><span>Quality</span><strong>${Utils.pct(s.avgQualityPct)}</strong></div>
          </div>
          <div class="product-card-footer">
            <span>${s.daysCount} days measured</span>
            <span>${Utils.formatDateShort(s.dateRange.start)} – ${Utils.formatDateShort(s.dateRange.end)}</span>
          </div>
        `;
        container.appendChild(card);
      });
  }

  function renderRankedChart(overview) {
    const products = overview.products.map((p) => ({
      displayName: p.displayName,
      avgOeePct: p.summary.avgOeePct,
    }));
    Charts.renderRankedOeeChart("rankedOeeChart", products);
  }

  function renderDowntimeSmallMultiples(overview) {
    const container = el("downtimeSmallMultiples");
    container.innerHTML = "";

    overview.products.forEach((p) => {
      const canvasId = `downtimeSmall-${p.slug}`;
      const card = document.createElement("div");
      card.className = "downtime-small-card";
      card.innerHTML = `
        <h3>${p.displayName}</h3>
        <div class="chart-wrap small"><canvas id="${canvasId}"></canvas></div>
        <div class="callout-line" id="${canvasId}-callout"></div>
      `;
      container.appendChild(card);
    });

    // Charts render after a paint so Chart.js measures real (laid-out)
    // canvas dimensions instead of stale ones from the instant the
    // <canvas> elements were injected -- otherwise its auto-sized y-axis
    // label column can come out too narrow and clip the widest label.
    requestAnimationFrame(() => {
      overview.products.forEach((p) => {
        const canvasId = `downtimeSmall-${p.slug}`;
        // Small multiples stay compact -- top 5 causes, not all 12 (the
        // full Pareto is one click away on the product's own dashboard).
        Charts.renderDowntimeChart(canvasId, p.summary.downtimeTotals, 5, true);
        el(`${canvasId}-callout`).innerHTML = Charts.biggestCauseCallout(p.summary.downtimeTotals);
      });
    });
  }

  return { show };
})();
