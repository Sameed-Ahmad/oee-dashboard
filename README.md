# Fry-O Packing OEE Dashboard

A local, full-stack dashboard visualizing Overall Equipment Effectiveness (OEE)
for Shahi Enterprises' Fry-O snack packing line, parsed from the plant's daily
Excel OEE reports. Runs entirely offline from a single `uvicorn` process.

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

The API is served from a pre-parsed JSON cache, not from the Excel file
directly. Build it once before first run (and again any time the workbook
changes):

```bash
python backend/scripts/build_cache.py --product fryo
```

This prints a summary (days parsed, sheets skipped and why, date range
covered, any parse warnings) and writes `backend/data/processed/fryo.json`.
If you skip this step, the API will build the cache automatically on first
request — the manual script is there mainly for visibility into the parse
result and as the "I dropped in a new month's data" workflow.

## Run

```bash
uvicorn backend.app.main:app --reload
```

Open http://localhost:8000 — FastAPI serves both the API (`/api/*`) and the
static frontend from this single process/port.

## Run the tests

```bash
cd backend
pytest tests/ -v
```

## Project layout

```
backend/
  app/
    main.py            FastAPI app: mounts frontend/ as static files + /api routes
    config.py           paths (raw data, processed cache, frontend dir)
    models.py           pydantic models: DayRecord, ProductSummary, ProductInfo
    parser.py            Excel parsing engine (generic across products)
    cache.py              JSON cache load/save + summary computation
    products/registry.py  PRODUCTS dict — one ProductConfig per product
    api/routes.py          all /api/* endpoints
  scripts/build_cache.py   CLI to (re)build a product's processed/<slug>.json
  data/raw/<slug>/          source Excel workbooks (per product)
  data/processed/            generated JSON caches (gitignored)
  tests/test_parser.py       unit + integration tests against the real workbook
frontend/
  index.html, css/, js/, vendor/ (Chart.js), assets/ (logo, fonts)
```

## Adding a new product (e.g. Nimco, Pops)

The parsing engine, API, and cache layer are all generic across products —
onboarding a new one that uses the same report template requires no code
changes to those layers:

1. Drop the new workbook into `backend/data/raw/<slug>/<workbook>.xlsx`.
2. Add a `ProductConfig` entry to `PRODUCTS` in
   `backend/app/products/registry.py`:
   ```python
   "nimco": ProductConfig(
       slug="nimco",
       display_name="Nimco",
       excel_path="nimco/<workbook>.xlsx",
   ),
   ```
3. Build its cache: `python backend/scripts/build_cache.py --product nimco`
4. The `/api/products` endpoint will now list it automatically, and
   `/api/products/nimco/...` routes work immediately.
5. **Not done in this version:** the frontend has no product switcher yet —
   it's hardcoded to load `"fryo"` (see the `PRODUCT_SLUG` constant at the
   top of `frontend/js/app.js`, with a comment marking where a switcher
   would hook in). Wiring up multi-product UI is future work.

## Notes on this build

- **Chart.js and fonts are vendored locally** (`frontend/vendor/chart.umd.min.js`,
  `frontend/assets/fonts/*.woff2`), so the dashboard works fully offline on
  the factory floor — no CDN calls at runtime.
- **Logo:** `frontend/index.html` references `frontend/assets/shahi-logo.png`
  directly. If that file isn't present yet, the header falls back to a
  plain "SE" monogram tile instead of a broken image — drop the real PNG
  in place any time and it'll pick it up on refresh.
- **Source workbook filename:** the actual file placed at
  `backend/data/raw/fryo/` is named `FryO Packing OEE 09-09-26.xlsx` (with
  spaces) rather than the underscored name originally mentioned in the
  spec. The filename is only ever referenced from
  `backend/app/products/registry.py`'s `ProductConfig.excel_path`, so this
  is a one-line config value, not a hardcoded path anywhere else.
- **Dark mode** is implemented both via `prefers-color-scheme: dark` and a
  manual override (the moon/sun button in the header), persisted in
  `localStorage`.
- Quality % is 100 on every single day across the full Oct 2025–Sep 2026
  dataset, confirmed by loading the whole parsed range — so, per spec, the
  trend chart plots OEE/Availability/Performance only, not Quality.
