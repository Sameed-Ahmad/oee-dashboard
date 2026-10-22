// All Chart.js construction/update logic lives here. Each render* function
// destroys its previous instance (if any) before drawing, so it's safe to
// call repeatedly as the user changes selection.
const Charts = (() => {
  const instances = {};

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function destroy(key) {
    if (instances[key]) {
      instances[key].destroy();
      delete instances[key];
    }
  }

  function baseFont() {
    return { family: "Inter, -apple-system, sans-serif", size: 12 };
  }

  const DOWNTIME_LABELS = {
    "Shift Startup": "Shift Startup",
    "Shift End": "Shift End",
    "Wrapper Changeover": "Wrapper Changeover",
    "Product Changeover": "Product Changeover",
    "KE Breakdown": "KE Breakdown",
    "Nitrogen/Air Issue": "Nitrogen/Air Issue",
    "Electrical Breakdown": "Electrical Breakdown",
    "Mechanical Breakdown": "Mechanical Breakdown",
    "Labor Short": "Labor Short",
    "Material Delay": "Material Delay",
    "Operator Maintenance": "Operator Maintenance",
    "Cleaning": "Cleaning",
  };

  function sortedDowntimeEntries(downtimeTotals) {
    return Object.entries(downtimeTotals)
      .filter(([, v]) => v > 0)
      .sort((a, b) => b[1] - a[1]);
  }

  // The world-class OEE benchmark used across the app (see the trend
  // chart's own 85% reference line) -- also used to color ranked/comparison
  // bars: green at or above it, red below. The hero tier tag (e.g. "Needs
  // attention") uses its own, separate 3-tier good/ok/bad split -- see
  // Utils.tierFor -- this is just for bars.
  const OEE_BENCHMARK = 85;

  function benchmarkColorVar(value, benchmark = OEE_BENCHMARK) {
    return value >= benchmark ? "--good" : "--bad";
  }

  // One color per product line in the cross-product trend comparison --
  // cycles if more products are selected than colors (rare in practice).
  const COMPARISON_PALETTE = ["--maroon", "--line-avail", "--gold", "--good", "--bad", "--maroon-ink"];

  function renderComparisonBarChart(canvasId, products) {
    destroy(canvasId);
    const ctx = document.getElementById(canvasId).getContext("2d");
    instances[canvasId] = new Chart(ctx, {
      type: "bar",
      data: {
        labels: products.map((p) => p.displayName),
        datasets: [
          { label: "Availability %", data: products.map((p) => p.avgAvailabilityPct), backgroundColor: cssVar("--line-avail"), borderWidth: 0 },
          { label: "Performance %", data: products.map((p) => p.avgPerformancePct), backgroundColor: cssVar("--line-perf"), borderWidth: 0 },
          { label: "Quality %", data: products.map((p) => p.avgQualityPct), backgroundColor: cssVar("--good"), borderWidth: 0 },
          { label: "OEE %", data: products.map((p) => p.avgOeePct), backgroundColor: cssVar("--maroon"), borderWidth: 0 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom", labels: { font: baseFont(), boxWidth: 12 } },
          tooltip: { callbacks: { label: (item) => `${item.dataset.label}: ${item.formattedValue}%` } },
        },
        scales: {
          x: { ticks: { font: baseFont() }, grid: { display: false } },
          y: { min: 0, max: 100, ticks: { font: baseFont(), callback: (v) => v + "%" }, grid: { color: cssVar("--border") } },
        },
      },
    });
  }

  // series: [{ label, weeklyOee: [{weekStart, avgOeePct}, ...] }] -- one
  // line per product, aligned on shared calendar weeks (not each product's
  // own start date) so products with different history lengths/date ranges
  // still compare meaningfully. Weeks a product has no data for are left as
  // a genuine gap (not bridged), since it may not have existed/run yet.
  function renderProductComparisonTrendChart(canvasId, series) {
    destroy(canvasId);
    const allWeeks = Array.from(new Set(series.flatMap((s) => s.weeklyOee.map((w) => w.weekStart)))).sort();
    const datasets = series.map((s, i) => {
      const byWeek = {};
      s.weeklyOee.forEach((w) => { byWeek[w.weekStart] = w.avgOeePct; });
      return {
        label: s.label,
        data: allWeeks.map((wk) => (wk in byWeek ? byWeek[wk] : null)),
        borderColor: cssVar(COMPARISON_PALETTE[i % COMPARISON_PALETTE.length]),
        backgroundColor: "transparent",
        pointRadius: 0,
        borderWidth: 2,
      };
    });

    const ctx = document.getElementById(canvasId).getContext("2d");
    instances[canvasId] = new Chart(ctx, {
      type: "line",
      data: { labels: allWeeks, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { font: baseFont(), boxWidth: 12 } },
          tooltip: {
            callbacks: {
              label: (item) => `${item.dataset.label}: ${item.parsed.y == null ? "no data" : item.parsed.y.toFixed(1) + "%"}`,
            },
          },
        },
        scales: {
          x: { ticks: { font: baseFont(), maxRotation: 0, autoSkip: true, maxTicksLimit: 10 }, grid: { display: false } },
          y: { min: 0, max: 100, ticks: { font: baseFont(), callback: (v) => v + "%" }, grid: { color: cssVar("--border") } },
        },
      },
    });
  }

  function renderRankedOeeChart(canvasId, products) {
    destroy(canvasId);
    const sorted = products.slice().sort((a, b) => b.avgOeePct - a.avgOeePct);
    const ctx = document.getElementById(canvasId).getContext("2d");
    instances[canvasId] = new Chart(ctx, {
      type: "bar",
      data: {
        labels: sorted.map((p) => p.displayName),
        datasets: [{
          data: sorted.map((p) => p.avgOeePct),
          backgroundColor: sorted.map((p) => cssVar(benchmarkColorVar(p.avgOeePct))),
          borderWidth: 0,
          maxBarThickness: 40,
        }],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "nearest", axis: "y", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (item) => `${item.formattedValue}% average OEE`,
            },
          },
        },
        scales: {
          x: {
            min: 0,
            max: 100,
            ticks: { font: baseFont(), callback: (v) => v + "%" },
            grid: { color: cssVar("--border") },
          },
          y: {
            ticks: { font: baseFont() },
            grid: { display: false },
          },
        },
      },
    });
  }

  function renderDowntimeChart(canvasId, downtimeTotals, limit, compact) {
    destroy(canvasId);
    const allEntries = sortedDowntimeEntries(downtimeTotals);
    // % of lost time is always against the TRUE total across every cause,
    // not just whichever top-N are shown (compact small-multiples only
    // plot the top 5) -- same total biggestCauseCallout already uses below
    // the chart, so the two stay consistent with each other.
    const totalMinutes = allEntries.reduce((s, [, v]) => s + v, 0);
    const entries = limit ? allEntries.slice(0, limit) : allEntries;
    const tickFont = compact ? { family: "Inter, -apple-system, sans-serif", size: 10 } : baseFont();
    const ctx = document.getElementById(canvasId).getContext("2d");
    instances[canvasId] = new Chart(ctx, {
      type: "bar",
      data: {
        labels: entries.map(([k]) => DOWNTIME_LABELS[k] || k),
        datasets: [{
          data: entries.map(([, v]) => v),
          backgroundColor: cssVar("--maroon"),
          borderWidth: 0,
          maxBarThickness: compact ? 18 : 22,
        }],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "nearest", axis: "y", intersect: false },
        layout: compact ? { padding: { left: 4 } } : undefined,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (item) => {
                const pct = totalMinutes > 0 ? ((item.parsed.x / totalMinutes) * 100).toFixed(1) : "0";
                return `${item.formattedValue} min (${pct}% of lost time)`;
              },
            },
          },
        },
        scales: {
          x: {
            title: compact ? undefined : { display: true, text: "Minutes", font: baseFont() },
            ticks: { font: tickFont },
            grid: { color: cssVar("--border") },
          },
          y: {
            ticks: { font: tickFont, autoSkip: false },
            grid: { display: false },
            // Chart.js's own auto-sized label column comes out a few px
            // too narrow for some labels (seen clipping "Mechanical
            // Breakdown"'s leading "M" even though it measures narrower
            // than the reserved width) -- pad it out defensively.
            afterFit: (scale) => { scale.width += 14; },
          },
        },
      },
    });
  }

  function biggestCauseCallout(downtimeTotals) {
    const entries = sortedDowntimeEntries(downtimeTotals);
    if (entries.length === 0) return "No downtime recorded.";
    const total = entries.reduce((s, [, v]) => s + v, 0);
    const [label, minutes] = entries[0];
    const share = total > 0 ? ((minutes / total) * 100).toFixed(1) : "0";
    return `Biggest cause: <strong>${DOWNTIME_LABELS[label] || label}</strong> at ${minutes.toFixed(0)} min (${share}% of lost time).`;
  }

  function renderOutputChartDay(canvasId, dayRecord) {
    destroy(canvasId);
    const ctx = document.getElementById(canvasId).getContext("2d");
    instances[canvasId] = new Chart(ctx, {
      type: "bar",
      data: {
        labels: ["Ideal (all machines, full schedule)", "Achievable (actual machines/time)", "Actual produced"],
        datasets: [{
          data: [
            dayRecord.idealTargetOutput,
            dayRecord.actualTargetOutput,
            dayRecord.actualCounter,
          ],
          backgroundColor: [cssVar("--border"), cssVar("--gold"), cssVar("--maroon")],
          borderWidth: 0,
          maxBarThickness: 40,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (item) => `${Math.round(item.parsed.y).toLocaleString()} units`,
            },
          },
        },
        scales: {
          x: { ticks: { font: baseFont() }, grid: { display: false } },
          y: {
            ticks: { font: baseFont(), callback: (v) => v.toLocaleString() },
            grid: { color: cssVar("--border") },
          },
        },
      },
    });
  }

  function weeklyBuckets(records) {
    // Groups records into contiguous 7-day buckets starting from the first record's date.
    const buckets = [];
    for (let i = 0; i < records.length; i += 7) {
      buckets.push(records.slice(i, i + 7));
    }
    return buckets;
  }

  function renderOutputChartOverview(canvasId, allRecords) {
    destroy(canvasId);
    // Short user-picked ranges (e.g. a week) read better as one point per
    // day; long ones (the whole dataset) need weekly buckets to stay
    // legible. Either way, a chart with only 1-2 points needs visible dots
    // -- a bare line with pointRadius 0 has nothing to draw with that few points.
    const buckets = allRecords.length <= 14
      ? allRecords.map((r) => [r])
      : weeklyBuckets(allRecords);
    const labels = buckets.map((b) => b[0].date);
    const ideal = buckets.map((b) => b.reduce((s, r) => s + r.idealTargetOutput, 0));
    const actual = buckets.map((b) => b.reduce((s, r) => s + r.actualCounter, 0));
    const pointRadius = buckets.length <= 2 ? 3 : 0;

    const ctx = document.getElementById(canvasId).getContext("2d");
    instances[canvasId] = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Ideal output",
            data: ideal,
            borderColor: cssVar("--muted"),
            backgroundColor: "transparent",
            borderDash: [4, 4],
            pointRadius,
            borderWidth: 2,
          },
          {
            label: "Actual output",
            data: actual,
            borderColor: cssVar("--maroon"),
            backgroundColor: "transparent",
            pointRadius,
            borderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { font: baseFont(), boxWidth: 12 } },
          tooltip: {
            callbacks: {
              label: (item) => `${item.dataset.label}: ${Math.round(item.parsed.y).toLocaleString()} units`,
            },
          },
        },
        scales: {
          x: {
            ticks: { font: baseFont(), maxRotation: 0, autoSkip: true },
            grid: { display: false },
          },
          y: {
            ticks: { font: baseFont(), callback: (v) => v.toLocaleString() },
            grid: { color: cssVar("--border") },
          },
        },
      },
    });
  }

  // months: [{monthLabel, gasConsumed, unitsProduced, gasPerThousandUnits}]
  // -- bars for gas consumed (left axis), a line for units produced (right
  // axis), so the relationship between the two is readable at a glance
  // even with only a handful of months. pointRadius is always visible
  // (never 0) since a sparse few-month series needs dots to read as a
  // line at all.
  function renderGasVsProductionChart(canvasId, months) {
    destroy(canvasId);
    const outputUnit = months.length ? months[0].outputUnit : "units";
    const unitSingular = outputUnit === "Packets" ? "Packet" : outputUnit;
    const ctx = document.getElementById(canvasId).getContext("2d");
    instances[canvasId] = new Chart(ctx, {
      data: {
        labels: months.map((m) => m.monthLabel),
        datasets: [
          {
            type: "bar",
            label: "Gas consumed (MMBTU)",
            data: months.map((m) => m.gasConsumed),
            backgroundColor: cssVar("--gold"),
            borderWidth: 0,
            yAxisID: "y",
            order: 2,
          },
          {
            type: "line",
            label: `${outputUnit} produced`,
            data: months.map((m) => m.unitsProduced),
            borderColor: cssVar("--maroon"),
            backgroundColor: "transparent",
            pointRadius: 4,
            pointBackgroundColor: cssVar("--maroon"),
            borderWidth: 2,
            yAxisID: "y1",
            order: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { font: baseFont(), boxWidth: 12 } },
          tooltip: {
            callbacks: {
              label: (item) => item.dataset.yAxisID === "y1"
                ? `${item.dataset.label}: ${Math.round(item.parsed.y).toLocaleString()}`
                : `${item.dataset.label}: ${item.parsed.y.toLocaleString()}`,
              afterBody: (items) => {
                const m = months[items[0].dataIndex];
                return [
                  `Gas per 1,000 ${outputUnit.toLowerCase()}: ${m.gasPerThousandUnits.toLocaleString()}`,
                  `Gas cost per ${unitSingular.toLowerCase()}: Rs. ${m.gasCostPerUnit.toLocaleString()}`,
                ];
              },
            },
          },
        },
        scales: {
          x: { ticks: { font: baseFont() }, grid: { display: false } },
          y: {
            position: "left",
            min: 0,
            title: { display: true, text: "Gas consumed (MMBTU)", font: baseFont() },
            ticks: { font: baseFont(), callback: (v) => v.toLocaleString() },
            grid: { color: cssVar("--border") },
          },
          y1: {
            position: "right",
            min: 0,
            title: { display: true, text: `${outputUnit} produced`, font: baseFont() },
            ticks: { font: baseFont(), callback: (v) => v.toLocaleString() },
            grid: { display: false },
          },
        },
      },
    });
  }

  // months: [{monthLabel, costRs, unitsConsumed}] -- same dual-axis
  // bar+line pattern as renderGasVsProductionChart: bars for Cost (Rs.,
  // left axis), a line for Units Consumed (right axis, a differently
  // scaled quantity). Packing/Production Dept output is shown in the
  // table below instead of on this chart -- an indexed single-axis
  // version (all 4 series as % of first month) was tried but was harder
  // to read at a glance than the simple cost/units view, even though it
  // avoided the dual-axis tradeoff.
  function renderElectricityChart(canvasId, months) {
    destroy(canvasId);
    const ctx = document.getElementById(canvasId).getContext("2d");
    instances[canvasId] = new Chart(ctx, {
      data: {
        labels: months.map((m) => m.monthLabel),
        datasets: [
          {
            type: "bar",
            label: "Cost (Rs.)",
            data: months.map((m) => m.costRs),
            backgroundColor: cssVar("--gold"),
            borderWidth: 0,
            yAxisID: "y",
            order: 2,
          },
          {
            type: "line",
            label: "Units consumed",
            data: months.map((m) => m.unitsConsumed),
            borderColor: cssVar("--maroon"),
            backgroundColor: "transparent",
            pointRadius: 4,
            pointBackgroundColor: cssVar("--maroon"),
            borderWidth: 2,
            yAxisID: "y1",
            order: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { font: baseFont(), boxWidth: 12 } },
          tooltip: {
            callbacks: {
              label: (item) => item.dataset.yAxisID === "y1"
                ? `${item.dataset.label}: ${Math.round(item.parsed.y).toLocaleString()}`
                : `${item.dataset.label}: Rs. ${item.parsed.y.toLocaleString()}`,
            },
          },
        },
        scales: {
          x: { ticks: { font: baseFont() }, grid: { display: false } },
          y: {
            position: "left",
            min: 0,
            title: { display: true, text: "Cost (Rs.)", font: baseFont() },
            ticks: { font: baseFont(), callback: (v) => v.toLocaleString() },
            grid: { color: cssVar("--border") },
          },
          y1: {
            position: "right",
            min: 0,
            title: { display: true, text: "Units consumed", font: baseFont() },
            ticks: { font: baseFont(), callback: (v) => v.toLocaleString() },
            grid: { display: false },
          },
        },
      },
    });
  }

  // months: [{monthLabel, gasCostRs, lpgCostRs}] -- Gas and LPG cost both
  // being Rs. figures, they share one axis as two grouped bars -- no
  // dual-axis tradeoff needed here the way Electricity's Cost-vs-Units
  // pairing has one (m3 of gas and KG of LPG aren't shown on this chart
  // at all, only in the table below, to avoid forcing a 3rd/4th scale
  // onto the same axis).
  function renderGasLpgChart(canvasId, months) {
    destroy(canvasId);
    const ctx = document.getElementById(canvasId).getContext("2d");
    instances[canvasId] = new Chart(ctx, {
      type: "bar",
      data: {
        labels: months.map((m) => m.monthLabel),
        datasets: [
          {
            label: "Gas cost (Rs.)",
            data: months.map((m) => m.gasCostRs),
            backgroundColor: cssVar("--gold"),
            borderWidth: 0,
          },
          {
            label: "LPG cost (Rs.)",
            data: months.map((m) => m.lpgCostRs),
            backgroundColor: cssVar("--maroon"),
            borderWidth: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { font: baseFont(), boxWidth: 12 } },
          tooltip: {
            callbacks: {
              label: (item) => `${item.dataset.label}: Rs. ${item.parsed.y.toLocaleString()}`,
            },
          },
        },
        scales: {
          x: { ticks: { font: baseFont() }, grid: { display: false } },
          y: {
            min: 0,
            title: { display: true, text: "Cost (Rs.)", font: baseFont() },
            ticks: { font: baseFont(), callback: (v) => v.toLocaleString() },
            grid: { color: cssVar("--border") },
          },
        },
      },
    });
  }

  // months: [{monthLabel, costPerThousandUnits, manHoursPerThousandUnits,
  // outputUnit}] -- same dual-axis bar+line pattern as
  // renderGasVsProductionChart: bars for Cost/1,000 units (the headline
  // "what does it cost to make a batch" figure, left axis), a line for
  // Man-Hours/1,000 units (right axis, a related but differently-scaled
  // quantity -- Rs. vs. hours -- so it needs its own axis, not a shared
  // one). Per-1,000 rather than per-single-unit so the numbers read as
  // ordinary figures instead of small fractions.
  function renderLaborCostChart(canvasId, months) {
    destroy(canvasId);
    const unit = months.length ? months[0].outputUnit : "units";
    const ctx = document.getElementById(canvasId).getContext("2d");
    instances[canvasId] = new Chart(ctx, {
      data: {
        labels: months.map((m) => m.monthLabel),
        datasets: [
          {
            type: "bar",
            label: `Cost per 1,000 ${unit}`,
            data: months.map((m) => m.costPerThousandUnits),
            backgroundColor: cssVar("--gold"),
            borderWidth: 0,
            yAxisID: "y",
            order: 2,
          },
          {
            type: "line",
            label: `Man-hours per 1,000 ${unit}`,
            data: months.map((m) => m.manHoursPerThousandUnits),
            borderColor: cssVar("--maroon"),
            backgroundColor: "transparent",
            pointRadius: 4,
            pointBackgroundColor: cssVar("--maroon"),
            borderWidth: 2,
            yAxisID: "y1",
            order: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { font: baseFont(), boxWidth: 12 } },
          tooltip: {
            callbacks: {
              label: (item) => item.dataset.yAxisID === "y1"
                ? `${item.dataset.label}: ${item.parsed.y.toLocaleString()}`
                : `${item.dataset.label}: Rs. ${item.parsed.y.toLocaleString()}`,
            },
          },
        },
        scales: {
          x: { ticks: { font: baseFont() }, grid: { display: false } },
          y: {
            position: "left",
            min: 0,
            title: { display: true, text: `Cost per 1,000 ${unit} (Rs.)`, font: baseFont() },
            ticks: { font: baseFont(), callback: (v) => v.toLocaleString() },
            grid: { color: cssVar("--border") },
          },
          y1: {
            position: "right",
            min: 0,
            title: { display: true, text: `Man-hours per 1,000 ${unit}`, font: baseFont() },
            ticks: { font: baseFont() },
            grid: { display: false },
          },
        },
      },
    });
  }

  return {
    renderDowntimeChart,
    biggestCauseCallout,
    renderOutputChartDay,
    renderOutputChartOverview,
    renderGasVsProductionChart,
    renderElectricityChart,
    renderGasLpgChart,
    renderLaborCostChart,
    renderRankedOeeChart,
    renderComparisonBarChart,
    renderProductComparisonTrendChart,
    weeklyBuckets,
  };
})();
