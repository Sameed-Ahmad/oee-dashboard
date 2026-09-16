// Top-level state and render() wiring for the dashboard. Only "fryo" is
// loaded today; a future product switcher would set PRODUCT_SLUG from a
// dropdown here instead of a constant, and re-run init() on change.
const PRODUCT_SLUG = "fryo";

const state = {
  overview: null,
  allDates: [],
  recordsByDate: {},
  allRecords: [], // sorted ascending by date
  availableMonths: [], // "YYYY-MM", sorted
  mode: "overview", // "overview" | "day"
  selectedDate: null,
  calendarMonthKey: null,
  trendRangeMode: "recent", // "recent" | "full"
};

const el = (id) => document.getElementById(id);

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

// ---------- Init ----------

async function init() {
  const [overview, allDates] = await Promise.all([
    Api.getOverview(PRODUCT_SLUG),
    Api.listDays(PRODUCT_SLUG),
  ]);
  state.overview = overview;
  state.allDates = allDates;

  const dayRecords = await Promise.all(allDates.map((d) => Api.getDay(PRODUCT_SLUG, d)));
  dayRecords.forEach((r) => { state.recordsByDate[r.date] = r; });
  state.allRecords = dayRecords.slice().sort((a, b) => a.date.localeCompare(b.date));
  state.availableMonths = Calendar.monthsFromDates(allDates);
  state.calendarMonthKey = state.availableMonths[state.availableMonths.length - 1];

  el("headerDateRange").textContent =
    `${formatDateShort(overview.dateRange.start)} – ${formatDateShort(overview.dateRange.end)}`;

  wireControls();
  render();
}

// ---------- Recent-window helper for the trend chart ----------

function getRecentWindow(endDate, size = 60) {
  const records = state.allRecords;
  let endIdx = records.length - 1;
  if (endDate) {
    const idx = records.findIndex((r) => r.date === endDate);
    if (idx !== -1) endIdx = idx;
  }
  const startIdx = Math.max(0, endIdx - size + 1);
  return records.slice(startIdx, endIdx + 1);
}

// ---------- Rendering ----------

function render() {
  if (state.mode === "overview") {
    renderOverviewMode();
  } else {
    renderDayMode(state.selectedDate);
  }
  renderTrendSection();
}

function renderOverviewMode() {
  const ov = state.overview;
  el("dateSelectorLabel").textContent =
    `Overview — ${formatDateShort(ov.dateRange.start)} to ${formatDateShort(ov.dateRange.end)}`;

  el("heroLabel").textContent = "All-time average OEE";
  el("heroOeeValue").textContent = pct(ov.avgOeePct);
  const tier = tierFor(ov.avgOeePct);
  el("heroTierTag").textContent = tier.label;
  el("heroTierTag").className = "tier-tag " + tier.cls;

  setBar("Avail", ov.avgAvailabilityPct);
  setBar("Perf", ov.avgPerformancePct);
  setBar("Qual", ov.avgQualityPct);

  el("kpiStrip").innerHTML = "";
  addKpiTile("Days measured", String(ov.daysCount), `${ov.dateRange.start} – ${ov.dateRange.end}`);
  addKpiTile("Avg. machines used", ov.avgActMachines.toFixed(1), `of ${ov.avgAvailMachines.toFixed(1)} available on average`);
  addKpiTile("Best day", `${ov.bestDay.oeePct}% OEE`, formatDateShort(ov.bestDay.date));
  addKpiTile("Toughest day", `${ov.worstDay.oeePct}% OEE`, formatDateShort(ov.worstDay.date));

  el("outputPanelSub").textContent = "Ideal vs. actual output, weekly totals across the full dataset";
  Charts.renderOutputChartOverview("outputChart", state.allRecords);

  el("downtimePanelSub").textContent = "Downtime minutes by cause, summed across the full dataset";
  Charts.renderDowntimeChart("downtimeChart", ov.downtimeTotals);
  el("downtimeCallout").innerHTML = Charts.biggestCauseCallout(ov.downtimeTotals);
}

function renderDayMode(dateStr) {
  const r = state.recordsByDate[dateStr];
  el("dateSelectorLabel").textContent = formatDateLong(dateStr);

  el("heroLabel").textContent = formatDateLong(dateStr);
  el("heroOeeValue").textContent = pct(r.oeePct);
  const tier = tierFor(r.oeePct);
  el("heroTierTag").textContent = tier.label;
  el("heroTierTag").className = "tier-tag " + tier.cls;

  setBar("Avail", r.availabilityPct);
  setBar("Perf", r.performancePct);
  setBar("Qual", r.qualityPct);

  el("kpiStrip").innerHTML = "";
  addKpiTile("Machines run", `${r.actMachines} / ${r.availMachines}`, "actual vs. available machines");
  addKpiTile(
    "Run time",
    `${r.actTime} / ${r.availTime} min`,
    "click for downtime breakdown",
    () => openDowntimeModal(dateStr),
  );
  addKpiTile("Units produced", r.actualCounter.toLocaleString(), `sheet ${r.sheet}`);

  el("outputPanelSub").textContent = "Ideal vs. achievable vs. actual output for this day";
  Charts.renderOutputChartDay("outputChart", r);

  el("downtimePanelSub").textContent = "Downtime minutes by cause for this day";
  Charts.renderDowntimeChart("downtimeChart", r.downtime);
  el("downtimeCallout").innerHTML = Charts.biggestCauseCallout(r.downtime);
}

