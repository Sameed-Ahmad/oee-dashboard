// Unit-overview page: compares departments within one unit (Packing vs
// Production). One level below the company landing page (company.js), one
// level above the department-overview page (department.js). Kept light on
// purpose -- just comparison cards + a ranked chart, no small multiples.
const Unit = (() => {
  const el = (id) => document.getElementById(id);

  async function show(unitSlug) {
    wireControlsOnce();
    const [overview, electricity, gasLpg, facilityCost, overhead] = await Promise.all([
      Api.getUnitOverview(unitSlug),
      Api.getElectricity(unitSlug),
      Api.getGasLpg(unitSlug),
      Api.getFacilityCost(unitSlug),
      Api.getManufacturingOverhead(unitSlug),
    ]);
    renderHeader(overview);
    renderCards(overview);
    renderElectricitySection(electricity, facilityCost);
    renderGasLpgSection(gasLpg, facilityCost);
    renderOverheadSection(overhead);
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
            ${c.electricityCostPerUnitRs != null ? `
            <div>
              <span>Electricity cost / ${c.laborCostOutputUnit === "Packets" ? "Packet" : c.laborCostOutputUnit}</span>
              <strong>Rs. ${c.electricityCostPerUnitRs.toLocaleString(undefined, { maximumFractionDigits: 2 })}</strong>
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
  // Shahi 1 has this rich per-source breakdown; Shahi 3 doesn't (just a
  // single lump Rs. figure per month, see shahi3_cost.py) -- falls back
  // to the simpler facilityCost rendering when `electricity` is null.
  function renderElectricitySection(electricity, facilityCost) {
    const section = el("electricitySection");
    if (electricity && electricity.months.length > 0) {
      section.style.display = "";
      el("electricityPanelSub").textContent =
        "This unit's own monthly units and cost, with Packing & Production output in the table below -- click a month row to see the source-by-source breakdown.";
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
      return;
    }

    const months = (facilityCost || {}).months?.filter((m) => m.electricityCostRs != null) || [];
    if (months.length === 0) {
      section.style.display = "none";
      return;
    }
    section.style.display = "";
    el("electricityPanelSub").textContent =
      "This unit's own monthly facility electricity cost, with Packing & Production output in the table below.";
    Charts.renderSingleCostChart("electricityChart", months, "electricityCostRs", "Electricity cost (Rs.)", "--gold");
    el("electricityTable").innerHTML = `
      <thead>
        <tr>
          <th>Month</th>
          <th class="numeric">Electricity Cost (Rs.)</th>
          <th class="numeric">Packing Output (Packets)</th>
          <th class="numeric">Production Output (KG)</th>
        </tr>
      </thead>
      <tbody>
        ${months.map((m) => `
          <tr>
            <td>${m.monthLabel}</td>
            <td class="numeric">${formatRs(m.electricityCostRs)}</td>
            <td class="numeric">${m.packingOutputUnits != null ? m.packingOutputUnits.toLocaleString() : "—"}</td>
            <td class="numeric">${m.productionOutputUnits != null ? m.productionOutputUnits.toLocaleString() : "—"}</td>
          </tr>
        `).join("")}
      </tbody>
    `;
  }

  // Shahi 1's own direct-production Gas (m3) and LPG (KG) use -- a
  // separate fuel-use report from Electricity's Gas Generator figure
  // (see backend/app/electricity.py for why those aren't the same
  // thing, and why Wood Pellets isn't shown here at all yet). Shahi 3
  // again falls back to a single lump Gas Rs. figure per month (see
  // renderElectricitySection above for the same pattern).
  function renderGasLpgSection(gasLpg, facilityCost) {
    const section = el("gasLpgSection");
    if (gasLpg && gasLpg.months.length > 0) {
      section.style.display = "";
      el("gasLpgPanelSub").textContent =
        "This unit's own direct-production Gas and LPG use -- not the Gas Generator (already counted under Electricity) or Wood Pellets (no Shahi-only split available yet).";
      const months = gasLpg.months;
      Charts.renderGasLpgChart("gasLpgChart", months);

      const table = el("gasLpgTable");
      table.innerHTML = `
        <thead>
          <tr>
            <th>Month</th>
            <th class="numeric">Gas (m&sup3;)</th>
            <th class="numeric">Gas Cost (Rs.)</th>
            <th class="numeric">LPG (KG)</th>
            <th class="numeric">LPG Cost (Rs.)</th>
            <th class="numeric">Total Cost (Rs.)</th>
          </tr>
        </thead>
        <tbody>
          ${months.map((m) => `
            <tr>
              <td>${m.monthLabel}</td>
              <td class="numeric">${m.gasM3 != null ? m.gasM3.toLocaleString() : "—"}</td>
              <td class="numeric">${m.gasCostRs != null ? formatRs(m.gasCostRs) : "—"}</td>
              <td class="numeric">${m.lpgKg != null ? m.lpgKg.toLocaleString() : "—"}</td>
              <td class="numeric">${m.lpgCostRs != null ? formatRs(m.lpgCostRs) : "—"}</td>
              <td class="numeric">${formatRs(m.totalCostRs)}</td>
            </tr>
          `).join("")}
        </tbody>
      `;
      return;
    }

    const months = (facilityCost || {}).months?.filter((m) => m.gasCostRs != null) || [];
    if (months.length === 0) {
      section.style.display = "none";
      return;
    }
    section.style.display = "";
    el("gasLpgPanelSub").textContent =
      "This unit's own monthly facility gas cost.";
    Charts.renderSingleCostChart("gasLpgChart", months, "gasCostRs", "Gas cost (Rs.)", "--maroon");
    el("gasLpgTable").innerHTML = `
      <thead>
        <tr>
          <th>Month</th>
          <th class="numeric">Gas Cost (Rs.)</th>
          <th class="numeric">Production Output (KG)</th>
        </tr>
      </thead>
      <tbody>
        ${months.map((m) => `
          <tr>
            <td>${m.monthLabel}</td>
            <td class="numeric">${formatRs(m.gasCostRs)}</td>
            <td class="numeric">${m.productionOutputUnits != null ? m.productionOutputUnits.toLocaleString() : "—"}</td>
          </tr>
        `).join("")}
      </tbody>
    `;
  }

  // Shahi 3 only -- see backend/app/shahi3_cost.py's
  // compute_shahi3_manufacturing_overhead. One sub-block per department
  // (built dynamically since the chart/table need their own canvas/table
  // ids per department), each a stacked bar (department's own cost +
  // Support Department's cost) plus a table with the same breakdown.
  function renderOverheadSection(overhead) {
    const section = el("overheadSection");
    if (!overhead || overhead.departments.length === 0) {
      section.style.display = "none";
      return;
    }
    section.style.display = "";

    const container = el("overheadDepartments");
    container.innerHTML = overhead.departments.map((d) => `
      <div class="overhead-dept-block">
        <h3>${d.displayName}</h3>
        <div class="chart-wrap"><canvas id="overheadChart-${d.departmentSlug}"></canvas></div>
        <table class="data-table" id="overheadTable-${d.departmentSlug}"></table>
      </div>
    `).join("");

    overhead.departments.forEach((d) => {
      const months = d.months;
      const unit = months[0].outputUnit;
      Charts.renderOverheadChart(`overheadChart-${d.departmentSlug}`, months);

      el(`overheadTable-${d.departmentSlug}`).innerHTML = `
        <thead>
          <tr>
            <th>Month</th>
            <th class="numeric">Output (${unit})</th>
            <th class="numeric">Department Cost (Rs.)</th>
            <th class="numeric">Support Dept Cost (Rs.)</th>
            <th class="numeric">Total Overhead Cost (Rs.)</th>
            <th class="numeric">Cost / 1,000 ${unit}</th>
          </tr>
        </thead>
        <tbody>
          ${months.map((m) => `
            <tr>
              <td>${m.monthLabel}</td>
              <td class="numeric">${m.output.toLocaleString()}</td>
              <td class="numeric">${formatRs(m.departmentCostRs)}</td>
              <td class="numeric">${formatRs(m.supportCostRs)}</td>
              <td class="numeric">${formatRs(m.totalOverheadCostRs)}</td>
              <td class="numeric">${m.costPerThousandUnits.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
            </tr>
          `).join("")}
        </tbody>
      `;
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
