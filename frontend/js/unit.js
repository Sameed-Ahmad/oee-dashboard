// Unit-overview landing page: compares departments within one unit (today,
// only Shahi 1's Packing vs Production). This is the default landing page,
// one level above the department-overview page (department.js). Kept light
// on purpose -- just comparison cards + a ranked chart, no small multiples.
const Unit = (() => {
  const el = (id) => document.getElementById(id);

  async function show(unitSlug) {
    wireControlsOnce();
    const [overview, electricity] = await Promise.all([
      Api.getUnitOverview(unitSlug),
      Api.getElectricity(unitSlug),
    ]);
    renderHeader(overview);
    renderCards(overview);
    renderElectricitySection(electricity);
  }

  let controlsWired = false;

  function wireControlsOnce() {
    if (controlsWired) return;
    controlsWired = true;
    Modal.wireOverlay(el("electricityMonthModalOverlay"), el("electricityMonthModalClose"));
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

  function formatRs(amount) {
    return `Rs. ${Math.round(amount).toLocaleString()}`;
  }

  function monthRangeLabel(first, last) {
    if (!first) return "";
    return first === last
      ? Calendar.monthLabel(first)
      : `${Calendar.monthNameOnly(first)}–${Calendar.monthLabel(last)}`;
  }

  function renderCards(overview) {
    const container = el("departmentCards");
    container.innerHTML = "";

    overview.departments
      .slice()
      .sort((a, b) => b.summary.avgOeePct - a.summary.avgOeePct)
      .forEach((d) => {
        const s = d.summary;
        const c = d.costs;
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
            <div>
              <span>Total labor cost</span>
              <strong>${c.totalLaborCostRs != null ? formatRs(c.totalLaborCostRs) : "—"}</strong>
              <small>${monthRangeLabel(c.laborCostFirstMonth, c.laborCostLastMonth)}</small>
            </div>
            ${c.laborCostPerThousandUnits != null ? `
            <div>
              <span>Labor cost / 1,000 ${c.laborCostOutputUnit}</span>
              <strong>${formatRs(c.laborCostPerThousandUnits)}</strong>
            </div>
            ` : ""}
            ${c.gasCostGroups.map((g) => `
            <div>
              <span>Gas cost / 1,000 ${g.outputUnit} (avg of ${g.products.length} product${g.products.length === 1 ? "" : "s"})</span>
              <strong>${formatRs(g.costPerThousandUnits)}</strong>
            </div>
            `).join("")}
          </div>
          <div class="product-card-footer">
            <span>${d.productCount} product${d.productCount === 1 ? "" : "s"}</span>
          </div>
        `;
        container.appendChild(card);
      });
  }

  // Facility-wide electricity, not tied to any one department -- see
  // backend/app/electricity.py for why only a combined monthly total is
  // available (the source sheet never splits units by source for
  // Shahi 1 specifically, only the combined Zain-1/Shahi-1 total).
  function renderElectricitySection(electricity) {
    const section = el("electricitySection");
    if (!electricity || electricity.months.length === 0) {
      section.style.display = "none";
      return;
    }
    section.style.display = "";

    const months = electricity.months;
    Charts.renderElectricityChart("electricityChart", months);

    const table = el("electricityTable");
    table.innerHTML = `
      <thead>
        <tr>
          <th>Month</th>
          <th class="numeric">Units Consumed</th>
          <th class="numeric">Cost (Rs.)</th>
          <th class="numeric">Share of Facility Total</th>
          <th class="numeric">Packing Output (Packets)</th>
          <th class="numeric">Production Output (KG)</th>
        </tr>
      </thead>
      <tbody>
        ${months.map((m) => `
          <tr class="clickable-row" data-month="${m.month}">
            <td>${m.monthLabel}</td>
            <td class="numeric">${m.unitsConsumed.toLocaleString()}</td>
            <td class="numeric">${formatRs(m.costRs)}</td>
            <td class="numeric">${m.sharePct != null ? `${m.sharePct}%` : "—"}</td>
            <td class="numeric">${m.packingOutputUnits != null ? m.packingOutputUnits.toLocaleString() : "—"}</td>
            <td class="numeric">${m.productionOutputUnits != null ? m.productionOutputUnits.toLocaleString() : "—"}</td>
          </tr>
        `).join("")}
      </tbody>
    `;
    table.querySelectorAll("tr[data-month]").forEach((row) => {
      row.addEventListener("click", () => {
        const month = months.find((m) => m.month === row.dataset.month);
        openElectricityMonthModal(month);
      });
    });
  }

  // Source-by-source drill-down for one month: each of the 4 power
  // sources (facility-wide, Zain-1 + Shahi-1 combined -- see
  // backend/app/electricity.py for why this can't be split per facility),
  // then a combined Total row, then Shahi-1's own derived units/cost and
  // its % share of that total.
  function openElectricityMonthModal(month) {
    el("electricityMonthModalTitle").textContent = `Electricity -- ${month.monthLabel}`;
    const table = el("electricityMonthModalTable");
    table.innerHTML = `
      <thead>
        <tr>
          <th>Source</th>
          <th class="numeric">Units Consumed</th>
          <th class="numeric">Unit Cost (Rs.)</th>
          <th class="numeric">Total Bill (Rs.)</th>
        </tr>
      </thead>
      <tbody>
        ${month.sources.map((s) => `
          <tr>
            <td>${s.name}</td>
            <td class="numeric">${s.units != null ? s.units.toLocaleString() : "—"}</td>
            <td class="numeric">${s.unitCost != null ? s.unitCost.toLocaleString() : (s.billRs == null && s.units != null ? "Free" : "—")}</td>
            <td class="numeric">${s.billRs != null ? formatRs(s.billRs) : "—"}</td>
          </tr>
        `).join("")}
        <tr class="total-row">
          <td><strong>Total (all sources)</strong></td>
          <td class="numeric"><strong>${month.facilityTotalUnits != null ? month.facilityTotalUnits.toLocaleString() : "—"}</strong></td>
          <td class="numeric"><strong>${month.facilityAvgUnitCost.toLocaleString()}</strong></td>
          <td class="numeric"><strong>${month.facilityTotalCostRs != null ? formatRs(month.facilityTotalCostRs) : "—"}</strong></td>
        </tr>
        <tr>
          <td>Shahi 1's share</td>
          <td class="numeric">${month.unitsConsumed.toLocaleString()} (${month.sharePct != null ? `${month.sharePct}%` : "—"})</td>
          <td class="numeric">—</td>
          <td class="numeric">${formatRs(month.costRs)}</td>
        </tr>
      </tbody>
    `;
    Modal.open(el("electricityMonthModalOverlay"));
  }

  return { show };
})();
