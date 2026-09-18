// Top-level router: decides whether to show the department-overview page or
// a single-product dashboard, based on the URL hash, and wires the one truly
// global control (dark-mode toggle). Everything else lives in department.js
// / product.js.
//
// NOTE: only "shahi-1-packing" (Fry-O/Pops/Ishida/Nimco) has data today, so
// this is hardcoded as the landing page and the only department the product
// tab bar/back-link ever points at. Once other departments have data, a real
// company/unit/department switcher would hook in here -- Api.getCompany()
// already returns the full org chart with per-product hasData flags, ready
// for that.
const DEFAULT_DEPARTMENT_SLUG = "shahi-1-packing";

const el = (id) => document.getElementById(id);

function parseRoute() {
  const hash = window.location.hash.replace(/^#\/?/, "");
  const parts = hash.split("/").filter(Boolean);
  if (parts[0] === "product" && parts[1]) {
    return { view: "product", slug: parts[1] };
  }
  if (parts[0] === "department" && parts[1]) {
    return { view: "department", slug: parts[1] };
  }
  return { view: "department", slug: DEFAULT_DEPARTMENT_SLUG };
}

async function route() {
  const { view, slug } = parseRoute();
  try {
    if (view === "product") {
      el("departmentPage").style.display = "none";
      el("productPage").style.display = "";
      await Product.show(slug);
    } else {
      el("productPage").style.display = "none";
      el("departmentPage").style.display = "";
      await Department.show(slug);
    }
  } catch (err) {
    console.error(err);
    document.body.innerHTML = `<div style="padding:40px;font-family:sans-serif;color:#A23328">
      Failed to load dashboard data: ${err.message}. Is the FastAPI server running?
    </div>`;
  }
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
  route(); // re-draw charts with the new palette's CSS vars
}

applyStoredTheme();
el("themeToggle").addEventListener("click", toggleTheme);
window.addEventListener("hashchange", route);
route();
