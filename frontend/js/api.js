// Thin fetch wrappers for the backend API. Product/department endpoints are
// namespaced by slug -- see backend/app/products/registry.py for the full
// company org chart (most of it has no data yet; only shahi-1-packing's four
// products are wired into this frontend today, see app.js).
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
    refresh: (slug) => post(`/products/${slug}/refresh`),
    // Full org chart -- not consumed by the frontend yet (only
    // shahi-1-packing has data), but real and correct. This is where a
    // future company/unit/department switcher would start.
    getCompany: () => get("/company"),
    getDepartment: (slug) => get(`/departments/${slug}`),
    getDepartmentOverview: (slug) => get(`/departments/${slug}/overview`),
    getUnitOverview: (slug) => get(`/units/${slug}/overview`),
    getMachines: (slug) => get(`/products/${slug}/machines`),
  };
})();
