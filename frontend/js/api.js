// Thin fetch wrappers for the backend API. Everything is namespaced by product
// slug even though only "fryo" is registered today (see backend/app/products/registry.py).
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

  return {
    listProducts: () => get("/products"),
    listDays: (slug) => get(`/products/${slug}/days`),
    getDay: (slug, date) => get(`/products/${slug}/days/${date}`),
    getOverview: (slug) => get(`/products/${slug}/overview`),
    refresh: (slug) => post(`/products/${slug}/refresh`),
  };
})();
