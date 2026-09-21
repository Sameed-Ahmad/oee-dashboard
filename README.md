# Shahi Enterprises OEE Dashboard

A local, full-stack dashboard visualizing Overall Equipment Effectiveness (OEE)
across Shahi Enterprises' packing and production lines, parsed from the
plant's daily Excel OEE reports. Runs entirely offline from a single
`uvicorn` process.

Today it's populated with real data for Shahi 1's two departments:

- **Packing Dept**: Fry-O, Pops, Ishida, Nimco
- **Production Dept**: Coated Peanut, Namak Para, HNC 1, HNC 3, Extruder, Kuiper

The backend models the whole company org chart (sub-enterprises → units →
departments → products), so onboarding the next product, department, or unit
is config, not code. See [Adding a new product](#adding-a-new-product) below.

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

# every product that has a workbook registered (all 10 today)
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
static frontend from this single process/port, with caching disabled on the
frontend files (this app is actively edited locally; see `NoCacheStaticFiles`
in `main.py`). The landing page is the Shahi 1 unit overview (Packing Dept vs
Production Dept); click a department card to see its product comparison,
then a product card (or the tab bar once inside a product's dashboard) to
drill into its full OEE view.

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
                              plus the org-chart models (CompanyOrgInfo, UnitOverview,
                              DepartmentDetail, DepartmentOverview, ...)
    parser.py                 the generic Excel-parsing + shift-aggregation engine --
                               one implementation for every product, no hardcoded
                               column letters, label text, or downtime category names
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
  index.html                a single page with three views (unit overview /
                             department overview / single-product dashboard),
                             switched client-side via URL hash routing
                             (#/unit/<slug>, #/department/<slug>, #/product/<slug>)
  js/
    app.js                    top-level router + shared header + dark-mode toggle
    unit.js                     unit-overview page (department comparison cards +
                                 ranked OEE chart) -- the default landing page
    department.js              department-overview page (product comparison cards,
                                ranked OEE chart, downtime small multiples)
    product.js                  single-product dashboard (calendar with a year
                                 jump-select, hero, KPIs, charts, Day/Night shift toggle)
    api.js, calendar.js, charts.js, modal.js, utils.js
  vendor/ (Chart.js), assets/ (logo, fonts)
```

## How the Excel files are parsed

One parser handles every product across both departments. Nothing is keyed
by a hardcoded column letter, label string, or downtime category name --
Packing Dept and Production Dept don't even share a column layout (summary
block at AJ/AK/AL vs AI/AJ/AK), and Production Dept's six workbooks each use
their own downtime category names. Everything is located by content, per
sheet, at parse time:

- **File selection:** `ProductConfig.excel_dir` points at a folder
  (`backend/data/raw/<slug>/`), and the parser always uses the single newest
  `.xlsx` file in it by modified time (Excel's own `~$...` lock files are
  ignored). Dropping in a fresh export is just "put the file in the folder"
  -- no filename or config change needed.
- **The 16-row summary block** (Machines/Time/.../Output-Labor) is found by
  searching every cell for the `'Available'` / `'Machines'` / `<number>`
  triplet, rather than assuming it's at any particular column -- this varies
  by product and the label text itself is sometimes blank.
- **Downtime categories** are found by locating a `"total time"` marker and
  a `"total down time"` marker in whichever header row actually has them
  (normally row 6, but at least one real sheet has everything shifted up by
  one row), and reading whatever category names sit between them. Two
  products can use completely different category sets; the frontend shows
  whatever text the sheet itself uses.
- **Shifts:** most products report one sheet per calendar day (Fry-O), some
  report a Day + Night sheet per day, and a couple of Production Dept
  products (Coated Peanut) report multiple parallel production lines as
  separate same-date sheets. Sheets are grouped by date and combined into
  one `DayRecord`; the raw per-shift/per-line records are kept too (see
  `DayRecord.shifts`), so the frontend's shift toggle can show either the
  combined day or one specific shift.
- **Duplicate vs. distinct same-date sheets:** some workbooks have leftover
  edit-history duplicates of an already-reported sheet (e.g. `15-06-26`
  alongside six `15-06-26 (62)`..`(67)` copies) using the same `"(NN)"`
  suffix convention that Coated Peanut uses for genuinely distinct parallel
  lines. The two are told apart by whether a *clean* (unsuffixed) sheet
  exists for that date: if it does, the numbered sheet is a duplicate and is
  excluded entirely; if it doesn't, it's a distinct entry and is parsed
  normally.
- **Blank-filtering:** a numbered/suffixed sheet that turns out to be all
  zero (an inactive parallel line, or a stray empty copy) is excluded from
  aggregation. A *clean* sheet that's all zero is kept -- it's the sole
  record for its date+shift, so an honest zero (e.g. a Night shift that
  never ran) is real, reportable data, not junk to hide.
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
  which caught a real year-typo in the Nimco file, and real early-reporting
  gaps in Coated Peanut/Namak Para) are surfaced in the `build_cache.py`
  console output and in every product's `/overview` response
  (`dataQualityWarnings`) rather than silently dropped or "fixed."

## Adding a new product

The parsing engine, API, and cache layer are all generic — onboarding a new
product requires no changes to those layers, regardless of its column
layout or downtime category names:

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
4. `/api/products`, `/api/departments/<dept>/overview`,
   `/api/units/<unit>/overview`, and `/api/products/nimco/...` all pick it
   up automatically.
5. **Not done in this version:** the frontend has no full company/unit
   switcher yet — it's hardcoded to land on `shahi-1` (see
   `DEFAULT_UNIT_SLUG` in `frontend/js/app.js`, with a comment marking where
   a real switcher would hook in once more units have data). `GET
   /api/company` already returns the full org chart with per-product
   `hasData` flags, ready for that.

Adding a whole new **department, unit, or sub-enterprise** with no products
yet is the same idea one level up: add a `DepartmentConfig` (and
`UnitConfig` / `SubEnterpriseConfig` if needed) to `registry.py`. It'll show
up in `GET /api/company` immediately with `hasData: false` until a product
under it gets a real `excel_dir`.

## Notes on this build

- **Chart.js and fonts are vendored locally** (`frontend/vendor/chart.umd.min.js`,
  `frontend/assets/fonts/*.woff2`), so the dashboard works fully offline on
  the factory floor — no CDN calls at runtime.
- **Dark mode** is implemented both via `prefers-color-scheme: dark` and a
  manual override (the moon/sun button in the header), persisted in
  `localStorage`.
- The calendar date-picker (used across every product's dashboard) has a
  year jump-select next to the month name, so browsing a wide date range
  (e.g. Nimco's Mar 2025 – Sep 2026) doesn't require repeatedly clicking
  through every month.
- Quality % is 100 on every single Fry-O day across the full parsed range,
  confirmed by loading the whole dataset — so, per spec, the trend chart
  plots OEE/Availability/Performance only, not Quality.
