// Company landing page: compares Shahi 1 and Shahi 3 at the top level --
// overall OEE + total labor/electricity/gas cost per unit, then the two
// facility-wide cost comparison charts below. One level above the unit
// page (unit.js); clicking a unit's card drills into its own dashboard,
// the same one Shahi 1 already had before Shahi 3 existed. See
// backend/app/api/routes.py's get_company_compare for where this data
// comes from and COMPARABLE_UNIT_SLUGS for which units are included.
const Company = (() => {
  const el = (id) => document.getElementById(id);

  async function show() {
    const compare = await Api.getCompanyCompare();
    renderHeader();
    renderCards(compare.units);
    renderElectricitySection(compare.electricityMonths);
    renderGasSection(compare.gasMonths);
  }

  function renderHeader() {
    el("headerHeading").textContent = "Shahi Enterprises";
    el("headerSubtitle").textContent = "OEE Dashboard";
    el("headerRightDynamic").innerHTML = "";
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

  function renderCards(units) {
    const container = el("unitCompareCards");
    container.innerHTML = "";

    units.forEach((u) => {
      const tier = u.avgOeePct != null ? Utils.tierFor(u.avgOeePct) : null;
      const card = document.createElement("a");
      card.className = "product-card";
      card.href = `#/unit/${u.slug}`;
      card.innerHTML = `
        <div class="product-card-top">
          <h3>${u.displayName}</h3>
          ${tier ? `<span class="tier-tag ${tier.cls}">${tier.label}</span>` : ""}
        </div>
        <div class="product-card-oee">${u.avgOeePct != null ? Utils.pct(u.avgOeePct) : "—"}</div>
        <div class="product-card-metrics">
          <div>
            <span>Total labor cost</span>
            <strong>${u.totalLaborCostRs != null ? formatRs(u.totalLaborCostRs) : "—"}</strong>
            <small>${monthRangeLabel(u.laborCostFirstMonth, u.laborCostLastMonth)}</small>
          </div>
          <div>
            <span>Total electricity cost</span>
            <strong>${u.totalElectricityCostRs != null ? formatRs(u.totalElectricityCostRs) : "—"}</strong>
            <small>${monthRangeLabel(u.electricityFirstMonth, u.electricityLastMonth)}</small>
          </div>
          <div>
            <span>Total gas cost</span>
            <strong>${u.totalGasCostRs != null ? formatRs(u.totalGasCostRs) : "—"}</strong>
            <small>${monthRangeLabel(u.gasFirstMonth, u.gasLastMonth)}</small>
          </div>
        </div>
      `;
      container.appendChild(card);
    });
  }

  function renderElectricitySection(months) {
    const section = el("companyElectricitySection");
    if (!months || months.length === 0) {
      section.style.display = "none";
      return;
    }
    section.style.display = "";
    Charts.renderUnitCompareChart("companyElectricityChart", months);
  }

  function renderGasSection(months) {
    const section = el("companyGasSection");
    if (!months || months.length === 0) {
      section.style.display = "none";
      return;
    }
    section.style.display = "";
    Charts.renderUnitCompareChart("companyGasChart", months);
  }

  return { show };
})();
