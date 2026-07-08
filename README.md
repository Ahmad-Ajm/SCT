# SCT — Simple Crawler Tool

[![CI](https://github.com/Ahmad-Ajm/SCT/actions/workflows/ci.yml/badge.svg)](https://github.com/Ahmad-Ajm/SCT/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Docs: AR + EN](https://img.shields.io/badge/docs-AR%20%2B%20EN-brightgreen.svg)](README_ar.md)

> **A local-first technical SEO crawler and site auditor — written in Python, driven from a browser UI, with everything running on your own machine.**

SCT crawls a website, extracts its on-page SEO data, runs a full battery of technical analyzers, optionally joins Google Search Console / Analytics 4 / PageSpeed data, and produces downloadable reports (HTML / PDF / Excel / CSV / JSON / XML). No data ever leaves your computer unless you explicitly enable an integration.

It started as a lightweight alternative for technical SEO checks and grew into a multi-mode crawler with async crawling, SQLite storage, a transparent fix-prioritization engine, an interactive link-graph view, and customizable client reports (including Arabic / RTL).

Arabic documentation: [README_ar.md](README_ar.md).

---

## Table of contents

- [Why SCT](#why-sct)
- [Key features](#key-features)
- [Quick start](#quick-start)
- [Screenshots](#screenshots)
- [Platform presets](#platform-presets)
- [Integrations](#integrations)
- [Output formats](#output-formats)
- [Documentation](#documentation)
- [Requirements](#requirements)
- [License & contributing](#license--contributing)

---

## Why SCT

- **Runs entirely locally.** Bind to `127.0.0.1`, crawl, audit, and export — nothing is uploaded unless you turn on an integration.
- **One-click launch.** `START.bat` / `START.ps1` / `start.sh` detect Python, install requirements on first run, open the browser, and print the local auth token.
- **Honest, actionable output.** Every issue carries impact, effort, why-it-matters, how-to-fix, and a priority score — not just a raw list of problems.
- **Built for real sites.** Two-phase crawling, adaptive throttling, platform presets, and crash-safe resume keep large stores and blogs manageable.
- **Arabic-first friendly.** Correct UTF-8 handling, an RTL UI, Arabic reports, and full bilingual documentation.

---

## Key features

### Crawling

- Async crawler with configurable concurrency and crawl delay; a synchronous crawler is available as a fallback / debugging mode.
- SQLite-backed crawl storage for large sites, with **crash-safe resume** (no duplicate rows) and explicit completion states (`complete` / `partial` / `partial_max_pages` / `stopped` / `failed`).
- **Three seed strategies** — homepage-first (breadth-first), sitemap-first (wide product coverage), or hybrid (default).
- **Two-phase crawl:** Phase 1 classifies discovered URLs on the fly and defers budget-wasting patterns (deep pagination, auth/redirect wrappers, filter-combination explosions); a panel then lets you review what was set aside and optionally run Phase 2 on those URLs.
- **Adaptive throttle** that slows automatically on 429 / 5xx / slow responses and recovers.
- `robots.txt` respect (toggleable), HTTPS certificate verification controls, and configurable retries.
- **User-Agent presets** (default visitor, Googlebot, Googlebot Mobile, Bingbot, or custom) to reproduce Cloudflare / WAF bot-blocking issues.
- **Optional JavaScript rendering** (Chromium via Playwright) with a raw-vs-rendered diff (links, content, title, canonical, console errors).
- Speed slider (gentle → max) with a server-side floor to protect target sites.

### Analysis

- On-page SEO: titles, meta descriptions, headings (H1–H6), canonical tags, robots directives, Open Graph, pagination (`rel=next/prev`), and word counts.
- Duplicate title / description / H1 / content detection, plus **near-duplicate detection** (SimHash + LSH).
- **Thin-content** checks against configurable word-count / text-ratio thresholds.
- **Broken internal link** analysis and external link status checks (with per-host sampling to stay fast).
- **Internal link scoring (PageRank)** and an **orphan-page finder** (pages with no internal inlinks).
- URL hygiene (length, case, underscores, tracking params, parameter count, non-ASCII) — with a non-ASCII toggle appropriate for Arabic sites.
- Canonical analysis (to non-200 / non-indexable / external targets, loops, chains).
- **Hreflang validation** (reciprocity / return-link, targets 404 / noindex, invalid format, missing x-default / self-reference).
- **Schema.org validation** (JSON-LD / microdata — type and name).
- **Security headers analyzer** (HSTS / CSP / X-Frame-Options and more), non-HTTPS detection, and **mixed-content** detection.
- **Resource inventory** (CSS / JS / images / fonts / media / iframes) with mixed-content flags and optional per-resource HTTP status checks.
- **Image analysis** — missing alt, missing dimensions (CLS risk), format, and lazy-loading.
- **Optional accessibility audit** (axe-core / WCAG) with per-page violation counts and by-impact breakdown (requires JS rendering).
- **Custom extraction** — pull any value with CSS or regex rules.
- **Priority Engine v2 + Action Board:** a transparent multi-factor per-page score (severity × impact × ease × confidence) with page-type and ease/owner classification, grouped into *Do now / Needs developer / Needs platform / Needs content / Do later / Low impact*.
- **Crawl-over-time comparison** — pick two runs and see fixed / new / persisting issues.
- **Log analyzer** — upload an Apache/Nginx access log to see Googlebot crawl budget per URL (200 / 3xx / 404 / 5xx).

### Integrations (all optional, all off by default)

- **Google Search Console** — clicks / impressions / CTR / position per page and query, plus derived **keyword cannibalization** and **internal-link opportunities**.
- **GSC URL Inspection** — real per-URL index status (verdict / coverage / canonical), quota-capped.
- **Google Analytics 4** — sessions / users / engagement for landing pages and channels.
- **PageSpeed Insights API** — performance / SEO scores plus **deep Lighthouse tables** (all audits, network requests, JS treemap, failed audits).
- **CrUX History** — Core Web Vitals trend over time (p75).
- **Lighthouse import** — read a folder of local Lighthouse JSON files (no keys, no internet).
- **Ahrefs Webmaster Tools (AWT) import** — free backlinks / keywords CSV for site owners.
- **Backlinks API (live)** — referring domains and top external links from Ahrefs API v3 or Majestic OpenApp.
- **AI advisor** — an optional executive summary and prioritized recommendations from OpenAI, Google Gemini, DeepSeek, OpenRouter, Hugging Face, or any OpenAI-compatible endpoint (including local models such as Ollama / LM Studio). No personal data is sent — only URLs, issue types, and aggregate numbers.

When GSC / GA4 are enabled, a **Unified report** cross-references technical issues with real traffic to produce **Priority Opportunities** (`priority_score = traffic impact × issue severity`).

### Reports

- **Expert** report — the full technical document (executive summary, priority opportunities, all issues by severity with sample URLs, problem pages, search visibility, user behavior, redirects, pagination, hreflang, resource inventory, Schema.org).
- **Client** report — a short, plain-language summary with an overall health score / rating.
- **Both** — produces two separate files.
- **On-demand generation** — raw data (CSV / JSON) is always written after a crawl; HTML / PDF / Excel / XML are generated on demand from the job page. You can **rebuild** a report afterward, changing language, client name, audience, and whether to render a PDF.
- Customizable HTML / PDF reports with **Arabic / RTL support** (PDF via Playwright).

### Web UI

- Integrated local web UI (**FastAPI + HTMX + SSE**) with three tabs: **Crawl**, **Integrations & AI**, and **Advanced**.
- Live crawl monitoring — phase, elapsed time, and six live counters (pages, queue, failed, external checked, pages/sec, seconds), each with an explanatory tooltip.
- **Explore results** — filter / sort / search crawled pages in the browser and export the filtered set as CSV.
- **Action Board** — fix priorities grouped and filterable, with a per-URL slide-out panel joining crawl data + GSC + URL Inspection + GA4 + PageSpeed + priority + accessibility in one view.
- **Link graph view** — a path-segment tree colored by status code, depth / status histograms, and a force-directed internal-link map (capped for responsiveness).
- **Compare before/after** and **Log analyzer** pages.
- **Stop** exports partial results immediately so nothing is lost.
- Recent-jobs list with per-job artifacts under `webapp_jobs/<job_id>/`.

### Safety & operations

- **Local auth token** — every `/api/*` route requires a per-install token at `~/.sct/local_token` (mode `0600`); the launcher prints it, and scripts pass it as a bearer token or `?token=` query param. Liveness (`/health`) and readiness (`/readyz`) endpoints are exempt.
- **SSRF protection** — blocks crawling / redirecting to internal / loopback / metadata addresses (overridable per run).
- **Formula-injection neutralization** for safe CSV / Excel opening, and a **gzip-bomb cap**.
- Secret keys live in `.env` / local per-job config (gitignored) and are passed to the crawl process via environment variables — never committed.
- Detailed logs and a `metrics.json` observability output (counters, per-phase timings, slowest phases). GitHub Actions CI.

---

## Quick start

### Fastest path — one click

- **Windows:** double-click `START.bat`.
- **Windows (PowerShell):** right-click `START.ps1` → *Run with PowerShell*.
- **macOS / Linux:** `./start.sh`.

The launcher detects Python, installs requirements on first run, opens `http://127.0.0.1:8000`, and prints the local auth token for scripts. `STOP.bat` ends the server on Windows.

### Manual (advanced)

```bash
python -m pip install -r requirements.txt
python main.py --help
python main.py --mode audit --url https://example.com/
```

Web UI only:

```bash
python -m pip install fastapi "uvicorn[standard]" jinja2 python-multipart
python webapp/run.py            # then open http://127.0.0.1:8000
```

For optional JavaScript rendering and PDF reports:

```bash
playwright install chromium
```

### Docker (one command, bundles Chromium)

```bash
docker compose up --build       # then open http://127.0.0.1:8000
```

Built on the official Playwright image, so JavaScript rendering and PDF reports work out of the box. Outputs persist in `./webapp_jobs`; secrets are read at runtime from `.env` (never baked into the image); optional Google credentials can be mounted under `./credentials`.

### Windows installer (no Docker, no admin)

```powershell
powershell -ExecutionPolicy Bypass -File installer\install.ps1
```

Sets up an isolated `.venv`, installs all requirements plus Chromium for Playwright, and adds Desktop + Start Menu shortcuts that launch the local web UI. See [`installer/README.md`](installer/README.md).

### Command-line usage

```bash
python main.py --mode audit --url https://example.com/
python main.py --mode competitor --url https://competitor.example/
python main.py --mode compare
python main.py --analyze-only --skip-external
python main.py --phase2            # crawl the deferred URLs from a previous run
python main.py --clear-cache
```

---

## Screenshots

> _Placeholder — add your own screenshots here._ Suggested captures: the Crawl tab, a live job page with the six counters, the Action Board, the link-graph view, and a rendered Client report. Drop the images under `docs/screenshots/` and reference them here, e.g. `![Action Board](docs/screenshots/action-board.png)`.

---

## Platform presets

Pick a preset from the UI (Advanced crawl options) or set `site.platform_preset` in `config.yaml`. A preset **adds** recommended exclude patterns and query-parameter normalization without clearing yours — so cart / checkout / account noise and duplicate sort-order URLs stay out of the crawl.

| Preset | Best for | What it excludes / normalizes |
|---|---|---|
| **Zid** | Zid stores | cart / checkout / account / add-to-cart; normalizes `sort_by` / `sort` / `order_by` / `order` / `view`. |
| **Salla** | Salla stores | cart / checkout / profile / login / add-to-cart; normalizes `sort` / `order` / `view`. |
| **Shopify** | Shopify stores | cart / checkout / account / `products.json` endpoints; normalizes `sort_by` / `view`. |
| **WooCommerce** | WordPress-based stores | cart / checkout / my-account / add-to-cart / wp-admin; normalizes `orderby` / `order` / price filters. |
| **WordPress** | Vanilla WP sites (blogs, news, corporate, gov) | `?replytocom=` (the classic infinite comment-crawl trap), `/feed/`, `/tag/`, `/author/`, `/wp-admin`, `/wp-login.php`, `/wp-json/`, `/xmlrpc.php`, plus 7 query-param strips (`replytocom`, `attachment_id`, `unapproved`, `moderation-hash`, `preview`, `preview_id`, `preview_nonce`). |

Pick **WordPress** for vanilla WP and **WooCommerce** for WP-based stores. The platform can also be auto-detected from the page HTML / headers.

---

## Integrations

All integrations are **optional and off by default**, enabled from **Advanced settings → Integrations** in the UI. Keys and paths are stored only in the local per-job config and are never written to the repository; secret keys are passed to the crawl process via environment variables.

| Integration | What it adds | What you provide |
|---|---|---|
| **Google Search Console** | Clicks / impressions / CTR / position per page & query + keyword cannibalization + internal-link opportunities | OAuth (Desktop) credentials + verified site URL |
| **GSC URL Inspection** | Real per-URL index status (verdict / coverage / canonical), quota-capped | Same GSC credentials |
| **Google Analytics 4** | Sessions / users / engagement for landing pages + channels | Service-account JSON + property ID (needs `google-analytics-data`) |
| **PageSpeed Insights** | Performance / SEO scores + deep Lighthouse tables (audits / network / JS treemap / failed) | API key (or `PAGESPEED_API_KEY` in `.env`) |
| **CrUX History** | Core Web Vitals trend over time (p75) | Same PageSpeed key |
| **Lighthouse import** | Reads local Lighthouse JSON — no keys, no internet | A folder of Lighthouse `.json` files |
| **Ahrefs Webmaster (AWT)** | Free backlinks / keywords for site owners | A folder of AWT CSV exports |
| **Backlinks API (live, paid)** | Referring domains + top external links | API key in `.env` (`BACKLINKS_API_KEY`) — Ahrefs API v3 or Majestic OpenApp |
| **AI advisor** | Executive summary + prioritized recommendations | An API key (or a local OpenAI-compatible endpoint) |

The UI offers one-click Google sign-in (with dropdowns to pick GSC sites / GA4 properties), a paste-the-code fallback for headless machines, and a first-time setup guide with direct links to Google Cloud. See [`docs/EXTERNAL_TOOLS_GUIDE.md`](docs/EXTERNAL_TOOLS_GUIDE.md).

---

## Output formats

Raw data (**CSV** and **JSON**) is always written after a crawl; the rest is generated on demand.

| Format | Contents |
|---|---|
| **CSV** (`csv/`) | The complete data home — many small, single-purpose files: pages, all_links / inlinks / outlinks_external, images (+ no-alt / no-dimensions), headings, schema, headers, redirects (+ chains / loops / issues), seo_issues, duplicates, orphans, thin_content, 4xx / 5xx / 404-with-inlinks, url_issues, canonical_issues, security_issues, pagination (+ issues), hreflang_issues, resources (+ issues / status), custom_extraction, excluded_urls, deferred_urls, and — when enabled — gsc_pages / gsc_queries / gsc_index_status, keyword_cannibalization, internal_link_opportunities, ga4_landing_pages / ga4_channels, pagespeed_* (deep Lighthouse tables), crux_history, priority_opportunities, page_priority, action_board, ai_recommendations, lighthouse_import, js_diff, accessibility (+ issues). |
| **JSON** | The complete machine-readable audit archive (the report is built from this). Raw link / image / heading arrays are excluded by default to keep it light; set `output.json_full: true` to embed them. |
| **Excel** (`.xlsx`) | A bounded, multi-sheet client workbook (sheets capped for readability). Requires `openpyxl`; skipped gracefully if absent. |
| **HTML / PDF** | The formatted, shareable report — Expert, Client, or Both. Arabic / RTL supported. PDF requires Playwright. |
| **XML** (`xml/`) | The same core data in XML for tooling that prefers it (off by default; row-capped). |
| **sitemap.xml** | Generated from indexable pages when `output.generate_sitemap` is on. |
| **metrics.json** | Run metrics — counters, per-phase timings, and the slowest phases. |

Files only appear when the matching data exists or the matching integration is enabled. On the job page you can download any file individually, everything as one ZIP, or a selected subset.

---

## Documentation

| For… | Read |
|---|---|
| End-users (UI walkthrough, integrations, troubleshooting) | [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) · [العربية](docs/USER_GUIDE_AR.md) |
| Command-line flags + scenarios | [`docs/CLI.md`](docs/CLI.md) · [العربية](docs/CLI_AR.md) |
| Architecture, module map, design decisions | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [العربية](docs/ARCHITECTURE_AR.md) |
| External tool integrations (Lighthouse, ZAP, Backlinks) | [`docs/EXTERNAL_TOOLS_GUIDE.md`](docs/EXTERNAL_TOOLS_GUIDE.md) · [العربية](docs/EXTERNAL_TOOLS_GUIDE_AR.md) |
| Incident runbook (operators) | [`docs/RUNBOOK.md`](docs/RUNBOOK.md) · [العربية](docs/RUNBOOK_AR.md) |
| Contributing / extending the tool | [`CONTRIBUTING.md`](CONTRIBUTING.md) · [العربية](CONTRIBUTING_AR.md) |
| Code of Conduct | [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) · [العربية](CODE_OF_CONDUCT_AR.md) |
| Security policy | [`SECURITY.md`](SECURITY.md) |
| Windows installer | [`installer/README.md`](installer/README.md) |
| Release history | [`CHANGELOG.md`](CHANGELOG.md) |
| What's planned | [`ROADMAP.md`](ROADMAP.md) |

---

## Requirements

- **Python 3.10+**.
- Core dependencies from `requirements.txt` (includes the web UI: `fastapi`, `uvicorn`, `jinja2`, `python-multipart`).
- **Playwright + Chromium** (optional) — only for JavaScript rendering, the accessibility audit, and PDF reports: `playwright install chromium`.
- **`openpyxl`** (optional) — only for Excel export; skipped gracefully if absent.
- **`google-analytics-data`** (optional) — only for the GA4 integration.

Run the tests with:

```bash
python -B -m compileall -q seo_crawler/seo_crawler tests
python -B -m unittest discover -s tests
```

---

## License & contributing

**MIT License** — Copyright (c) 2026 **Ahmad-Ajm**. You may copy, modify, distribute, and use this software commercially. See [LICENSE](LICENSE).

Contributions are welcome and accepted under the same license. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) (and the [Code of Conduct](CODE_OF_CONDUCT.md)) before opening a pull request. Security issues: see [`SECURITY.md`](SECURITY.md).
