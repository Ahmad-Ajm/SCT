# Changelog

## Unreleased

### Added
- **Deep PageSpeed/Lighthouse tables** (from the raw report we already fetch, no extra API
  call): `pagespeed_audits.csv` (all ~150 audits), `pagespeed_network_requests.csv` (every
  request with size/status/protocol/priority/entity), `pagespeed_js_treemap.csv` (per-script
  bytes + computed unused %), and `pagespeed_failed_audits.csv` (only real failures —
  `scoreDisplayMode binary/numeric` and `score < 1`, with a `None`-safe filter). The big
  tables are excluded from the JSON archive (kept in CSV) to keep JSON light.
- **GSC insights** computed from data already fetched: `keyword_cannibalization.csv`
  (multiple pages competing for one query) and `internal_link_opportunities.csv` (pages with
  high search impressions but few internal inlinks, by joining GSC with the internal link
  score). No extra crawl or client involvement.
- **GSC URL Inspection** (optional, `integrations.gsc.url_inspection`, off by default): real
  per-URL index status/verdict/coverage via the URL Inspection API → `gsc_index_status.csv`,
  capped by `inspect_max_urls` to respect the daily quota.
- **CrUX History** (optional, `integrations.pagespeed.crux_history`, off by default): Core Web
  Vitals field-data trend over time (p75 per period) → `crux_history.csv`, using the existing
  PageSpeed key.
- **Sitemap generator** (`output.generate_sitemap`, off by default): clean `sitemap.xml` from
  indexable (200, self-canonical) pages, splitting into a sitemap index above 50,000 URLs.
- **Crawl comparison over time** (`analyzers.crawl_compare`): compare two audit runs of the
  same site → fixed / new / persisting issue types + page add/remove + totals delta.
- **Prioritized hints** on every SEO issue: `impact`, `effort`, `why_it_matters`,
  `how_to_fix`, and a `priority_score` (impact ÷ effort) — actionable client reporting.
- **Adaptive throttle** (`crawl.adaptive_throttle`, off by default): automatically slows the
  crawl on 429/5xx/slow responses and recovers as the site stabilizes.
- **E-commerce presets** (`site.platform_preset`: zid | salla | shopify | woocommerce): adds
  recommended exclude patterns (cart/checkout/account) without clearing yours; includes a
  platform detector.
- **Accessibility (axe-core) module** (`analyzers.accessibility`, optional): pure summarizer
  for axe results + a helper to run axe on a rendered Playwright page.
- **Auto-install of optional requirements** (`utils.auto_install`): when the tool needs an
  optional library it installs it automatically (notifying, no prompt), restricted to a known
  allowlist of the tool's optional deps; disable with `SCT_NO_AUTO_INSTALL=1`.
- Output files browser in the job page: a labelled, grouped list of **every** produced file
  (Reports / Excel / Archive / CSV data / XML) with human‑readable bilingual names and sizes.
  Each file downloads individually, **“Download all (ZIP)”** grabs everything in one click,
  and you can tick a subset and **“Download selected (ZIP)”**. New endpoints
  `/api/jobs/<id>/files`, `/download-file?rel=…`, and `/download-all[?only=…]` (all with
  path‑containment checks).
- AI advisor (optional, `integrations.ai`, off by default): provider-agnostic assistant
  (`requests`-only, no new dependency) that reads the audit summary + top opportunities and
  returns an executive summary plus prioritized, specific recommendations. Providers:
  **OpenAI, DeepSeek, OpenRouter, Hugging Face** (OpenAI-compatible `chat/completions`) and
  **Google Gemini** (`:generateContent`), plus a custom `openai_compatible` endpoint for
  local models (Ollama/LM Studio/gateways) via `base_url`+`model`. Pick the provider and
  enter the key from the UI advanced settings; the key is passed to the crawl process via
  the `AI_API_KEY` env var and never written to the job config or the repo. No PII is sent —
  only page URLs, issue types, and aggregate numbers. Output appears as an AI section in the
  report (client + expert) and as `ai_recommendations.csv` + a block in the JSON. Degrades
  gracefully when the key/library is missing or the call fails.
