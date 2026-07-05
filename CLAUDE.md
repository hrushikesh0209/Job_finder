# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Job Finder AI — a multi-platform job scraper (LinkedIn, Indeed, RemoteOK, Remotive, Jobicy, Arbeitnow, The Muse, Naukri, Seek, JobStreet, Bayt, Reed, Rozee) with CV match scoring and formatted Excel export. Pure Python, no database, no tests, no linter configured.

## Commands

```powershell
# Install core dependencies (use the venv in ./venv)
pip install -r requirements.txt

# Run the Streamlit web UI (primary entry point)
streamlit run app.py

# Run the CLI (alternative entry point)
python run.py --keyword "Python Developer" --location "Remote" --cv my_cv.pdf

# One-shot Windows setup + launch
install_and_run.bat
```

There is no test suite or lint configuration. Verify changes by running a search via `run.py` (faster feedback than the UI).

## Architecture

Two entry points share three core modules:

- **`app.py`** — Streamlit UI. Searches go through `_cached_search` (`st.cache_data`, 15-min TTL — identical params return instantly; lists must be passed as tuples). All session state lives in `st.session_state` (`jobs_df`, `cv_text`, `cv_file_id`, `excel_bytes`, per-row `ai_res_*` — cleared on every new search). A `job_skills` column is computed once at search time (`_attach_job_skills`) so job cards never re-run skill regexes on reruns. CV match scores are attached as DataFrame *columns* (`match_score`, `matched_skills`, `missing_skills`) on the full unfiltered frame to avoid index-alignment bugs when UI filters are applied; the columns are dropped when the CV upload is removed. List columns (`job_skills`, `matched_skills`, `missing_skills`) must be dropped before CSV export.
- **`run.py`** — argparse CLI over the same modules.
- **`scraper.py`** — all 13 board scrapers plus the public API: `search_jobs()` (one keyword, all sites in a `ThreadPoolExecutor`) and `search_jobs_multi()` (many keywords, max 2 concurrent, adds a `searched_keyword` column). Results pass through `_filter_by_age()` (rows with no `date_posted` pass — most boards don't expose dates), `_dedupe()` (primary key `job_url`, fallback `title|company`, plus an exact title/company/location pass), `_ensure_job_urls()` (rows a scraper couldn't link get a per-board search URL for title+company — every row must have a clickable `job_url`), and `_interleave()` (round-robin across sites/keywords so truncation to `max_results` doesn't keep only the fastest board), then truncate. When `remote_only=True`, LinkedIn is queried with `f_WT=2` and its rows are force-flagged `is_remote=True` — the text-based remote check must never filter out server-side-filtered LinkedIn results, and `search_jobs_multi` must keep passing `remote_only` down for this to work. Remotive/Jobicy/Arbeitnow/The Muse are open JSON APIs, no key needed; Arbeitnow and The Muse have no search parameter, so keywords are matched client-side (all words must appear in title+description). Do NOT set an `Accept-Encoding` header manually — advertising `br` without brotli installed makes responses undecodable (this broke Remotive/Jobicy once).
- **`cv_analyzer.py`** — CV reading (.docx/.pdf), similarity scoring, and skill extraction: `extract_skills(text) -> set` is the public entry; `keyword_gap(cv, jd, cv_skills=...)` accepts a precomputed CV skill set so callers don't re-scan the CV per job. `_SKILL_PATTERNS` uses lookarounds, not `\b` — plain word boundaries can never match `c++`/`c#`, and `r`/`go` have special context-guarded patterns. Optional AI suggestions (Claude/OpenAI/Gemini).
- **`excel_exporter.py`** — openpyxl workbook with color-coded Jobs + Summary sheets.
- **`locations.py`** — static data only: job titles, country→city map, country→recommended-board map (`COUNTRY_PLATFORMS`), `PLATFORM_INFO`.

### The job-dict contract

Every scraper builds dicts with the same keys — `title, company, location, date_posted, job_url, job_id, description, job_type, job_level, is_remote` — and returns them through `_to_dataframe(jobs, site_label)`, which adds the `site` column and ensures the salary columns (`min_amount, max_amount, currency, interval, salary_text`) exist. `salary_text` is a free-text salary string (set by Remotive/Jobicy); the Excel exporter and job cards fall back to it when the structured amounts are empty. Downstream code (app UI, Excel export, CV scoring) depends on these column names.

### The match_scores contract

`export_to_excel(df, match_scores, ...)` expects `match_scores` as a list of dicts with keys `tfidf_score`, `matched_skills`, `missing_skills` — one per DataFrame row, in row order. `app.py` builds this by renaming its `match_score` column to `tfidf_score`.

### Optional-dependency fallback chains

The codebase degrades gracefully when optional packages are missing — preserve this pattern (try-import at module level or inside the function, log a warning, fall back):

- **Indeed & Naukri**: Playwright only (Cloudflare JS challenge / reCAPTCHA + Next.js hydration defeat plain HTTP); both return empty with a logged warning otherwise. Indeed's old RSS endpoint is discontinued — do not reintroduce it or curl_cffi.
- **CV scoring**: sentence-transformers (semantic, model cached in module-level `_ST_MODEL`, CV embedded in mean-pooled chunks) → TF-IDF (scikit-learn).
- **PDF reading**: pdfplumber → PyPDF2.
- **AI suggestions**: anthropic / openai / google-generativeai imported lazily per provider; return `None` on any failure.

### Adding a new job board

1. Write `_<board>_search(keyword, location, max_results, hours_old)` in `scraper.py` returning `_to_dataframe(jobs, "BoardName")`. Follow the existing pattern: multi-selector fallback lists for HTML parsing (sites change class names), `_get_with_retry()` for HTTP, randomized `time.sleep` between pages.
2. Register it in `SUPPORTED_SITES` and the `scraper_map` inside `search_jobs()`.
3. Add an entry to `PLATFORM_INFO` and (if country-specific) `COUNTRY_PLATFORMS` in `locations.py`.

### Scraping conventions

- Anti-blocking is central to this codebase: shared `_HEADERS` Chrome UA, exponential-backoff retry on 429/5xx, polite randomized delays, Playwright contexts hide `navigator.webdriver` and block image/font loads.
- Scrapers must never raise to the caller — catch errors, log via the module `logger`, and return an empty DataFrame (`search_jobs` also wraps each scraper future in try/except).
