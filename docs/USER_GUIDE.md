# SCT — User Guide

**SCT (Simple Crawler Tool)** is a local SEO crawler and auditor. It crawls a website,
extracts on‑page SEO data, runs technical analyzers, optionally joins Google Search Console
/ Google Analytics 4 data, and produces downloadable reports (HTML/PDF/Excel/CSV/JSON) — all
on your own machine. No data leaves your computer unless you explicitly enable an integration.

This guide is task‑oriented. For architecture and internals, see `docs/DOCUMENTATION_AR.md`.

---

## 1. Installation

Requires **Python 3.10+**.

```bash
# from the project root
python -m pip install -r requirements.txt

# only needed for PDF reports and JavaScript rendering:
playwright install chromium
```

Notes:
- The web UI needs `fastapi`, `uvicorn`, `jinja2`, `python-multipart` (included in
  `requirements.txt`).
- GA4 integration additionally needs `google-analytics-data` (commented in requirements —
  install it only if you use GA4).
- The AI advisor needs **no extra packages** (it uses `requests`).
- **Auto-install of requirements:** when the tool needs an optional library that isn't
  installed (e.g. `openpyxl`, `playwright`, Google libs) it installs it **automatically
  (notifying, no prompt)**, restricted to a known allowlist of the tool's optional deps (no
  arbitrary packages). Set `SCT_NO_AUTO_INSTALL=1` to disable and install manually.

---

## 2. Quick start

### Option A — Web interface (recommended)

```bash
python webapp/run.py
# then open http://127.0.0.1:8000
```

Enter a URL, press **Start**, and watch live progress. When it finishes, download buttons
appear (HTML, PDF, Excel, JSON, CSV, XML) plus an **Explore results** view.

To expose it on your LAN: `python webapp/run.py --host 0.0.0.0 --port 9000`.

### Option B — Command line

```bash
python main.py --url https://example.com --mode audit
```

Useful flags:

| Flag | Meaning |
|------|---------|
| `--url <url>` | Override the start URL from `config.yaml` |
| `--mode audit\|competitor\|compare` | Crawl mode (default `audit`) |
| `--config <path>` | Use a different config file (default `config.yaml`) |
| `--sync` | Use the synchronous crawler (slower; for debugging) |
| `--analyze-only` | Skip crawling; re‑analyze an existing database |
| `--no-resume` | Start fresh (ignore saved progress) |
| `--skip-external` | Skip external‑link checking (faster) |
| `--clear-cache` | Clear the API cache and exit |

---

## 3. The web interface, step by step

1. **URL** — the site to crawl.
2. **Mode** — `audit` (your own site), `competitor`, or `compare` (multiple sites).
3. **Seed strategy** — how the crawl discovers pages:
   - **homepage** — start at the homepage and follow links (breadth‑first).
   - **sitemap** — crawl URLs declared in the sitemap.
   - **hybrid** (default) — homepage + links first, then sitemap URLs as deferred seeds.
4. **Limits & speed** — max pages (0 = unlimited), max depth, and a speed slider
   (gentle → max). A server‑side floor protects target sites.
5. **What to collect** — grouped checkboxes (meta, headings, links, images, canonical,
   hreflang, pagination, Open Graph, Schema.org, HTTP headers, mixed content, resource
   inventory). Enable only what you need for faster crawls.
6. **Output formats** — HTML, PDF, Excel, CSV, JSON, XML.
7. **Report type** — Expert (full technical), Client (short, plain‑language with a health
   score), or Both.
8. **Advanced settings** (collapsible) — integrations, AI advisor, custom extraction,
   analysis thresholds, and "check resource HTTP status".

During the crawl, the job page shows the live phase, an elapsed‑time counter, page counts,
and a **Stop** button. Stopping still exports the partial results so you can download them.

---

## 4. Crawl modes

- **audit** — full SEO audit of a single site (default).
- **competitor** — crawl a competitor for comparison data.
- **compare** — crawl several sites (`sites_to_compare` in config) and produce a comparison
  summary; each site also gets its own folder and `metrics.json`.