- Two report audiences (`report.audience`: `client` | `expert` | `both`): the **client**
  report is a short, plain-language summary with an overall health score/rating and the
  top issues (no deep technical tables); the **expert** report is the full technical
  document and now also includes dedicated Pagination, Hreflang, and Resource-inventory
  sections. `both` produces two files (`report_*_client.*` and `report_*_expert.*`).
  Selectable from the UI (start form and report-rebuild form) with separate download
  buttons. The report's redirect section is also fixed (the JSON now carries
  `redirect_data`, so redirects/pagination/resource-status render in the report).
- Pagination (`rel=next`/`rel=prev`): new `pagination_extractor` + `pagination_analyzer`
  detect paginated sequences and flag broken reciprocity (A.next=B but B.prev≠A),
  next/prev targets that are 4xx/5xx or noindex, and non-self canonicals on paginated
  pages → `pagination.csv` + `pagination_issues.csv`. New page columns
  (`pagination_next`/`pagination_prev`/`is_paginated`); enabled via
  `extraction.extract_pagination` (on by default) and the UI collection group.
- Per-resource HTTP status checking (optional, `extraction.check_resource_status`, off by
  default): reuses the external-link checker to fetch each unique page resource
  (CSS/JS/images/fonts/media/iframe) and reports its status → `resource_status.csv`.
  Toggle from the UI advanced options.
- Hreflang issues export: the existing reciprocity/return-link validation (non-reciprocal,
  points-to-404, points-to-noindex, invalid format, missing self/x-default, duplicates,
  lang mismatch) is now written to `hreflang_issues.csv` for download.
- Unified report combining Technical SEO + Search Visibility (GSC) + User Behavior (GA4),
  plus a **Priority Opportunities** section that cross-references technical issues with
  clicks/impressions/sessions to rank what to fix first. New GA4 connector
  (`integrations/ga4_api.py`, optional `google-analytics-data`), join + scoring engine
  (`reporting/`), and exports `gsc_pages.csv`, `gsc_queries.csv`, `ga4_landing_pages.csv`,
  `ga4_channels.csv`, `priority_opportunities.csv`. GSC/GA4 configurable from the UI.
- Resource Inventory: collect CSS/JS/images/fonts/media/iframes per page (type, internal/
  external, mixed content) → `resources.csv` + `resource_issues.csv` + summary; enabled via
  `extraction.extract_resources` and the UI collection group.
- Async JavaScript rendering (Playwright): modes `all`/`sample`/`on_empty_content`, raw↔rendered
  diff (links/content/title/canonical/console errors) → `js_diff.csv`; rendered HTML is used
  for extraction and link discovery. Gracefully skipped if Playwright is not installed.
- UI "Advanced settings": configure integrations (GSC, PageSpeed API key, Lighthouse
  folder, AWT), custom-extraction rules (visual add/remove editor), and analysis thresholds
  directly from the web interface (no manual YAML editing). Keys are stored only in the
  local per-job config.
- Security headers analyzer (HTTPS/HSTS/CSP/X-Frame-Options/X-Content-Type-Options/
  Referrer-Policy/Permissions-Policy/mixed content) → `security_issues.csv` + JSON; new DB
  columns persisted for the missing security headers.
- Custom Extraction (`custom_extraction` config): CSS selector (text/attr/html) and regex
  rules → `custom_extraction.csv` + JSON (sync and async crawlers).
- Redirect detail reports: `redirect_chains.csv`, `redirect_loops.csv`, `redirect_issues.csv`.
- Optional Lighthouse/PageSpeed JSON import (no keys/internet): reads a local folder →
  `lighthouse_import.csv` (performance/accessibility/best-practices/seo, 0–100).
- Visual results explorer (`/jobs/<id>/explore`): client-side filter/sort/search over pages
  (status, indexability, depth, content type, missing H1/meta/canonical/title) + filtered CSV.
- External tools guide docs (EN+AR) for Lighthouse/axe-core/OWASP ZAP/GSC + example READMEs.
- Crawl seed strategy `crawl.seed_strategy`: `homepage` (start page + link BFS),
  `sitemap` (legacy flood), `hybrid` (default: homepage+links first, sitemap as deferred
  seeds). Selectable in the UI.
- Web UI English/Arabic language toggle (i18n, persisted in localStorage).
- Clear completion status: `complete` / `partial` / `partial_max_pages` / `stopped` /
  `failed` (instead of always "done").
