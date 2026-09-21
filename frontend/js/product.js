// Single-product dashboard page: calendar popup, hero OEE, availability/
// performance/quality bars, output-lost chart, downtime Pareto, trend chart,
// and (new) a Day/Night/... shift toggle for multi-shift days. Driven by
// whichever product slug is currently selected -- see app.js's router.
const Product = (() => {
  const el = (id) => document.getElementById(id);

  const state = {
    slug: null,
    departmentSlug: null,
    departmentDisplayName: null,
    unitDisplayName: null,
    siblingProducts: [], // [{slug, displayName}], products in the same department -- tab bar
    overview: null,
    allDates: [],
    recordsByDate: {},
    allRecords: [], // sorted ascending by date, day-level (combined) records
    availableMonths: [], // "YYYY-MM", sorted
    mode: "overview", // "overview" | "day"
    selectedDate: null,
    selectedShift: "combined", // "combined" | a shiftCode from that day's shifts[]
    calendarMonthKey: null,
    trendRangeMode: "recent", // "recent" | "full"
  };

  async function show(slug) {
    const isProductSwitch = state.slug !== slug;
    state.slug = slug;

    if (isProductSwitch) {
      state.recordsByDate = {};
      state.mode = "overview";
      state.selectedDate = null;
      state.selectedShift = "combined";
      state.trendRangeMode = "recent";

      const [overview, allDates] = await Promise.all([
        Api.getOverview(slug),
        Api.listDays(slug),
      ]);
      state.overview = overview;
      state.allDates = allDates;

      // Only re-fetch the department (and its product list, for the tab
      // bar) if we've actually moved to a different department -- e.g.
      // switching between two Packing Dept products doesn't need this.
      if (overview.departmentSlug !== state.departmentSlug) {
        const dept = await Api.getDepartment(overview.departmentSlug);
        state.departmentSlug = dept.slug;
        state.departmentDisplayName = dept.displayName;
        state.unitDisplayName = dept.unit.displayName;
        state.siblingProducts = dept.products.filter((p) => p.hasData);
      }

      const dayRecords = await Promise.all(allDates.map((d) => Api.getDay(slug, d)));
      dayRecords.forEach((r) => { state.recordsByDate[r.date] = r; });
      state.allRecords = dayRecords.slice().sort((a, b) => a.date.localeCompare(b.date));
      state.availableMonths = Calendar.monthsFromDates(allDates);
      state.calendarMonthKey = state.availableMonths[state.availableMonths.length - 1];

      wireControlsOnce();
    }

    renderProductTabs();
    renderHeader();
    setTrendToggle("recent");
    render();
  }

  // ---------- Header / tabs ----------

  function renderHeader() {
    const ov = state.overview;
    el("headerHeading").textContent = ov.displayName;
    el("headerSubtitle").textContent = `${state.unitDisplayName} › ${state.departmentDisplayName}`;
    el("headerRightDynamic").innerHTML =
      `<div class="date-range">${Utils.formatDateShort(ov.dateRange.start)} – ${Utils.formatDateShort(ov.dateRange.end)}</div>`;

    el("backToOverviewLink").href = `#/department/${state.departmentSlug}`;
    el("backToOverviewLink").textContent = `‹ All products`;
  }

  function renderProductTabs() {
    const container = el("productTabs");
    container.innerHTML = "";
    state.siblingProducts.forEach((p) => {
      const tab = document.createElement("a");
      tab.className = "product-tab" + (p.slug === state.slug ? " active" : "");
      tab.href = `#/product/${p.slug}`;
      tab.textContent = p.displayName;
      container.appendChild(tab);
    });
  }

  // ---------- Active-record resolution (combined day vs one shift) ----------

  function activeDay() {
    return state.recordsByDate[state.selectedDate];
  }

  function activeRecord() {
    const day = activeDay();
    if (!day) return null;
    if (state.selectedShift === "combined") return day;
    return day.shifts.find((s) => s.shiftCode === state.selectedShift) || day;
  }

  // ---------- Recent-window helper for the trend chart (always day-level) ----------

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
      renderDayMode();
    }
    renderTrendSection();
  }

  function renderOverviewMode() {
    const ov = state.overview;
    el("dateSelectorLabel").textContent =
      `Overview — ${Utils.formatDateShort(ov.dateRange.start)} to ${Utils.formatDateShort(ov.dateRange.end)}`;

    el("shiftToggleRow").style.display = "none";

    el("heroLabel").textContent = "All-time average OEE";
    el("heroOeeValue").textContent = Utils.pct(ov.avgOeePct);
    const tier = Utils.tierFor(ov.avgOeePct);
    el("heroTierTag").textContent = tier.label;
    el("heroTierTag").className = "tier-tag " + tier.cls;

    setBar("Avail", ov.avgAvailabilityPct);
    setBar("Perf", ov.avgPerformancePct);
    setBar("Qual", ov.avgQualityPct);

    el("kpiStrip").innerHTML = "";
    addKpiTile("Days measured", String(ov.daysCount), `${ov.dateRange.start} – ${ov.dateRange.end}`);
    addKpiTile("Avg. machines used", ov.avgActMachines.toFixed(1), `of ${ov.avgAvailMachines.toFixed(1)} available on average`);
    addKpiTile("Best day", `${ov.bestDay.oeePct}% OEE`, Utils.formatDateShort(ov.bestDay.date));
    addKpiTile("Toughest day", `${ov.worstDay.oeePct}% OEE`, Utils.formatDateShort(ov.worstDay.date));

    el("outputPanelSub").textContent = "Ideal vs. actual output, weekly totals across the full dataset";
    Charts.renderOutputChartOverview("outputChart", state.allRecords);

    el("downtimePanelSub").textContent = "Downtime minutes by cause, summed across the full dataset";
    Charts.renderDowntimeChart("downtimeChart", ov.downtimeTotals);
    el("downtimeCallout").innerHTML = Charts.biggestCauseCallout(ov.downtimeTotals);
  }

  function renderDayMode() {
    const day = activeDay();
    const r = activeRecord();
    const isShiftView = state.selectedShift !== "combined";

    const shiftSuffix = isShiftView ? ` — ${shiftLabelFor(state.selectedShift)} shift` : "";
    el("dateSelectorLabel").textContent = Utils.formatDateLong(day.date);

    renderShiftToggle(day);

    el("heroLabel").textContent = Utils.formatDateLong(day.date) + shiftSuffix;
    el("heroOeeValue").textContent = Utils.pct(r.oeePct);
    const tier = Utils.tierFor(r.oeePct);
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
      () => openDowntimeModal(),
    );
    addKpiTile("Units produced", r.actualCounter.toLocaleString(), isShiftView ? r.sheet : day.sheets.join(", "));

    el("outputPanelSub").textContent = isShiftView
      ? `Ideal vs. achievable vs. actual output for this shift`
      : "Ideal vs. achievable vs. actual output for this day";
    Charts.renderOutputChartDay("outputChart", r);

    el("downtimePanelSub").textContent = isShiftView
      ? "Downtime minutes by cause for this shift"
      : "Downtime minutes by cause for this day";
    Charts.renderDowntimeChart("downtimeChart", r.downtime);
    el("downtimeCallout").innerHTML = Charts.biggestCauseCallout(r.downtime);
  }

  function shiftLabelFor(code) {
    const day = activeDay();
    const shift = day && day.shifts.find((s) => s.shiftCode === code);
    return shift ? shift.shiftLabel : code;
  }

  function renderShiftToggle(day) {
    const row = el("shiftToggleRow");
    if (day.shiftCount <= 1) {
      row.style.display = "none";
      return;
    }
    row.style.display = "";

    const seg = el("shiftSegmented");
    seg.innerHTML = "";
    const options = [{ code: "combined", label: "Combined" }].concat(
      day.shifts.map((s) => ({ code: s.shiftCode, label: s.shiftLabel })),
    );
    options.forEach((opt) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = opt.label;
      btn.className = opt.code === state.selectedShift ? "active" : "";
      btn.addEventListener("click", () => {
        state.selectedShift = opt.code;
        renderDayMode();
      });
      seg.appendChild(btn);
    });

    const caption = el("combinedCaption");
    if (state.selectedShift === "combined") {
      caption.style.display = "";
      caption.textContent =
        "Combines " + day.shifts.map((s) => s.shiftLabel).join(" + ") +
        " shift. Availability, Quality and totals are exact; Performance is a weighted average of the shifts' reported figures.";
    } else {
      caption.style.display = "none";
    }
  }

  function renderTrendSection() {
    const endDate = state.mode === "day" ? state.selectedDate : null;
    const records = state.trendRangeMode === "full"
      ? state.allRecords
      : getRecentWindow(endDate, 60);
    Charts.renderTrendChart("trendChart", records, state.trendRangeMode);
  }

  function setBar(suffix, value) {
    el(`bar${suffix}Value`).textContent = Utils.pct(value);
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

  function openDowntimeModal() {
    const day = activeDay();
    const r = activeRecord();
    const isShiftView = state.selectedShift !== "combined";
    const suffix = isShiftView ? ` — ${shiftLabelFor(state.selectedShift)} shift` : "";
    el("downtimeModalTitle").textContent = `Downtime breakdown — ${Utils.formatDateLong(day.date)}${suffix}`;
    Modal.open(el("downtimeModalOverlay"));
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
    el("calMonthLabel").textContent = Calendar.monthNameOnly(state.calendarMonthKey);
    el("calPrevBtn").disabled = idx <= 0;
    el("calNextBtn").disabled = idx === -1 || idx >= state.availableMonths.length - 1;
    syncYearSelect();

    Calendar.renderMonth(
      el("calendarGrid"),
      state.calendarMonthKey,
      state.recordsByDate,
      state.mode === "day" ? state.selectedDate : null,
      (dateStr) => {
        state.mode = "day";
        state.selectedDate = dateStr;
        state.selectedShift = "combined";
        setTrendToggle("recent");
        Modal.close(el("dateModalOverlay"));
        render();
      },
    );
  }

  function syncYearSelect() {
    const sel = el("calYearSelect");
    const years = Calendar.yearsFromMonths(state.availableMonths);
    const optionsHtml = years.map((y) => `<option value="${y}">${y}</option>`).join("");
    if (sel.dataset.years !== optionsHtml) {
      sel.innerHTML = optionsHtml;
      sel.dataset.years = optionsHtml;
    }
    sel.value = state.calendarMonthKey.slice(0, 4);
  }

  function jumpToYear(year) {
    const currentMonthNum = Number(state.calendarMonthKey.slice(5, 7));
    const target = Calendar.closestMonthInYear(state.availableMonths, year, currentMonthNum);
    if (target) {
      state.calendarMonthKey = target;
      renderCalendarMonth();
    }
  }

  function setTrendToggle(mode) {
    state.trendRangeMode = mode;
    document.querySelectorAll("#trendToggle button").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.range === mode);
    });
  }

  // ---------- Wiring (once per page load, not per product switch) ----------

  let controlsWired = false;

  function wireControlsOnce() {
    if (controlsWired) return;
    controlsWired = true;

    el("dateSelectorBtn").addEventListener("click", openDateModal);
    Modal.wireOverlay(el("dateModalOverlay"), el("dateModalClose"));
    Modal.wireOverlay(el("downtimeModalOverlay"), el("downtimeModalClose"));

    el("overviewBtn").addEventListener("click", () => {
      state.mode = "overview";
      state.selectedDate = null;
      state.selectedShift = "combined";
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

    el("calYearSelect").addEventListener("change", (e) => {
      jumpToYear(e.target.value);
    });

    document.querySelectorAll("#trendToggle button").forEach((btn) => {
      btn.addEventListener("click", () => {
        setTrendToggle(btn.dataset.range);
        renderTrendSection();
      });
    });

    el("refreshBtn").addEventListener("click", async () => {
      const btn = el("refreshBtn");
      const original = btn.textContent;
      btn.textContent = "Refreshing…";
      btn.disabled = true;
      try {
        await Api.refresh(state.slug);
        const slug = state.slug;
        state.slug = null; // force show() to treat this as a fresh load
        await show(slug);
      } catch (e) {
        alert("Refresh failed: " + e.message);
      } finally {
        btn.textContent = original;
        btn.disabled = false;
      }
    });
  }

  return { show };
})();