---

## 5. Output files

For the UI, everything lands under `webapp_jobs/<job_id>/output/`. For the CLI, under the
configured output directory.

- **`report_<site>_<ts>.html` / `.pdf`** — the formatted report (PDF needs Playwright).
  In `both` mode you get `..._client.*` and `..._expert.*`.
- **`audit_<site>_<ts>.xlsx`** — multi‑sheet Excel (good for client delivery).
- **`audit_<site>_<ts>.json`** — the complete audit archive (every dataset).
- **`csv/`** — one file per dataset: `pages`, `inlinks`, `outlinks_external`, `all_links`,
  `images`, `headings`, `schema`, `redirects` (+ `redirect_chains/loops/issues`), `headers`,
  `seo_issues`, `duplicates`, `orphans`, `thin_content`, `pages_4xx/5xx/404_with_inlinks`,
  `images_no_alt/no_dimensions` (complete, not capped), `url_issues`, `canonical_issues`,
  `security_issues`, `pagination` / `pagination_issues`, `hreflang_issues`, `resources`
  (+ `resource_issues`, `resource_status`), `custom_extraction`, `excluded_urls`,
  `gsc_pages/gsc_queries`, `ga4_landing_pages/ga4_channels`, `priority_opportunities`,
  `ai_recommendations`, `lighthouse_import`, `js_diff`, and (when integrations are enabled)
  `pagespeed_audits` / `pagespeed_network_requests` / `pagespeed_js_treemap` /
  `pagespeed_failed_audits` (deep Lighthouse tables), `keyword_cannibalization`,
  `internal_link_opportunities`, `gsc_index_status` (URL Inspection), `crux_history`.
- **`sitemap.xml`** — generated from indexable pages when `output.generate_sitemap` is on.
- **`metrics.json`** — counters, timings, and a "slowest phases" summary.

**How outputs are organized (and why they stay reasonably sized):**
- **`csv/` is the complete data home** — many small, single‑purpose files with descriptive
  names (each focused on one thing). This is where the full data lives, including the link
  graph (`all_links.csv`), which is naturally the largest file on big sites.
- **Excel** is a bounded client workbook (sheets capped at 50,000 rows) — a readable
  deliverable, not a raw dump.
- **JSON** keeps pages + analyses + summaries; it does **not** embed the giant raw
  links/images/headings arrays by default (`output.json_full: true` to include them).
- **XML is off by default** — it only duplicates the CSV data. Enable it only if a downstream
  tool needs XML; it's capped by `output.xml_max_rows`.
- For genuinely huge sites, set a **page limit** to keep total output small. No information is
  lost by the defaults above — everything is in the CSV files.

**Downloading outputs:** the job page lists every produced file grouped by type (Reports,
Excel, Archive, CSV data, XML) with a clear label and size. You can download any file
individually, grab **everything as one ZIP** ("Download all"), or tick a subset and
"Download selected (ZIP)".

**Explore results** (`/jobs/<id>/explore`) lets you filter/sort/search pages in the browser
and download the filtered set as CSV.

### What each file contains

**Main deliverables**

| File | Contents |
|------|----------|
| `report_*.html` / `.pdf` | The formatted, shareable report (sections depend on the chosen audience). |
| `audit_*.xlsx` | The same datasets as multi-sheet Excel for client delivery. |
| `audit_*.json` | The complete machine-readable archive of every dataset (the report is built from this). |
| `metrics.json` | Run metrics: counters, per-phase timings, and the slowest phases. |

**Core data (`csv/`)**

