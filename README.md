# Shahi Enterprises OEE Dashboard

A local, full-stack dashboard visualizing Overall Equipment Effectiveness (OEE)
across Shahi Enterprises' packing lines, parsed from the plant's daily Excel
OEE reports. Runs entirely offline from a single `uvicorn` process.

Today it's populated with one department's worth of real data — Shahi 1's
Packing Dept (Fry-O, Pops, Ishida, Nimco) — but the backend models the whole
company org chart (sub-enterprises → units → departments → products), so
onboarding the next product or department is config, not code. See
[Adding a new product](#adding-a-new-product) below.

## Prerequisites

- Python 3.11+ (developed/tested against 3.14)
- No Node.js / npm required — the frontend is plain HTML/CSS/JS with no build step.

## Setup

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r backend/requirements.txt
```

## Build the data cache

The API is served from a pre-parsed JSON cache, not from the Excel files
directly. Build it once before first run (and again any time a workbook
changes):

```bash
# one product
python backend/scripts/build_cache.py --product fryo

# every product that has a workbook registered (fryo, pops, ishida, nimco today)
python backend/scripts/build_cache.py --all
```

This prints a summary per product (day records produced, date range covered,
any data-quality warnings) and writes `backend/data/processed/<slug>.json`.
If you skip this step, the API will build a product's cache automatically on
first request — the manual script is there mainly for visibility into the
parse result and as the "I dropped in a new month's data" workflow.

## Run

```bash
uvicorn backend.app.main:app --reload
```

Open http://localhost:8000 — FastAPI serves both the API (`/api/*`) and the
static frontend from this single process/port. The landing page is the
Packing Dept comparison view; click a product card (or use the tab bar once
inside a product's dashboard) to drill into its full OEE view.

## Run the tests

```bash
cd backend
pytest tests/ -v
```

## Project layout

```
backend/
  app/
    main.py                FastAPI app: mounts frontend/ as static files + /api routes
    config.py               paths (raw data, processed cache, frontend dir)
    models.py                pydantic models: ShiftRecord, DayRecord, ProductSummary,
                              plus the org-chart models (CompanyOrgInfo, DepartmentDetail, ...)
    parser.py                 the generic Excel-parsing + shift-aggregation engine --
                               one implementation for every product, no per-product config
    cache.py                   JSON cache load/save + summary computation
    products/registry.py        the full org chart: SubEnterpriseConfig / UnitConfig /
                                 DepartmentConfig / ProductConfig
    api/routes.py                 all /api/* endpoints
  scripts/build_cache.py    CLI to (re)build one or every product's processed/<slug>.json
  data/raw/<slug>/           source Excel workbooks (per product; newest file by
                              modified time is used automatically, see below)
  data/processed/             generated JSON caches (gitignored)
  tests/test_parser.py        unit + integration tests against the real workbooks
frontend/
  index.html                a single page with two views (department overview /
                             single-product dashboard), switched client-side via
                             URL hash routing (#/department/<slug>, #/product/<slug>)
  js/
    app.js                    top-level router + shared header + dark-mode toggle
    department.js              department-overview page (comparison cards, ranked
                                OEE chart, downtime small multiples)
    product.js                  single-product dashboard (calendar, hero, KPIs,
                                 charts, Day/Night shift toggle)
    api.js, calendar.js, charts.js, modal.js, utils.js
  vendor/ (Chart.js), assets/ (logo, fonts)
```

## How the Excel files are parsed

One parser handles every product — every column from F onward (downtime
categories, run time, availability, counters, performance, quality, OEE) is
in the same position with the same meaning across all four real workbooks.
Only the file location and the shift structure differ per product, and
neither needs per-product configuration:

- **File selection:** `ProductConfig.excel_dir` points at a folder
  (`backend/data/raw/<slug>/`), and the parser always uses the single newest
  `.xlsx` file in it by modified time (Excel's own `~$...` lock files are
  ignored). Dropping in a fresh monthly export is just "put the file in the
  folder" — no filename or config change needed.
- **Shifts:** most products report one sheet per calendar day (Fry-O), but
  some report a Day + Night sheet per day (Pops/Ishida/Nimco), and
  occasionally only one shift, or an oddball shift code. Sheets are grouped
  by date and combined into one `DayRecord` regardless of how many shift
  sheets exist for that date; the raw per-shift records are kept too (see
  `DayRecord.shifts`), so the frontend's shift toggle can show either the
  combined day or one specific shift.
- **Aggregating multiple shifts into a day** isn't just averaging
  percentages: additive fields (time, output, downtime, labor) are summed;
  Quality % and Output/Labor are recomputed from those sums (exact, since
  they reuse the same ratio the sheet itself uses); Availability % is exact
  too, via an identity (`availabilityPct × actMachines` reconstructs the
  sheet's own per-machine sum) verified against real data rather than
  requiring extra parsing; Performance % is an actualCounter-weighted
  average of each shift's own reported figure, since its underlying formula
  doesn't reproduce from summed counters; OEE is then derived from the
  day-level Availability/Performance/Quality so the three keep multiplying
  out to the fourth, same as they do per-shift.
- **Data-quality warnings** (e.g. an isolated date far from its neighbors,
  which caught a real year-typo in the Nimco file) are surfaced in the
  `build_cache.py` console output and in every product's `/overview`
  response (`dataQualityWarnings`) rather than silently dropped or "fixed."

## Adding a new product

The parsing engine, API, and cache layer are all generic — onboarding a new
product that uses the same report template requires no changes to those
layers:

1. Drop the new workbook into `backend/data/raw/<slug>/` (any filename).
2. Add a `ProductConfig` entry to `PRODUCTS` in
   `backend/app/products/registry.py`, pointing `department_slug` at an
   existing (or new) department:
   ```python
   "nimco": ProductConfig(
       slug="nimco",
       display_name="Nimco",
       department_slug="shahi-1-packing",
       excel_dir=Path("backend/data/raw/nimco"),
   ),
   ```
3. Build its cache: `python backend/scripts/build_cache.py --product nimco`
4. `/api/products`, `/api/departments/<dept>/overview`, and
   `/api/products/nimco/...` all pick it up automatically.
5. **Not done in this version:** the frontend has no company/unit/department
   switcher yet — it's hardcoded to land on `shahi-1-packing` and its four
   products (see `DEFAULT_DEPARTMENT_SLUG` in `frontend/js/app.js`, with a
   comment marking where a real switcher would hook in once more
   departments have data). `GET /api/company` already returns the full org
   chart with per-product `hasData` flags, ready for that.

Adding a whole new **department or sub-enterprise** with no products yet is
the same idea one level up: add a `DepartmentConfig` (and `UnitConfig` /
`SubEnterpriseConfig` if needed) to `registry.py`. It'll show up in
`GET /api/company` immediately with `hasData: false` until a product under
it gets a real `excel_dir`.

## Notes on this build

- **Chart.js and fonts are vendored locally** (`frontend/vendor/chart.umd.min.js`,
  `frontend/assets/fonts/*.woff2`), so the dashboard works fully offline on
  the factory floor — no CDN calls at runtime.
- **Dark mode** is implemented both via `prefers-color-scheme: dark` and a
  manual override (the moon/sun button in the header), persisted in
  `localStorage`.
- Quality % is 100 on every single Fry-O day across the full parsed range,
  confirmed by loading the whole dataset — so, per spec, the trend chart
  plots OEE/Availability/Performance only, not Quality.
