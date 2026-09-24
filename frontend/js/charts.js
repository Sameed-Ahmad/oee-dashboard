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

  function avg(nums) {
    return nums.reduce((s, v) => s + v, 0) / nums.length;
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

  function renderTrendChart(canvasId, records, mode) {
    destroy(canvasId);
    let labels, oee, avail, perf;

    // Machine/line-level records never have a real OEE % (Quality % isn't
    // tracked at that granularity -- see MachineDayRecord) -- rather than
    // average nulls into a misleading flat 0% line, drop the OEE dataset
    // entirely when there's nothing real to plot.
    const hasOee = records.length > 0 && records[0].oeePct != null;

    if (mode === "full") {
      const buckets = weeklyBuckets(records);
      labels = buckets.map((b) => b[0].date);
      oee = hasOee ? buckets.map((b) => avg(b.map((r) => r.oeePct))) : [];
      avail = buckets.map((b) => avg(b.map((r) => r.availabilityPct)));
      perf = buckets.map((b) => avg(b.map((r) => r.performancePct)));
    } else {
      labels = records.map((r) => r.date);
      oee = hasOee ? records.map((r) => r.oeePct) : [];
      avail = records.map((r) => r.availabilityPct);
      perf = records.map((r) => r.performancePct);
    }

    const datasets = [];
    if (hasOee) {
      datasets.push({
        label: "OEE %",
        data: oee,
        borderColor: cssVar("--line-oee"),
        backgroundColor: "transparent",
        pointRadius: 0,
        borderWidth: 2,
      });
    }
    datasets.push(
      {
        label: "Availability %",
        data: avail,
        borderColor: cssVar("--line-avail"),
        backgroundColor: "transparent",
        pointRadius: 0,
        borderWidth: 1.5,
      },
      {
        label: "Performance %",
        data: perf,
        borderColor: cssVar("--line-perf"),
        backgroundColor: "transparent",
        pointRadius: 0,
        borderWidth: 1.5,
      },
      {
        label: "World-class benchmark (85%)",
        data: labels.map(() => 85),
        borderColor: cssVar("--muted"),
        backgroundColor: "transparent",
        borderDash: [6, 4],
        pointRadius: 0,
        borderWidth: 1,
      },
    );

    const ctx = document.getElementById(canvasId).getContext("2d");
    instances[canvasId] = new Chart(ctx, {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { font: baseFont(), boxWidth: 12 } },
          tooltip: {
            callbacks: {
              label: (item) => `${item.dataset.label}: ${item.parsed.y.toFixed(1)}%`,
            },
          },
        },
        scales: {
          x: {
            ticks: { font: baseFont(), maxRotation: 0, autoSkip: true, maxTicksLimit: 10 },
            grid: { display: false },
          },
          y: {
            min: 0,
            max: 100,
            ticks: { font: baseFont(), callback: (v) => v + "%" },
            grid: { color: cssVar("--border") },
          },
        },
      },
    });
  }

  // Answers "if we hire more/fewer people, does production actually move?"
  // -- NOT the same question as plotting output against man-hours (headcount
  // x run-time), which was tried first and rejected: a longer shift produces
  // more man-hours AND more output even with the exact same headcount, so
  // that chart mostly showed "longer shifts make more" (run-time, a
  // scheduling/machine factor), swamping any real labor signal.
  //
  // This isolates headcount by normalizing output against run-time: y is
  // OUTPUT RATE (units produced per hour of actual run time), so a longer
  // shift no longer inflates the number, only genuinely producing faster
  // does. x is headcount (totalLabor) alone. Days are sorted by headcount
  // and grouped into ~10 equal-sized buckets (fewer if there isn't much
  // data) for the same reason as before -- individual days are too noisy to
  // read as a line -- each point is a bucket's own average headcount/rate.
  //
  // How to read it: if the rate stays roughly flat across headcount levels
  // (even the leanest-staffed days), the line is already running near its
  // rated machine speed regardless of staffing -- labor isn't the
  // bottleneck, and hiring more probably won't move output much. If the
  // rate climbs as headcount rises, understaffing is capping the line below
  // its rated speed, and adding people would plausibly help. This is still
  // observational, not a controlled experiment -- e.g. more staff might get
  // assigned specifically on days higher output is already planned -- so
  // it's a directional read, not a guarantee.
  function renderOutputRateVsLaborChart(canvasId, records) {
    destroy(canvasId);
    const points = records
      .map((r) => ({ labor: r.totalLabor, rate: r.actualCounter / (r.actTime / 60) }))
      .filter((p) => p.labor > 0 && Number.isFinite(p.rate))
      .sort((a, b) => a.labor - b.labor);

    const numBins = Math.max(1, Math.min(10, Math.floor(points.length / 3)));
    const binSize = Math.ceil(points.length / numBins) || 1;
    const bucketed = [];
    for (let i = 0; i < points.length; i += binSize) {
      const slice = points.slice(i, i + binSize);
      bucketed.push({
        x: slice.reduce((s, p) => s + p.labor, 0) / slice.length,
        y: slice.reduce((s, p) => s + p.rate, 0) / slice.length,
      });
    }

    const ctx = document.getElementById(canvasId).getContext("2d");
    instances[canvasId] = new Chart(ctx, {
      type: "line",
      data: {
        datasets: [{
          label: "Output rate",
          data: bucketed,
          borderColor: cssVar("--maroon"),
          backgroundColor: "transparent",
          pointRadius: 3,
          pointBackgroundColor: cssVar("--maroon"),
          borderWidth: 2,
          tension: 0.15,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "nearest", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (item) => `${Math.round(item.parsed.y).toLocaleString()} units/hour at ~${Math.round(item.parsed.x).toLocaleString()} workers`,
            },
          },
        },
        scales: {
          x: {
            type: "linear",
            title: { display: true, text: "Headcount (labor)", font: baseFont() },
            ticks: { font: baseFont(), callback: (v) => v.toLocaleString() },
            grid: { color: cssVar("--border") },
          },
          y: {
            min: 0,
            title: { display: true, text: "Units produced per hour", font: baseFont() },
            ticks: { font: baseFont(), callback: (v) => v.toLocaleString() },
            grid: { color: cssVar("--border") },
          },
        },
      },
    });
  }

  // labels: x-axis categories (month names, or years). series: [{ label:
  // "Packing Dept", data: [oee, oee, ...] }, ...] -- one line per
  // department, each its own fixed color (so the two departments stay
  // visually distinguishable across both the monthly and yearly trend
  // charts), plus a dashed 85% world-class benchmark reference line. A
  // series with only 1-2 points still needs visible dots -- a bare line
  // can't draw a segment with that few points.
  function renderDepartmentTrendChart(canvasId, labels, series) {
    destroy(canvasId);
    const pointRadius = labels.length <= 2 ? 4 : 0;
    const datasets = series.map((s, i) => ({
      label: s.label,
      data: s.data,
      borderColor: cssVar(COMPARISON_PALETTE[i % COMPARISON_PALETTE.length]),
      backgroundColor: "transparent",
      pointRadius,
      borderWidth: 2,
    }));
    datasets.push({
      label: "World-class benchmark (85%)",
      data: labels.map(() => 85),
      borderColor: cssVar("--muted"),
      backgroundColor: "transparent",
      borderDash: [6, 4],
      pointRadius: 0,
      borderWidth: 1,
    });

    const ctx = document.getElementById(canvasId).getContext("2d");
    instances[canvasId] = new Chart(ctx, {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { font: baseFont(), boxWidth: 12 } },
          tooltip: { callbacks: { label: (item) => `${item.dataset.label}: ${item.parsed.y}% OEE` } },
        },
        scales: {
          x: { ticks: { font: baseFont(), maxRotation: 0 }, grid: { display: false } },
          y: { min: 0, max: 100, ticks: { font: baseFont(), callback: (v) => v + "%" }, grid: { color: cssVar("--border") } },
        },
      },
    });
  }

  // months: [{monthLabel, gasConsumed, unitsProduced, gasPerThousandUnits}]
  // -- bars for gas consumed (left axis), a line for units produced (right
  // axis), so the relationship between the two is readable at a glance
  // even with only a handful of months. pointRadius is always visible
  // (never 0) since a sparse few-month series needs dots to read as a line
  // at all, same reasoning as the department trend chart.
  function renderGasVsProductionChart(canvasId, months) {
    destroy(canvasId);
    const ctx = document.getElementById(canvasId).getContext("2d");
    instances[canvasId] = new Chart(ctx, {
      data: {
        labels: months.map((m) => m.monthLabel),
        datasets: [
          {
            type: "bar",
            label: "Gas consumed",
            data: months.map((m) => m.gasConsumed),
            backgroundColor: cssVar("--gold"),
            borderWidth: 0,
            yAxisID: "y",
            order: 2,
          },
          {
            type: "line",
            label: "Units produced",
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
                ? `${item.dataset.label}: ${Math.round(item.parsed.y).toLocaleString()} units`
                : `${item.dataset.label}: ${item.parsed.y.toLocaleString()}`,
              afterBody: (items) => {
                const m = months[items[0].dataIndex];
                return `Gas per 1,000 units: ${m.gasPerThousandUnits.toLocaleString()}`;
              },
            },
          },
        },
        scales: {
          x: { ticks: { font: baseFont() }, grid: { display: false } },
          y: {
            position: "left",
            min: 0,
            title: { display: true, text: "Gas consumed", font: baseFont() },
            ticks: { font: baseFont(), callback: (v) => v.toLocaleString() },
            grid: { color: cssVar("--border") },
          },
          y1: {
            position: "right",
            min: 0,
            title: { display: true, text: "Units produced", font: baseFont() },
            ticks: { font: baseFont(), callback: (v) => v.toLocaleString() },
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
    renderTrendChart,
    renderOutputRateVsLaborChart,
    renderGasVsProductionChart,
    renderRankedOeeChart,
    renderComparisonBarChart,
    renderProductComparisonTrendChart,
    renderDepartmentTrendChart,
    weeklyBuckets,
  };
})();