| File | One row per… / Contents |
|------|--------------------------|
| `pages.csv` | Each crawled page — URL, final URL, status, content type, size, depth, title (+length), meta description (+length), robots, canonical, H1 count, word count, indexability, pagination, etc. |
| `all_links.csv` | Every discovered link (from → to, anchor text, internal/external, nofollow). |
| `inlinks.csv` | Internal links only (which page links to which). |
| `outlinks_external.csv` | Links pointing to external domains. |
| `images.csv` | Every image occurrence — page, src, alt, has-alt, dimensions, format, lazy-loading. |
| `headings.csv` | Every heading H1–H6 — page, tag, level, text, length, order. |
| `schema.csv` | Schema.org entries — page, format (JSON-LD/microdata), type, name. |
| `headers.csv` | HTTP/security response headers per page. |
| `redirects.csv` | Redirect hops — from, to, status code. |

**Issues & analysis (`csv/`)**

| File | Contents |
|------|----------|
| `seo_issues.csv` | All issues aggregated by type and severity (Critical/High/Medium/Low) with affected counts. |
| `duplicates.csv` | Duplicate titles / descriptions / H1 / content groups. |
| `orphans.csv` | Pages with no internal inlinks (orphaned). |
| `thin_content.csv` | Pages below the word-count / text-ratio threshold. |
| `pages_4xx.csv` / `pages_5xx.csv` | Pages returning 4xx / 5xx. |
| `pages_404_with_inlinks.csv` | 404 pages that are linked internally, plus the pages linking to them. |
| `images_no_alt.csv` | All images missing an `alt` attribute (complete, not capped). |
| `images_no_dimensions.csv` | All images without explicit width/height (CLS risk). |
| `url_issues.csv` | URL hygiene — too long, uppercase, underscores, tracking params, too many params, non-ASCII. |
| `canonical_issues.csv` | Canonical problems — to non-200/non-indexable/external targets, loops, chains. |
| `security_issues.csv` | Missing/weak security headers, non-HTTPS pages, mixed content. |
| `pagination.csv` | Paginated pages with their `rel=next`/`rel=prev` targets. |
| `pagination_issues.csv` | Broken pagination sequences, next/prev to 4xx/noindex, non-self canonical on paginated pages. |
| `hreflang_issues.csv` | Hreflang problems — non-reciprocal (return-link), points to 404/noindex, invalid format, missing x-default/self-reference. |
| `resources.csv` | Every page resource (CSS/JS/images/fonts/media/iframe) — type, internal/external, mixed content. |
| `resource_issues.csv` | Mixed-content and broken resources. |
| `resource_status.csv` | HTTP status per resource (only when "check resource status" is enabled). |
| `custom_extraction.csv` | Values pulled by your custom CSS/regex rules. |
| `excluded_urls.csv` | URLs that were not crawled and the reason (robots / filters / max depth / SSRF). |

**Integrations & report (`csv/`)** — only when the relevant integration is enabled

| File | Contents |
|------|----------|
| `gsc_pages.csv` / `gsc_queries.csv` | Search Console clicks / impressions / CTR / position per page and per query. |
| `gsc_index_status.csv` | Real per-URL index status from URL Inspection (verdict/coverage/canonical) — when `gsc.url_inspection` is on. |
| `keyword_cannibalization.csv` | Queries where multiple pages compete (rank-splitting) — derived from GSC. |
| `internal_link_opportunities.csv` | Pages with high search impressions but few internal inlinks (link-building candidates). |
| `ga4_landing_pages.csv` / `ga4_channels.csv` | GA4 sessions / users / engagement for landing pages and channels. |
| `pagespeed_audits.csv` | Every Lighthouse audit (score/value/type) per page×strategy. |
| `pagespeed_failed_audits.csv` | Only failing audits (real problems) — safely filtered. |
| `pagespeed_network_requests.csv` | Every network request (size/status/protocol/priority/entity). |
| `pagespeed_js_treemap.csv` | Per-script JS bytes + computed unused-code %. |
| `crux_history.csv` | Core Web Vitals trend over time (p75) from CrUX History — when enabled. |
| `priority_opportunities.csv` | Pages ranked by impact × severity, with the top fix for each. |
| `ai_recommendations.csv` | AI advisor recommendations — title, why, action, priority. |
| `lighthouse_import.csv` | Imported performance / accessibility / best-practices / SEO scores (0–100). |
| `js_diff.csv` | Raw vs JavaScript-rendered differences — links, content, title, canonical, console errors. |

