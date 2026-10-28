// Top-level router: decides which of the four pages (company overview /
// unit overview / department overview / single-product dashboard) to show,
// based on the URL hash, and wires the one truly global control (dark-mode
// toggle). Everything else lives in company.js / unit.js / department.js /
// product.js.
//
// NOTE: only Shahi 1 and Shahi 3 have data today, both surfaced via the
// company landing page (#/company, also the default route). The other
// units (Zain 1/2) are still excel_dir=None everywhere -- Api.getCompany()
// already returns the full org chart with per-product hasData flags, ready
// for whenever they're added to COMPARABLE_UNIT_SLUGS on the backend too.

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
  if (parts[0] === "unit" && parts[1]) {
    return { view: "unit", slug: parts[1] };
  }
  return { view: "company" };
}

const PAGES = ["companyPage", "unitPage", "departmentPage", "productPage"];

function showPage(id) {
  PAGES.forEach((p) => { el(p).style.display = p === id ? "" : "none"; });
}

async function route() {
  const { view, slug } = parseRoute();
  try {
    if (view === "product") {
      showPage("productPage");
      await Product.show(slug);
    } else if (view === "department") {
      showPage("departmentPage");
      await Department.show(slug);
    } else if (view === "unit") {
      showPage("unitPage");
      await Unit.show(slug);
    } else {
      showPage("companyPage");
      await Company.show();
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
