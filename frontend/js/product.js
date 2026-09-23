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
    machines: [], // group labels for this product, e.g. Ishida's named machines
    selectedMachines: [], // [] = whole-product view; 1 = single machine; 2+ = compared/combined
    machineRecordsByDate: {}, // { machineLabel: { date: record } }
    machineAllRecords: {}, // { machineLabel: [records sorted ascending] }
    availableMonths: [], // "YYYY-MM", sorted
    mode: "overview", // "overview" | "day" | "range"
    selectedDate: null,
    selectedShift: "combined", // "combined" | a shiftCode from that day's shifts[]
    selectedRangeStart: null,
    selectedRangeEnd: null,
    calendarMonthKey: null,
    calendarSelectMode: "day", // "day" | "range" -- controls what a calendar-day click does
    pendingRangeStart: null, // set after the first click while calendarSelectMode === "range"
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
      state.selectedRangeStart = null;
      state.selectedRangeEnd = null;
      state.calendarSelectMode = "day";
      state.pendingRangeStart = null;
      state.trendRangeMode = "recent";
      state.selectedMachines = [];
      state.machines = [];
      state.machineRecordsByDate = {};
      state.machineAllRecords = {};

      const [overview, allDates, machines] = await Promise.all([
        Api.getOverview(slug),
        Api.listDays(slug),
        Api.getMachines(slug),
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

      state.machines = machines.machines;
      state.machines.forEach((m) => {
        const recs = (machines.records[m] || []).slice().sort((a, b) => a.date.localeCompare(b.date));
        state.machineAllRecords[m] = recs;
        state.machineRecordsByDate[m] = {};
        recs.forEach((r) => { state.machineRecordsByDate[m][r.date] = r; });
      });

      wireControlsOnce();
    }

    renderProductTabs();
    renderHeader();
    renderMachineSelector();
    setTrendToggle("recent");
    render();
  }

  // ---------- Machine/line data-source resolution ----------

  // Combines 2+ selected machines'/lines' day records for the SAME DATE into
  // one. Additive fields (machines run, output, downtime) sum normally --
  // each line has its own. availTime/actTime don't: they're the plant's
  // shared shift-schedule window, not per-line, so two lines both reporting
  // a Day+Night shift both report the SAME ~1020 minutes -- summing across
  // lines would double-count that one wall-clock window, so the widest one
  // observed is used instead (a line that only ran Day shift shouldn't
  // shrink the window below what a Day+Night line already revealed).
  function combineLineRecords(records) {
    const sum = (key) => records.reduce((s, r) => s + r[key], 0);
    const max = (key) => records.reduce((m, r) => Math.max(m, r[key]), 0);
    const sumActMachines = sum("actMachines");
    const sumActualCounter = sum("actualCounter");
    const sumStock = sum("stockTransferred");

    const availPctWeightSum = records.reduce((s, r) => s + r.availabilityPct * r.actMachines, 0);
    const availabilityPct = sumActMachines ? availPctWeightSum / sumActMachines : 0;

    const perfWeightSum = records.reduce((s, r) => s + r.performancePct * r.actualCounter, 0);
    const performancePct = sumActualCounter ? perfWeightSum / sumActualCounter : 0;

    const speedWeightSum = records.reduce((s, r) => s + r.avgSpeed * r.actualCounter, 0);
    const avgSpeed = sumActualCounter ? speedWeightSum / sumActualCounter : sum("avgSpeed") / records.length;

    // Packing Dept lines never track Quality % per line (qualityPct is
    // always null there); Production Dept lines do -- recompute it from the
    // summed good/total output, same ratio-of-sums the day-level aggregation
    // already uses, rather than just carrying one line's own figure over.
    const hasQuality = records[0].qualityPct != null;
    const qualityPct = hasQuality && sumActualCounter ? (sumStock / sumActualCounter) * 100 : (hasQuality ? 0 : null);
    const oeePct = hasQuality ? (availabilityPct * performancePct * qualityPct) / 10000 : null;

    const downtime = {};
    records.forEach((r) => {
      Object.entries(r.downtime).forEach(([k, v]) => { downtime[k] = (downtime[k] || 0) + v; });
    });

    return {
      date: records[0].date,
      availMachines: sum("availMachines"),
      actMachines: sumActMachines,
      avgSpeed: Math.round(avgSpeed * 100) / 100,
      availTime: max("availTime"),
      actTime: max("actTime"),
      idealTargetOutput: Math.round(sum("idealTargetOutput") * 10) / 10,
      actualTargetOutput: Math.round(sum("actualTargetOutput") * 10) / 10,
      availabilityPct: Math.round(availabilityPct * 100) / 100,
      targetCounter: sum("targetCounter"),
      actualCounter: sumActualCounter,
      performancePct: Math.round(performancePct * 100) / 100,
      stockTransferred: sumStock,
      qualityPct: qualityPct == null ? null : Math.round(qualityPct * 100) / 100,
      oeePct: oeePct == null ? null : Math.round(oeePct * 100) / 100,
      downtime,
    };
  }

  // Resolves the current data source: the whole product (no machine
  // selected), one machine/line's own records, or -- when 2+ are selected
  // for comparison -- their per-date combination.
  function machineData() {
    const sel = state.selectedMachines;
    if (sel.length === 0) return { byDate: state.recordsByDate, all: state.allRecords };
    if (sel.length === 1) return { byDate: state.machineRecordsByDate[sel[0]], all: state.machineAllRecords[sel[0]] };

    const byDate = {};
    sel.forEach((m) => {
      Object.values(state.machineRecordsByDate[m] || {}).forEach((r) => {
        (byDate[r.date] = byDate[r.date] || []).push(r);
      });
    });
    const combinedByDate = {};
    Object.keys(byDate).forEach((date) => { combinedByDate[date] = combineLineRecords(byDate[date]); });
    const combinedAll = Object.values(combinedByDate).sort((a, b) => a.date.localeCompare(b.date));
    return { byDate: combinedByDate, all: combinedAll };
  }

  function currentRecordsByDate() {
    return machineData().byDate;
  }

  function currentAllRecords() {
    return machineData().all;
  }

  function machineSuffixText() {
    const sel = state.selectedMachines;
    return sel.length ? ` — ${sel.join(" + ")}` : "";
  }

  function setSelectedMachines(list) {
    state.selectedMachines = list;
    // Reset to Overview on any selection change -- a day/range picked for
    // the previous selection may not have data for the new one.
    state.mode = "overview";
    state.selectedDate = null;
    state.selectedShift = "combined";
    state.selectedRangeStart = null;
    state.selectedRangeEnd = null;
    setTrendToggle("recent");
    renderMachineSelector();
    render();
  }

  function renderMachineSelector() {
    const row = el("machineSelectorRow");
    if (state.machines.length === 0) {
      row.style.display = "none";
      return;
    }
    row.style.display = "";

    const seg = el("machineSegmented");
    seg.innerHTML = "";

    const allBtn = document.createElement("button");
    allBtn.type = "button";
    allBtn.textContent = "All machines";
    allBtn.className = state.selectedMachines.length === 0 ? "active" : "";
    allBtn.addEventListener("click", () => {
      if (state.selectedMachines.length === 0) return;
      setSelectedMachines([]);
    });
    seg.appendChild(allBtn);

    state.machines.forEach((m) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "machine-option" + (state.selectedMachines.includes(m) ? " active" : "");

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = state.selectedMachines.includes(m);
      checkbox.title = "Add to comparison";
      // Toggling the checkbox builds a multi-machine comparison (additive)
      // without affecting the rest of the selection -- stopPropagation
      // keeps this click from also reaching the button's own "switch to
      // just this one" handler below.
      checkbox.addEventListener("click", (e) => e.stopPropagation());
      checkbox.addEventListener("change", () => {
        const idx = state.selectedMachines.indexOf(m);
        const next = idx === -1
          ? state.selectedMachines.concat(m)
          : state.selectedMachines.filter((x) => x !== m);
        setSelectedMachines(next);
      });
      btn.appendChild(checkbox);

      const label = document.createElement("span");
      label.textContent = m;
      btn.appendChild(label);

      // Clicking the machine's name/body switches exclusively to just this
      // one -- the common case of "show me this line instead," not another
      // add-to-comparison click. Comparing several is opt-in via the checkbox.
      btn.addEventListener("click", () => {
        if (state.selectedMachines.length === 1 && state.selectedMachines[0] === m) return;
        setSelectedMachines([m]);
      });
      seg.appendChild(btn);
    });

    const hint = el("machineSelectorHint");
    hint.textContent = state.selectedMachines.length > 1
      ? `Comparing ${state.selectedMachines.length} lines (combined totals) — uncheck a box to remove one, or click a name to switch to just it.`
      : "Click a name to switch to it, or check boxes to compare/combine several.";
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
    return currentRecordsByDate()[state.selectedDate];
  }

  function activeRecord() {
    const day = activeDay();
    if (!day) return null;
    // Machine/line-level day records have no shift breakdown of their own
    // (a "machine" here is a product/SKU/machine-name grouping across the
    // whole day, not a Day/Night shift) -- always show the combined figures.
    if (state.selectedMachines.length > 0) return day;
    if (state.selectedShift === "combined") return day;
    return day.shifts.find((s) => s.shiftCode === state.selectedShift) || day;
  }

  // ---------- Recent-window helper for the trend chart (always day-level) ----------

  function getRecentWindow(endDate, size = 60) {
    const records = currentAllRecords();
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
    } else if (state.mode === "range") {
      renderRangeMode();
    } else {
      renderDayMode();
    }
    renderTrendSection();
  }

  function recordsInSelectedRange() {
    return currentAllRecords().filter(
      (r) => r.date >= state.selectedRangeStart && r.date <= state.selectedRangeEnd,
    );
  }

  // Same shape of aggregation as the backend's ProductSummary, computed
  // client-side over an arbitrary user-picked date range (we already have
  // every day record loaded, so no new endpoint is needed for this).
  function computeRangeSummary(records) {
    const n = records.length;
    const avg = (key) => records.reduce((sum, r) => sum + r[key], 0) / n;
    // Packing Dept machine/line records always have oeePct/qualityPct ==
    // null (Quality % isn't tracked at that granularity there -- see
    // MachineDayRecord); Production Dept's are real. Whichever it is here,
    // fall back to ranking best/toughest by Availability % when OEE isn't
    // available, so the tiles still mean something.
    const hasOee = records[0].oeePct != null;
    const rankKey = hasOee ? "oeePct" : "availabilityPct";

    const downtimeTotals = {};
    records.forEach((r) => {
      Object.entries(r.downtime).forEach(([k, v]) => {
        downtimeTotals[k] = (downtimeTotals[k] || 0) + v;
      });
    });

    const bestDay = records.reduce((a, b) => (b[rankKey] > a[rankKey] ? b : a));
    const worstDay = records.reduce((a, b) => (b[rankKey] < a[rankKey] ? b : a));

    return {
      daysCount: n,
      avgOeePct: hasOee ? avg("oeePct") : null,
      avgAvailabilityPct: avg("availabilityPct"),
      avgPerformancePct: avg("performancePct"),
      avgQualityPct: hasOee ? avg("qualityPct") : null,
      avgActMachines: avg("actMachines"),
      avgAvailMachines: avg("availMachines"),
      bestDay,
      worstDay,
      rankedBy: rankKey,
      downtimeTotals,
    };
  }

  // ---------- Shared display helpers for a possibly-untracked OEE/Quality ----------

  function displayHeroOee(oeePct) {
    if (oeePct == null) {
      el("heroOeeValue").textContent = "—";
      el("heroTierTag").textContent = "OEE not tracked per machine";
      el("heroTierTag").className = "tier-tag tier-neutral";
      return;
    }
    el("heroOeeValue").textContent = Utils.pct(oeePct);
    const tier = Utils.tierFor(oeePct);
    el("heroTierTag").textContent = tier.label;
    el("heroTierTag").className = "tier-tag " + tier.cls;
  }

  function displayQualityBar(qualityPct) {
    if (qualityPct == null) {
      el("barQualValue").textContent = "Not tracked";
      el("barQualFill").style.width = "0%";
      return;
    }
    setBar("Qual", qualityPct);
  }

  function bestWorstTileLabel(rankedBy) {
    // Only call out the ranking criterion when it's the Availability
    // fallback (machine/line mode) -- the normal OEE-ranked case keeps the
    // plain "Best day" wording it always had.
    return rankedBy === "availabilityPct" ? " (Availability)" : "";
  }

  function bestWorstTileValue(day, rankedBy) {
    return rankedBy === "availabilityPct"
      ? `${day.availabilityPct}% Avail`
      : `${day.oeePct}% OEE`;
  }

  function renderRangeMode() {
    const records = recordsInSelectedRange();
    const rangeLabel = `${Utils.formatDateShort(state.selectedRangeStart)} – ${Utils.formatDateShort(state.selectedRangeEnd)}`;

    el("dateSelectorLabel").textContent = rangeLabel;
    el("shiftToggleRow").style.display = "none";

    const summary = computeRangeSummary(records);

    el("heroLabel").textContent = `Average OEE — ${rangeLabel}`;
    displayHeroOee(summary.avgOeePct);

    setBar("Avail", summary.avgAvailabilityPct);
    setBar("Perf", summary.avgPerformancePct);
    displayQualityBar(summary.avgQualityPct);

    el("kpiStrip").innerHTML = "";
    addKpiTile("Days measured", String(summary.daysCount), rangeLabel);
    addKpiTile("Machines available", summary.avgAvailMachines.toFixed(1), "average across measured days");
    addKpiTile(`Best day${bestWorstTileLabel(summary.rankedBy)}`, bestWorstTileValue(summary.bestDay, summary.rankedBy), Utils.formatDateShort(summary.bestDay.date));
    addKpiTile(`Toughest day${bestWorstTileLabel(summary.rankedBy)}`, bestWorstTileValue(summary.worstDay, summary.rankedBy), Utils.formatDateShort(summary.worstDay.date));

    el("outputPanelSub").textContent = "Ideal vs. actual output for the selected range";
    Charts.renderOutputChartOverview("outputChart", records);

    el("downtimePanelSub").textContent = "Downtime minutes by cause, summed across the selected range";
    Charts.renderDowntimeChart("downtimeChart", summary.downtimeTotals);
    el("downtimeCallout").innerHTML = Charts.biggestCauseCallout(summary.downtimeTotals);
  }

  function renderOverviewMode() {
    const hasMachine = state.selectedMachines.length > 0;
    const records = currentAllRecords();
    // A machine/line has no backend-precomputed summary -- but we already
    // load every one of its day records up front, so the same client-side
    // aggregation used for date ranges works here too (same field shape).
    const summary = hasMachine ? computeRangeSummary(records) : state.overview;
    const rangeStart = hasMachine ? records[0].date : state.overview.dateRange.start;
    const rangeEnd = hasMachine ? records[records.length - 1].date : state.overview.dateRange.end;
    const machineSuffix = machineSuffixText();

    el("dateSelectorLabel").textContent =
      `Overview — ${Utils.formatDateShort(rangeStart)} to ${Utils.formatDateShort(rangeEnd)}`;

    el("shiftToggleRow").style.display = "none";

    el("heroLabel").textContent = "All-time average OEE" + machineSuffix;
    displayHeroOee(summary.avgOeePct);

    setBar("Avail", summary.avgAvailabilityPct);
    setBar("Perf", summary.avgPerformancePct);
    displayQualityBar(summary.avgQualityPct);

    el("kpiStrip").innerHTML = "";
    addKpiTile("Days measured", String(summary.daysCount), `${rangeStart} – ${rangeEnd}`);
    addKpiTile("Machines available", summary.avgAvailMachines.toFixed(1), "average across measured days");
    addKpiTile(`Best day${bestWorstTileLabel(summary.rankedBy)}`, bestWorstTileValue(summary.bestDay, summary.rankedBy), Utils.formatDateShort(summary.bestDay.date));
    addKpiTile(`Toughest day${bestWorstTileLabel(summary.rankedBy)}`, bestWorstTileValue(summary.worstDay, summary.rankedBy), Utils.formatDateShort(summary.worstDay.date));

    el("outputPanelSub").textContent = "Ideal vs. actual output, weekly totals across the full dataset" + machineSuffix;
    Charts.renderOutputChartOverview("outputChart", records);

    el("downtimePanelSub").textContent = "Downtime minutes by cause, summed across the full dataset" + machineSuffix;
    Charts.renderDowntimeChart("downtimeChart", summary.downtimeTotals);
    el("downtimeCallout").innerHTML = Charts.biggestCauseCallout(summary.downtimeTotals);
  }

  function renderDayMode() {
    const day = activeDay();
    const r = activeRecord();
    const hasMachine = state.selectedMachines.length > 0;
    const isShiftView = !hasMachine && state.selectedShift !== "combined";

    const suffix = isShiftView ? ` — ${shiftLabelFor(state.selectedShift)} shift` : machineSuffixText();
    el("dateSelectorLabel").textContent = Utils.formatDateLong(day.date);

    if (hasMachine) {
      el("shiftToggleRow").style.display = "none"; // no shift breakdown at machine/line granularity
    } else {
      renderShiftToggle(day);
    }

    el("heroLabel").textContent = Utils.formatDateLong(day.date) + suffix;
    displayHeroOee(r.oeePct);

    setBar("Avail", r.availabilityPct);
    setBar("Perf", r.performancePct);
    displayQualityBar(r.qualityPct);

    el("kpiStrip").innerHTML = "";
    addKpiTile("Machines run", `${r.actMachines} / ${r.availMachines}`, "actual vs. available machines");
    addKpiTile(
      "Run time",
      `${r.actTime} / ${r.availTime} min`,
      "click for downtime breakdown",
      () => openDowntimeModal(),
    );
    addKpiTile("Units produced", r.actualCounter.toLocaleString(), isShiftView ? r.sheet : (hasMachine ? state.selectedMachines.join(" + ") : day.sheets.join(", ")));

    el("outputPanelSub").textContent = isShiftView
      ? `Ideal vs. achievable vs. actual output for this shift`
      : "Ideal vs. achievable vs. actual output for this day" + suffix;
    Charts.renderOutputChartDay("outputChart", r);

    el("downtimePanelSub").textContent = isShiftView
      ? "Downtime minutes by cause for this shift"
      : "Downtime minutes by cause for this day" + suffix;
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
    el("trendToggle").style.display = state.mode === "range" ? "none" : "";

    if (state.mode === "range") {
      const records = recordsInSelectedRange();
      // Longer ranges fall back to weekly aggregation for legibility, same
      // threshold-free reasoning as the "full range" toggle elsewhere.
      const mode = records.length > 90 ? "full" : "recent";
      Charts.renderTrendChart("trendChart", records, mode);
      return;
    }

    const endDate = state.mode === "day" ? state.selectedDate : null;
    const records = state.trendRangeMode === "full"
      ? currentAllRecords()
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
    const isShiftView = state.selectedMachines.length === 0 && state.selectedShift !== "combined";
    const suffix = isShiftView
      ? ` — ${shiftLabelFor(state.selectedShift)} shift`
      : machineSuffixText();
    el("downtimeModalTitle").textContent = `Downtime breakdown — ${Utils.formatDateLong(day.date)}${suffix}`;
    Modal.open(el("downtimeModalOverlay"));
    requestAnimationFrame(() => Charts.renderDowntimeChart("downtimeModalChart", r.downtime));
  }

  // ---------- Date picker modal / calendar ----------

  function openDateModal() {
    if (state.mode === "day") {
      state.calendarMonthKey = state.selectedDate.slice(0, 7);
    } else if (state.mode === "range") {
      state.calendarMonthKey = state.selectedRangeEnd.slice(0, 7);
    }
    state.calendarSelectMode = state.mode === "range" ? "range" : "day";
    state.pendingRangeStart = null;
    setCalendarModeToggle(state.calendarSelectMode);
    renderCalendarMonth();
    Modal.open(el("dateModalOverlay"));
  }

  function setCalendarModeToggle(mode) {
    state.calendarSelectMode = mode;
    state.pendingRangeStart = null;
    document.querySelectorAll("#calendarModeToggle button").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.mode === mode);
    });
  }

  function updateRangeHint() {
    const hint = el("rangeHint");
    if (state.calendarSelectMode !== "range") {
      hint.innerHTML = "&nbsp;";
    } else if (state.pendingRangeStart) {
      hint.textContent = `Start: ${Utils.formatDateShort(state.pendingRangeStart)} — now click an end date.`;
    } else {
      hint.textContent = "Click a start date, then an end date — or click the month name for the whole month.";
    }
  }

  function calendarSelection() {
    if (state.calendarSelectMode === "range") {
      if (state.pendingRangeStart) return { type: "pending", start: state.pendingRangeStart };
      if (state.mode === "range") return { type: "range", start: state.selectedRangeStart, end: state.selectedRangeEnd };
      return null;
    }
    return state.mode === "day" ? { type: "day", date: state.selectedDate } : null;
  }

  function applyRange(start, end) {
    state.mode = "range";
    state.selectedRangeStart = start <= end ? start : end;
    state.selectedRangeEnd = start <= end ? end : start;
    state.pendingRangeStart = null;
    setTrendToggle("recent");
    Modal.close(el("dateModalOverlay"));
    render();
  }

  function onCalendarDayClick(dateStr) {
    if (state.calendarSelectMode === "range") {
      if (!state.pendingRangeStart) {
        state.pendingRangeStart = dateStr;
        updateRangeHint();
        renderCalendarMonth();
      } else {
        applyRange(state.pendingRangeStart, dateStr);
      }
      return;
    }
    state.mode = "day";
    state.selectedDate = dateStr;
    state.selectedShift = "combined";
    setTrendToggle("recent");
    Modal.close(el("dateModalOverlay"));
    render();
  }

  function onMonthLabelClick() {
    const dates = Calendar.datesInMonth(currentRecordsByDate(), state.calendarMonthKey);
    if (dates.length === 0) return;
    applyRange(dates[0], dates[dates.length - 1]);
  }

  function renderCalendarMonth() {
    const idx = state.availableMonths.indexOf(state.calendarMonthKey);
    el("calMonthLabel").textContent = Calendar.monthNameOnly(state.calendarMonthKey);
    el("calPrevBtn").disabled = idx <= 0;
    el("calNextBtn").disabled = idx === -1 || idx >= state.availableMonths.length - 1;
    syncYearSelect();
    updateRangeHint();

    Calendar.renderMonth(
      el("calendarGrid"),
      state.calendarMonthKey,
      currentRecordsByDate(),
      calendarSelection(),
      onCalendarDayClick,
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
      state.selectedRangeStart = null;
      state.selectedRangeEnd = null;
      setTrendToggle("recent");
      Modal.close(el("dateModalOverlay"));
      render();
    });

    document.querySelectorAll("#calendarModeToggle button").forEach((btn) => {
      btn.addEventListener("click", () => {
        setCalendarModeToggle(btn.dataset.mode);
        renderCalendarMonth();
      });
    });

    el("calMonthLabel").addEventListener("click", onMonthLabelClick);

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
