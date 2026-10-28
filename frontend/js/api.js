// Thin fetch wrappers for the backend API. Product/department endpoints are
// namespaced by slug -- see backend/app/products/registry.py for the full
// company org chart (Shahi 1 and Shahi 3 have real data today; most of the
// rest is registered but still excel_dir=None, see app.js).
const Api = (() => {
  const BASE = "/api";

  async function get(path) {
    const res = await fetch(BASE + path);
    if (!res.ok) {
      throw new Error(`GET ${path} failed: ${res.status}`);
    }
    return res.json();
  }

  async function post(path) {
    const res = await fetch(BASE + path, { method: "POST" });
    if (!res.ok) {
      throw new Error(`POST ${path} failed: ${res.status}`);
    }
    return res.json();
  }

  // A 404 here means "this product genuinely has no such data" (e.g. gas
  // meter readings, only registered for a handful of products) -- not an
  // error a caller should throw/alert on, so it resolves to null instead.
  async function getOptional(path) {
    const res = await fetch(BASE + path);
    if (res.status === 404) return null;
    if (!res.ok) {
      throw new Error(`GET ${path} failed: ${res.status}`);
    }
    return res.json();
  }

  return {
    listProducts: () => get("/products"),
    listDays: (slug) => get(`/products/${slug}/days`),
    getDay: (slug, date) => get(`/products/${slug}/days/${date}`),
    getOverview: (slug) => get(`/products/${slug}/overview`),
    getGasSummary: (slug) => getOptional(`/products/${slug}/gas`),
    getLaborCostSummary: (slug) => getOptional(`/products/${slug}/labor-cost`),
    getReconciliationSummary: (slug) => getOptional(`/products/${slug}/reconciliation`),
    getFgReconciliation: (slug) => getOptional(`/products/${slug}/fg-reconciliation`),
    refresh: (slug) => post(`/products/${slug}/refresh`),
    // Full org chart -- not consumed by the frontend yet, but real and
    // correct. This is where a future company/unit/department switcher
    // (beyond the Shahi 1 vs. Shahi 3 landing page) would start.
    getCompany: () => get("/company"),
    getCompanyCompare: () => get("/company/compare"),
    getDepartment: (slug) => get(`/departments/${slug}`),
    getDepartmentOverview: (slug) => get(`/departments/${slug}/overview`),
    getUnitOverview: (slug) => get(`/units/${slug}/overview`),
    getElectricity: (slug) => getOptional(`/units/${slug}/electricity`),
    getGasLpg: (slug) => getOptional(`/units/${slug}/gas-lpg`),
    getFacilityCost: (slug) => getOptional(`/units/${slug}/facility-cost`),
    getManufacturingOverhead: (slug) => getOptional(`/units/${slug}/manufacturing-overhead`),
    getMachines: (slug) => get(`/products/${slug}/machines`),
  };
})();