**`xml/`** — `pages.xml`, `links.xml`, `images.xml`, `schema.xml`, `seo_issues.xml` (the same
data in XML for tooling that prefers it).

> Files only appear when the matching data exists or the matching option/integration is
> enabled (e.g. no `ai_recommendations.csv` unless the AI advisor ran, no `pagination.csv`
> if the site has no `rel=next/prev`).

---

## 6. Reports: Client vs Expert

Choose with **Report type** (or `report.audience` in config):

- **Expert** — the full technical document: executive summary, priority opportunities, all
  issues by severity (with sample URLs), problem pages, search visibility (GSC), user
  behavior (GA4), redirects, pagination, hreflang, resource inventory, and Schema.org.
- **Client** — a short, non‑technical summary: an overall **health score/rating**, a plain
  executive summary, top opportunities, and the main issues — without deep technical tables.
- **Both** — produces two separate files; the job page shows separate download buttons.

You can also rebuild the report after a crawl from the job page (change language, client
name, audience, and whether to generate PDF).

---

## 7. Integrations (all optional, all off by default)

Enable from **Advanced settings → Integrations**. Keys/paths are stored only in the local
per‑job config and are never written to the repository. Secret keys are passed to the crawl
process via environment variables, not saved to disk.

| Integration | What it adds | What you provide |
|-------------|--------------|------------------|
| **Google Search Console** | Clicks / impressions / CTR / position per page & query + keyword cannibalization & internal-link opportunities | OAuth credentials file + verified site URL |
| **GSC — URL Inspection** (optional) | Real per-URL index status (`gsc.url_inspection`) — quota-capped by `inspect_max_urls` | Same GSC credentials |
| **Google Analytics 4** | Sessions / users / engagement for landing pages + channels | Service‑account JSON + property ID (needs `google-analytics-data`) |
| **PageSpeed API** | Performance/SEO scores + **deep Lighthouse tables** (audits/network/JS treemap/failed) | API key (or `PAGESPEED_API_KEY` in `.env`) |
| **CrUX History** (optional) | Core Web Vitals trend over time (`pagespeed.crux_history`) | Same PageSpeed key |
| **Lighthouse import** | Reads local Lighthouse JSON (no keys/internet) | A folder of Lighthouse `.json` files |
| **Ahrefs Webmaster (AWT)** | Imports AWT CSV exports (free backlinks/keywords for site owners) | A folder of CSV files |

When GSC/GA4 are enabled, the **Unified report** cross‑references technical issues with
traffic to produce **Priority Opportunities**
(`priority_score = traffic impact × issue severity`). Every issue also carries
**impact / effort / why-it-matters / how-to-fix / priority_score** to make it actionable.

### Extra run options (in `config.yaml`)
- **`site.platform_preset`** (`zid` | `salla` | `shopify` | `woocommerce`): adds recommended
  exclude patterns (cart/checkout/account) without clearing yours.
- **`crawl.adaptive_throttle.enabled`**: slows the crawl automatically on 429/5xx/slow
  responses and recovers (server-friendly, avoids blocks).
- **`output.generate_sitemap`**: generates a clean `sitemap.xml` from indexable pages.
- **`pagespeed.save_raw_json`**: saves the full raw Lighthouse report per page (source of the
  deep tables).

### Using a `.env` file for secrets (recommended)

Create a `.env` in the project root:

```
PAGESPEED_API_KEY=your_key
GA4_PROPERTY_ID=123456789
GA4_CREDENTIALS_FILE=./secrets/ga4.json
AI_API_KEY=your_ai_key
```

`.env` should be gitignored. The tool reads these as fallbacks.

---

## 8. AI advisor (optional)

The AI advisor reads the audit summary + top opportunities and returns an executive summary
plus prioritized, specific recommendations. It is **off by default**.

Enable from **Advanced settings → AI advisor**:

