// Department-overview landing page: compares every product with data in one
// department (today, only shahi-1-packing has any). Not a full org-chart
// browser yet -- see the NOTE in app.js for where a company/unit/department
// switcher would eventually hook in, once more departments have data.
const Department = (() => {
  const el = (id) => document.getElementById(id);

  const state = {
    deptSlug: null,
    overview: null,
    selectedProducts: [], // slugs, in click order
    dayRecordsCache: {}, // slug -> day records (fetched lazily, once per page load)
  };

  async function show(deptSlug) {
    const isDeptSwitch = state.deptSlug !== deptSlug;
    state.deptSlug = deptSlug;
    if (isDeptSwitch) {
      state.selectedProducts = [];
      state.dayRecordsCache = {};
    }

    const overview = await Api.getDepartmentOverview(deptSlug);
    state.overview = overview;
    renderHeader(overview);
    renderCards(overview);
    renderRankedChart(overview);
    renderDowntimeSmallMultiples(overview);
    renderCompareSection();
    wireControlsOnce();
  }

  function renderHeader(overview) {
    const dept = overview.department;
    el("headerHeading").textContent = "Shahi Enterprises";
    el("headerSubtitle").textContent = `${dept.unit.displayName} › ${dept.displayName}`;
    el("headerRightDynamic").innerHTML = "";

    el("backToUnitLink").href = `#/unit/${dept.unit.slug}`;
    el("backToUnitLink").textContent = `‹ ${dept.unit.displayName}`;

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
        if (state.selectedProducts.includes(p.slug)) card.classList.add("comparing");

        const toggle = document.createElement("label");
        toggle.className = "compare-toggle";
        toggle.innerHTML = `<input type="checkbox" ${state.selectedProducts.includes(p.slug) ? "checked" : ""}> Compare`;
        const checkbox = toggle.querySelector("input");
        // Clicking the checkbox must NOT follow the card's own link --
        // stopPropagation before the click bubbles up to the <a> keeps the
        // browser from navigating while still letting the checkbox toggle.
        toggle.addEventListener("click", (e) => e.stopPropagation());
        checkbox.addEventListener("change", () => toggleCompare(p.slug));
        card.appendChild(toggle);

        container.appendChild(card);
      });
  }

  function toggleCompare(slug) {
    const idx = state.selectedProducts.indexOf(slug);
    if (idx === -1) {
      state.selectedProducts.push(slug);
    } else {
      state.selectedProducts.splice(idx, 1);
    }
    renderCards(state.overview);
    renderCompareSection();
  }

  function renderRankedChart(overview) {
    const products = overview.products.map((p) => ({
      displayName: p.displayName,
      avgOeePct: p.summary.avgOeePct,
    }));
    Charts.renderRankedOeeChart("rankedOeeChart", products);
  }

  function renderDowntimeSmallMultiples(overview) {
    renderDowntimeGrid("downtimeSmallMultiples", "downtimeSmall", overview.products);
  }

  function renderDowntimeGrid(containerId, idPrefix, products) {
    const container = el(containerId);
    container.innerHTML = "";

    products.forEach((p) => {
      const canvasId = `${idPrefix}-${p.slug}`;
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
      products.forEach((p) => {
        const canvasId = `${idPrefix}-${p.slug}`;
        // Small multiples stay compact -- top 5 causes, not all 12 (the
        // full Pareto is one click away on the product's own dashboard).
        Charts.renderDowntimeChart(canvasId, p.summary.downtimeTotals, 5, true);
        el(`${canvasId}-callout`).innerHTML = Charts.biggestCauseCallout(p.summary.downtimeTotals);
      });
    });
  }

  // ---------- Cross-product comparison ----------

  function selectedProductEntries() {
    // Preserve click order (state.selectedProducts), not the overview's own
    // (OEE-ranked) order -- comparisons read more naturally in the order
    // the user picked them.
    return state.selectedProducts
      .map((slug) => state.overview.products.find((p) => p.slug === slug))
      .filter(Boolean);
  }

  function renderCompareSection() {
    const panel = el("comparePanel");
    const entries = selectedProductEntries();
    if (entries.length < 2) {
      panel.style.display = "none";
      return;
    }
    panel.style.display = "";

    el("compareHeading").textContent = `Comparing ${entries.length} products`;

    renderCompareCards(entries);
    Charts.renderComparisonBarChart(
      "compareBarChart",
      entries.map((p) => ({ displayName: p.displayName, ...p.summary })),
    );
    renderDowntimeGrid("compareDowntimeMultiples", "compareDowntime", entries);
    renderCompareTrend(entries);
  }

  function renderCompareCards(entries) {
    const container = el("compareCards");
    container.innerHTML = "";
    entries.forEach((p) => {
      const s = p.summary;
      const card = document.createElement("div");
      card.className = "compare-card";
      card.innerHTML = `
        <h4>${p.displayName}</h4>
        <div class="compare-card-row"><span>OEE</span><strong>${Utils.pct(s.avgOeePct)}</strong></div>
        <div class="compare-card-row"><span>Availability</span><strong>${Utils.pct(s.avgAvailabilityPct)}</strong></div>
        <div class="compare-card-row"><span>Performance</span><strong>${Utils.pct(s.avgPerformancePct)}</strong></div>
        <div class="compare-card-row"><span>Quality</span><strong>${Utils.pct(s.avgQualityPct)}</strong></div>
        <div class="compare-card-row"><span>Days measured</span><strong>${s.daysCount}</strong></div>
      `;
      container.appendChild(card);
    });
  }

  function weekStart(dateStr) {
    const d = new Date(dateStr + "T00:00:00");
    d.setDate(d.getDate() - d.getDay()); // back to the Sunday of this week
    return d.toISOString().slice(0, 10);
  }

  function weeklyOeeFromDayRecords(records) {
    const sums = {};
    const counts = {};
    records.forEach((r) => {
      const wk = weekStart(r.date);
      sums[wk] = (sums[wk] || 0) + r.oeePct;
      counts[wk] = (counts[wk] || 0) + 1;
    });
    return Object.keys(sums)
      .sort()
      .map((wk) => ({ weekStart: wk, avgOeePct: sums[wk] / counts[wk] }));
  }

  async function fetchDayRecords(slug) {
    if (state.dayRecordsCache[slug]) return state.dayRecordsCache[slug];
    const dates = await Api.listDays(slug);
    const records = await Promise.all(dates.map((d) => Api.getDay(slug, d)));
    state.dayRecordsCache[slug] = records;
    return records;
  }

  async function renderCompareTrend(entries) {
    const wrap = el("compareTrendWrap");
    wrap.innerHTML = '<div class="compare-trend-loading">Loading trend data…</div>';

    // Guards against a stale response landing after the user has changed
    // the selection again (e.g. toggled a product off) while this was in
    // flight -- only the MOST RECENT call for this exact set gets to render.
    const requestedSlugs = entries.map((p) => p.slug).join(",");

    const series = await Promise.all(
      entries.map(async (p) => ({
        label: p.displayName,
        weeklyOee: weeklyOeeFromDayRecords(await fetchDayRecords(p.slug)),
      })),
    );

    const stillCurrent = selectedProductEntries().map((p) => p.slug).join(",") === requestedSlugs;
    if (!stillCurrent) return;

    wrap.innerHTML = '<canvas id="compareTrendChart"></canvas>';
    Charts.renderProductComparisonTrendChart("compareTrendChart", series);
  }

  // ---------- Wiring (once per page load, not per department switch) ----------

  let controlsWired = false;

  function wireControlsOnce() {
    if (controlsWired) return;
    controlsWired = true;

    el("compareClearBtn").addEventListener("click", () => {
      state.selectedProducts = [];
      renderCards(state.overview);
      renderCompareSection();
    });
  }

  return { show };
})();
