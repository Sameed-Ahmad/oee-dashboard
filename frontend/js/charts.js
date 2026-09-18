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

  function tierColorVar(oeePct) {
    if (oeePct >= 90) return "--good";
    if (oeePct >= 80) return "--ok";
    return "--bad";
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
          backgroundColor: sorted.map((p) => cssVar(tierColorVar(p.avgOeePct))),
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
    let entries = sortedDowntimeEntries(downtimeTotals);
    if (limit) entries = entries.slice(0, limit);
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
              label: (item) => `${item.formattedValue} min`,
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
    const buckets = weeklyBuckets(allRecords);
    const labels = buckets.map((b) => b[0].date);
    const ideal = buckets.map((b) => b.reduce((s, r) => s + r.idealTargetOutput, 0));
    const actual = buckets.map((b) => b.reduce((s, r) => s + r.actualCounter, 0));

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
            pointRadius: 0,
            borderWidth: 2,
          },
          {
            label: "Actual output",
            data: actual,
            borderColor: cssVar("--maroon"),
            backgroundColor: "transparent",
            pointRadius: 0,
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

    if (mode === "full") {
      const buckets = weeklyBuckets(records);
      labels = buckets.map((b) => b[0].date);
      oee = buckets.map((b) => avg(b.map((r) => r.oeePct)));
      avail = buckets.map((b) => avg(b.map((r) => r.availabilityPct)));
      perf = buckets.map((b) => avg(b.map((r) => r.performancePct)));
    } else {
      labels = records.map((r) => r.date);
      oee = records.map((r) => r.oeePct);
      avail = records.map((r) => r.availabilityPct);
      perf = records.map((r) => r.performancePct);
    }

    const ctx = document.getElementById(canvasId).getContext("2d");
    instances[canvasId] = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "OEE %",
            data: oee,
            borderColor: cssVar("--line-oee"),
            backgroundColor: "transparent",
            pointRadius: 0,
            borderWidth: 2,
          },
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

  return {
    renderDowntimeChart,
    biggestCauseCallout,
    renderOutputChartDay,
    renderOutputChartOverview,
    renderTrendChart,
    renderRankedOeeChart,
    tierColorVar,
    weeklyBuckets,
  };
})();