- "Excluded URLs" report (excluded_urls.csv + JSON) with reasons (robots/filters/max_depth/ssrf).
- Image stats now report unique-by-src counts alongside occurrences (avoids inflation).
- `analysis.url_flag_non_ascii` (default off): non-ASCII URLs are informational, not an
  issue (suits Arabic sites).
- `observability.slow_call_summary` (default on): slow calls are summarized at the end
  instead of one WARNING per call.
- "All pages" checkbox (max_pages = 0 = unlimited) and crawl-speed slider in the UI.
- Integrated local Web UI (FastAPI + HTMX + SSE): configure settings, set URL, choose
  mode, start/stop crawls, live progress monitoring, and report downloads (`webapp/`).
- Grouped collection checkboxes (select all/partial/all groups), output-format selection,
  and PDF/HTML report formatting options in the UI.
- Crawl-speed slider (gentle→max) mapping to delay/concurrency, with a server-side floor
  (min delay 0.1s, max concurrency 20) to protect sites.
- Live elapsed-time counter on the job page (ticks while running, freezes on stop/finish).
- Per-job self-contained logs under `webapp_jobs/<job_id>/logs/` and rotating log files
  honoring `max_log_size_mb`.
- Customizable HTML and PDF reports (Arabic/RTL via Playwright): `html`/`pdf` output
  formats and `exporters/html_exporter.py`, `pdf_exporter.py`, `report_builder.py`.
- Reliable async resume: crawl progress (visited + queue) persisted to SQLite and
  restored on re-run.
- SSRF protection (`is_safe_remote_url`) applied to crawl URLs, redirect targets, and
  sitemap/robots-declared URLs; new `crawl.allow_private_hosts` option.
- Glob support in `filters` patterns (in addition to substring matching).
- Configurable thin-content thresholds (`thin_content_critical_threshold`,
  `text_ratio_threshold`).
- Regression test suite covering the fixes below.

### Fixed
- Full‑application audit pass (correctness, security, performance) — applied across all parts:
  - **Duplicate detector**: title/meta‑description now coerced via `str(...)` before
    `.strip().lower()` so non‑string values from the DB (e.g. numeric titles) can’t crash
    the analysis.
  - **Internal‑link score (PageRank)**: repeated nav/footer links between the same two pages
    are now de‑duplicated to a single `(from, to)` edge before the power iteration, so the
    score is no longer artificially inflated by links that appear on every page (the
    docstring promised this dedup but it wasn’t implemented).
  - **Near‑duplicate (LSH)**: auto‑corrects the band count so the candidate guarantee
    actually holds (`bands > max_distance`, and `bits % bands == 0`) instead of silently
    missing similar pairs; asserts the invariant.
  - **SimHash**: skipped (emit empty fingerprint) for very short text (< 10 words), whose
    fingerprint is unstable and produced false near‑duplicate matches.
  - **PageSpeed API**: the API key is now passed via `params=` (never formatted into a URL
    string that could be logged), error bodies that aren’t valid JSON no longer raise, and
    transient failures (429/5xx/timeout) get a short exponential‑backoff retry.
  - **robots.txt**: downloaded with a streaming 2 MB size cap so a huge/compressed response
    can’t exhaust memory.
  - **Google OAuth** (`google_auth`): token filenames are scope‑aware and a saved token that
    doesn’t cover the requested scopes triggers re‑consent; the interactive browser flow is
    gated by `SCT_NONINTERACTIVE` (set for the background crawl process) so it can never hang
    a non‑interactive run waiting for consent.
  - **Resource status**: `status_code` coerced from string before the `>= 400` check, so
    broken resources stored as text are still counted.
  - **GSC pagination**: `rowLimit` clamped to `max(1, …)` to avoid a zero/negative limit on
    the final page.
  - **Web UI**: `/api/google/upload` rejects payloads > 64 KB (client‑secret files are tiny);
    `/api/test/ga4` checks `client_secret.json` exists (parity with the GSC test); the
    “Download all (ZIP)” build runs in a thread executor so large archives don’t block the
    event loop; XML export has a hard per‑file safety cap inside `XMLExporter`; and
    `build_report_from_json` skips files larger than 500 MB instead of loading them into RAM.