function renderTrendSection() {
  const endDate = state.mode === "day" ? state.selectedDate : null;
  const records = state.trendRangeMode === "full"
    ? state.allRecords
    : getRecentWindow(endDate, 60);
  Charts.renderTrendChart("trendChart", records, state.trendRangeMode);
}

function setBar(suffix, value) {
  el(`bar${suffix}Value`).textContent = pct(value);
  el(`bar${suffix}Fill`).style.width = `${Math.min(100, value)}%`;
}

function addKpiTile(label, value, sub, onClick) {
  const tile = document.createElement("div");
  tile.className = "kpi-tile" + (onClick ? " clickable" : "");
  tile.innerHTML = `
    <div class="kpi-label">${label}</div>
    <div class="kpi-value">${value}</div>
    <div class="kpi-sub">${sub}</div>
  `;
  if (onClick) tile.addEventListener("click", onClick);
  el("kpiStrip").appendChild(tile);
}

// ---------- Downtime modal ----------

function openDowntimeModal(dateStr) {
  const r = state.recordsByDate[dateStr];
  el("downtimeModalTitle").textContent = `Downtime breakdown — ${formatDateLong(dateStr)}`;
  Modal.open(el("downtimeModalOverlay"));
  // Render after the overlay is visible so the canvas has real dimensions.
  requestAnimationFrame(() => Charts.renderDowntimeChart("downtimeModalChart", r.downtime));
}

// ---------- Date picker modal / calendar ----------

function openDateModal() {
  if (state.mode === "day") {
    state.calendarMonthKey = state.selectedDate.slice(0, 7);
  }
  renderCalendarMonth();
  Modal.open(el("dateModalOverlay"));
}

function renderCalendarMonth() {
  const idx = state.availableMonths.indexOf(state.calendarMonthKey);
  el("calMonthLabel").textContent = Calendar.monthLabel(state.calendarMonthKey);
  el("calPrevBtn").disabled = idx <= 0;
  el("calNextBtn").disabled = idx === -1 || idx >= state.availableMonths.length - 1;

  Calendar.renderMonth(
    el("calendarGrid"),
    state.calendarMonthKey,
    state.recordsByDate,
    state.mode === "day" ? state.selectedDate : null,
    (dateStr) => {
      state.mode = "day";
      state.selectedDate = dateStr;
      state.trendRangeMode = "recent";
      setTrendToggle("recent");
      Modal.close(el("dateModalOverlay"));
      render();
    },
  );
}

function setTrendToggle(mode) {
  state.trendRangeMode = mode;
  document.querySelectorAll("#trendToggle button").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.range === mode);
  });
}

// ---------- Theme ----------

function applyStoredTheme() {
  let theme = null;
  try {
    theme = localStorage.getItem("fryo-oee-theme");
  } catch (e) { /* private browsing / blocked storage */ }
  if (theme) document.documentElement.setAttribute("data-theme", theme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const currentlyDark = current ? current === "dark" : prefersDark;
  const next = currentlyDark ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try {
    localStorage.setItem("fryo-oee-theme", next);
  } catch (e) { /* ignore */ }
  render(); // re-draw charts with the new palette's CSS vars
}

// ---------- Wiring ----------

function wireControls() {
  el("dateSelectorBtn").addEventListener("click", openDateModal);
  Modal.wireOverlay(el("dateModalOverlay"), el("dateModalClose"));
  Modal.wireOverlay(el("downtimeModalOverlay"), el("downtimeModalClose"));

  el("overviewBtn").addEventListener("click", () => {
    state.mode = "overview";
    state.selectedDate = null;
    state.trendRangeMode = "recent";
    setTrendToggle("recent");
    Modal.close(el("dateModalOverlay"));
    render();
  });

  el("calPrevBtn").addEventListener("click", () => {
    const idx = state.availableMonths.indexOf(state.calendarMonthKey);
    if (idx > 0) {
      state.calendarMonthKey = state.availableMonths[idx - 1];
      renderCalendarMonth();
    }
  });

  el("calNextBtn").addEventListener("click", () => {
    const idx = state.availableMonths.indexOf(state.calendarMonthKey);
    if (idx !== -1 && idx < state.availableMonths.length - 1) {
      state.calendarMonthKey = state.availableMonths[idx + 1];
      renderCalendarMonth();
    }
  });

  document.querySelectorAll("#trendToggle button").forEach((btn) => {
    btn.addEventListener("click", () => {
      setTrendToggle(btn.dataset.range);
      renderTrendSection();
    });
  });

  el("themeToggle").addEventListener("click", toggleTheme);

  el("refreshBtn").addEventListener("click", async () => {
    const btn = el("refreshBtn");
    const original = btn.textContent;
    btn.textContent = "Refreshing…";
    btn.disabled = true;
    try {
      await Api.refresh(PRODUCT_SLUG);
      state.recordsByDate = {};
      await init();
    } catch (e) {
      alert("Refresh failed: " + e.message);
    } finally {
      btn.textContent = original;
      btn.disabled = false;
    }
  });
}

applyStoredTheme();
init().catch((err) => {
  console.error(err);
  document.body.innerHTML = `<div style="padding:40px;font-family:sans-serif;color:#A23328">
    Failed to load dashboard data: ${err.message}. Is the FastAPI server running?
  </div>`;
});