1. **Provider** — OpenAI (GPT), Google Gemini, DeepSeek, OpenRouter, Hugging Face, or a
   custom **OpenAI‑compatible** endpoint (for local models such as Ollama / LM Studio).
2. **API key** — pasted in the UI (passed via the `AI_API_KEY` env var; never written to
   disk or the repo) or set `AI_API_KEY` in `.env`.
3. **Model / base URL** — optional; leave blank to use the provider default. `base_url` is
   required only for a custom endpoint.
4. **Allow local/private endpoint** — leave **off** for cloud providers. Turn it **on** only
   for a trusted local model (e.g. `http://127.0.0.1:11434/v1`); internal/loopback endpoints
   are otherwise rejected as an SSRF safeguard.

Privacy: **no personal data (PII) is sent** — only page URLs, issue types, and aggregate
numbers. Output appears as an AI section in the report and as `ai_recommendations.csv`.
If the key/library is missing or the call fails, the crawl still completes normally.

---

## 9. Reading the log & diagnostics

- The UI shows live progress; for details open `webapp_jobs/<id>/run.log` (clean — no
  progress‑bar noise) or `webapp_jobs/<id>/logs/`.
- The end‑of‑crawl summary lists pages, failures, the per‑page status‑code distribution,
  links, images, and total size.
- **Transient fetch errors** (network/timeout that were retried) appear as a WARNING with a
  count; they are also in `metrics.json` (`crawler.fetch.errors`).
- **External links**: the summary separates `OK / Blocked (401/403/429) / Broken`. Blocked
  links are bot/rate‑limit blocks by the remote server, not real breakages.
- The job page's diagnostics panel summarizes errors/warnings/tracebacks from the log.

---

## 10. Stopping, resuming, partial results

- **Stop** during a crawl exports the partial CSV/JSON/Excel immediately so you can download
  results; the slow external‑link check and HTML/PDF are skipped (rebuild the report later
  from the job page).
- Crawl progress (visited URLs + queue) is persisted to SQLite, so re‑running resumes where
  it left off. Use `--no-resume` (CLI) or "Start fresh" (UI) to ignore saved progress.
- Completion status is explicit: `complete`, `partial`, `partial_max_pages`, `stopped`,
  or `failed`.

---

## 11. Troubleshooting

- **0 pages / everything failed** — check `run.log`; usually a network/DNS or encoding issue,
  or the start URL was rejected by the SSRF guard (use a public URL, or set
  `crawl.allow_private_hosts` for an internal site).
- **PDF not generated** — run `playwright install chromium`.
- **GA4 not working** — `pip install google-analytics-data`, then provide property ID and a
  valid service‑account file.
- **AI says unavailable** — missing API key, or an internal `base_url` was blocked (enable
  "allow local/private endpoint" only for trusted local models).
- **Slow crawl** — reduce max pages or raise the speed slider (the target site itself may be
  slow); use `--skip-external` to skip external‑link checks.
- **Stop didn't show downloads** — make sure you're on the current version (it handles the
  Windows stop signal and exports partial results).
- **Huge/unlimited crawl (gigabyte files, or results viewer hangs)** — on very large sites
  avoid "All pages" (0) or watch the size. By default `complete_audit.json` does **not**
  embed the huge raw arrays (links/images/headings — they're in CSV/Excel), keeping results
  light and fast to open. For a full archive set `output.json_full: true` (can be gigabytes).
  The Explore and Report‑rebuild pages refuse audit JSON larger than ~300 MB and point you to
  the CSV files.

---

## 12. Security & privacy

- Runs entirely locally; nothing is uploaded unless you enable an integration or the AI
  advisor.
- SSRF protection blocks crawling/redirecting to internal/loopback/metadata addresses
  (override per‑run with `crawl.allow_private_hosts`).
- CSV/Excel exports neutralize formula injection for safe opening in spreadsheet apps.
- Secret keys live in `.env` / local per‑job config (gitignored) and are passed to the crawl
  process via environment variables — never committed.
- No PII is collected from GA4 or sent to the AI provider.