- Large‑crawl output blowup & post‑run hang (found on an unlimited 11,937‑page crawl that
  produced a **1.7 GB `complete_audit.json`** and **1.15 GB `links.xml`**):
  - `complete_audit.json` no longer embeds the huge raw arrays (links/images/headings — here
    ~990k/303k/225k rows) by default; those live in CSV/Excel/XML. The JSON keeps pages +
    all analyses + summaries. Set `output.json_full: true` to embed everything.
  - The HTML/PDF report is now built from in‑memory data instead of **re‑loading the
    multi‑GB JSON** (`json.load` of 1.7 GB was the “preparing reports forever” hang). The
    report never needed the raw arrays — only pages + analyses.
  - XML export is capped per dataset via `output.xml_max_rows` (default 50,000; 0 = no cap)
    so `links.xml`/`images.xml` can’t reach gigabytes, **and XML is now off by default**
    (it duplicates the CSV data — no extra information; add it back per‑run if you need it).
    Net effect on the 11,937‑page example: total output drops from ~3 GB to a few hundred
    MB, dominated by the genuine link‑graph CSV (`all_links.csv`) — no information lost.
  - The web UI’s **Explore** and **Report‑rebuild** endpoints now refuse to load an audit
    JSON larger than ~300 MB (returns a clear message pointing to the CSV) instead of
    hanging the server on legacy huge files.
- Deep audit round (security/perf/correctness):
  - **Security:** the AI advisor now validates `base_url` against the SSRF guard before
    sending the request (and the Bearer/API key) — internal/loopback/metadata endpoints are
    rejected unless `integrations.ai.allow_private` is set (for local models like Ollama).
    The **Gemini** key moved from the URL query string to the `x-goog-api-key` header (keys
    in URLs leak into proxy/server logs). The crawl **start URL** is now SSRF-checked in
    `configure_target_site` (this also covers the initial `robots.txt` fetch, which ran
    before the per-URL guard).
  - **Performance:** table columns are cached instead of running `PRAGMA table_info` ~4×
    per saved page; `redirect_analyzer` de-duplicates shared internal hops and dropped an
    O(n²) `hop not in list` fallback; per-page `import` of the custom/resource extractors
    moved to module top; `normalize_url`'s tracking-param set hoisted to a module constant.
  - **Correctness/log:** `status_codes` are now tallied **once per saved page** instead of
    on every redirect hop and retried attempt, so the crawl summary's status distribution
    matches the page count (no more 523-vs-512). Broken-link results (4xx/5xx/404-with-
    inlinks) are now logged. In `both` report mode the generic html/pdf download no longer
    arbitrarily resolves to a client/expert variant. AI response parsing hardened against
    empty/malformed completions.
- Post-crawl review (500-page audit): `images_no_alt.csv` / `images_no_dimensions.csv`
  were capped at 100 rows (the analyzer's report/JSON sample leaked into the CSV); the CSV
  exporter now builds the **full** lists from the raw images so the actionable files are
  complete. The crawl log now surfaces **transient fetch errors** (network/timeout retries)
  as a WARNING with the count — previously 43 retried errors were invisible and the UI
  diagnostics showed 0 warnings. The external-links summary now prints
  `OK / Blocked (401/403/429) / Broken` separately instead of folding blocked links into
  "Working". And `run.log` is no longer bloated by tqdm progress bars: the progress bar is
  disabled when running under the web UI (subprocess, `SCT_PROGRESS_FILE` set) or any
  non-TTY, so the per-job log stays clean (the UI uses `progress.json` for live progress).
- Code audit round 2 (deferred items): DB-backed crawler getters (`get_pages`/`get_links`/
  …) are now memoized per run — after a crawl the DB is stable, so they build the
  materialized list once and hand each caller a fresh shallow copy instead of re-running
  `SELECT *` + rebuilding dicts in every phase (analysis/export/integrations/report).
  Per-job log summary (`_summarize_run_log`) counts errors/warnings/critical by the actual
  log level (`| LEVEL |`) instead of substring-matching the words anywhere in the text (an
  INFO line mentioning "ERROR" no longer inflates the error count). Intermediate redirect
  responses in `HTTPClient` are now closed before the next hop (with `stream=True` an
  unconsumed redirect kept the connection open). Compare mode resets monitoring per site
  and writes each site's `metrics.json` into its own folder (multi-site runs no longer
  conflate counters/timings).
- Code audit round: `broken_links` 404-with-inlinks now uses a one-pass index + normalized
  matching (was O(n²) and missed normalized targets); SSRF guard added to `logo_url` before
  PDF rendering (headless browser fetched it) and to redirect targets in `HTTPClient` (sync
  path); PageSpeed API key passed via env, no longer written to the per-job config file;
  custom-extraction skips `str(soup)` unless a regex rule needs it; SSE stream no longer
  hangs for unknown jobs; `job_id` format validation + download path containment under the
  jobs dir; `from typing import Any` added to webapp/app.py.
- Manual stop produced no downloadable results on Windows: the UI sent `CTRL_BREAK_EVENT`
  (SIGBREAK) but the crawler only caught SIGINT/SIGTERM, so the process died abruptly
  before exporting. The crawler now also catches SIGBREAK; on manual stop it skips the
  slow external-link check and HTML/PDF report, exports the partial CSV/JSON/Excel, and
  exits cleanly so the download buttons appear (the report can be rebuilt afterwards).
- UI looked "stuck" after the crawl phase: the timer kept ticking with frozen counters
  during the (silent) post-crawl phases (external links, export). The crawler now emits
  phase progress (`analyzing` / `checking_external_links` / `exporting`) and a final
  `complete` / `partial_max_pages` status, so the monitor shows the live phase, the timer
  stops when the job actually finishes, and the results panel appears. Download buttons
  now carry an explicit "Download" label.
- Unlimited crawl (`max_pages=0`, the "All" option) broke every worker with
  `TypeError: bool() undefined when iterable == total == None`: `if self.progress_bar:`
  invoked tqdm's `__bool__` on a `total=None` bar. Now uses `is not None`. The crawl was
  actually fetching pages but progress never updated (stuck at "starting").
- External-link checker reported bot-blocked sites as broken: `401/403/429` (e.g. every
  twitter.com share link → 403) were counted as broken. Now classified as "blocked", not
  "broken" (real broken count dropped from 512 → 5 on a sample crawl).
- Crawl order ignored the homepage and link discovery: all sitemap URLs were enqueued
  before the start URL, so with a page limit the crawler only fetched sitemap pages
  (depth 0) and never crawled the homepage or followed links. Now the homepage + BFS link
  graph are crawled first, with sitemap URLs pulled as deferred seeds afterward.
- PDF generation failed inside the crawl's asyncio loop (`Playwright Sync API inside the
  asyncio loop`) — now runs in a worker thread.
- Report/Excel/JSON deliverables are named with site + date-time
  (`audit_<slug>_<ts>.xlsx`, `report_<slug>_<ts>.html/.pdf`).
- Every async fetch crashed with `TypeError: event() got multiple values for argument
  'status'` (pre-existing) — `event()` calls and `span()` reserved-attr collisions fixed
  and hardened, so 0-crawled/all-failed runs no longer happen.
- `aiohttp` failed to decode brotli (`Can not decode content-encoding: br`) — the crawler
  no longer advertises `br` in `Accept-Encoding` (uses gzip/deflate).
- Resume snapshot rewrote the full queue too often (heavy I/O) — larger interval and
  delta-only visited writes.
- Analyzers crashed on database-backed dict rows (default audit run) — now dict/object safe.
- Async crawler could hang at `queue.join()` when `max_pages` was reached with items still
  queued — termination reworked (no hang).
- Re-runs duplicated links/images/headings/schema/redirects — now delete-then-insert per page.
- Microdata Schema.org entries were never field-validated — now validated.
- `sitemap_diff` received only the last sitemap's URLs — now accumulated and persisted.
- Redirect handling: robots checked on redirect targets, unified sync/async semantics,
  chains ordered by following links, `internal_redirects` populated.
- Excel export no longer dropped silently on long strings or null status codes.
- CSV/Excel formula-injection neutralization for client-facing exports.
- `normalize_url` resolves `.`/`..` segments; `is_internal_url` strips only a leading `www.`.
- gzip sitemap decompression is now size-capped (decompression-bomb protection).
- Graceful Ctrl+C / SIGTERM for the async crawler (saves state).
- `format_duration` no longer renders `60s`; restricted DB JSON decoding to known columns;
  `defusedxml` confirmed in requirements; GSC token written with `0600`.

### Changed
- Added detailed observability and `metrics.json` output.
- Improved `--analyze-only` behavior for database-backed analysis.
- Open-source roadmap and project governance files.
- Corrected overstated audit claims in docs (23 issue types, not "29+").
