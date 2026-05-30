# SCT - Simple Crawler Tool

SCT is an open-source technical SEO crawler built with Python. It helps audit websites for crawlability, indexability, on-page SEO issues, links, images, structured data, canonicals, hreflang, mixed content, redirects, and exportable reports.

The project started as a lightweight alternative for technical SEO checks, then evolved into a multi-mode crawler with async crawling, SQLite storage, CSV/JSON/Excel exports, observability metrics, an integrated local Web UI, and HTML/PDF client reports.

Arabic documentation is available in [README_ar.md](README_ar.md).

## Features

- Async crawler with configurable concurrency and crawl delay.
- Sync crawler fallback.
- SQLite-backed crawl storage for larger sites.
- Audit, competitor, and compare modes.
- `robots.txt` and sitemap handling.
- HTTPS certificate verification controls.
- URL hygiene analysis.
- Canonical analysis.
- Duplicate title/description/content checks.
- Thin content checks.
- Broken internal link analysis.
- External link status checks.
- Image analysis.
- Schema.org validation.
- Hreflang validation.
- Sitemap vs crawl comparison.
- Mixed content detection.
- Security headers analyzer (HSTS/CSP/X-Frame-Options/etc.).
- Resource inventory (CSS/JS/images/fonts/media/iframes) with mixed-content flags.
- Custom extraction (CSS/attr/text/regex rules).
- Optional async JavaScript rendering with raw-vs-rendered diff (Playwright).
- Optional Lighthouse/PageSpeed JSON import (no keys).
- Optional GSC + GA4 connectors with a unified report (Technical + Search + Behavior) and a
  cross-referenced "Priority Opportunities" section.
- Internal link score (PageRank), near-duplicate detection (SimHash + LSH), and orphan finder.
- Optional PageSpeed connector with **deep Lighthouse tables** (all audits / network requests /
  JS treemap / failed audits), plus optional **GSC URL Inspection** and **CrUX History**.
- GSC-derived insights: keyword cannibalization and internal-link opportunities.
- Crawl-over-time comparison (fixed / new / persisting issues) and actionable issue hints
  (impact / effort / why / how / priority score).
- Priority Engine v2 + Action Board: a transparent multi-factor per-page score
  (severity × impact × ease × confidence) with page-type and ease/owner classification,
  grouped into Do now / Needs developer / Needs platform / Needs content / Do later.
- Sitemap generator, adaptive crawl throttle, and e-commerce platform presets
  (Zid / Salla / Shopify / WooCommerce).
- Auto-install of optional requirements (allowlisted; disable with `SCT_NO_AUTO_INSTALL=1`).
- Results explorer (filter/sort/search) and full settings editable from the UI.
- CSV, JSON, optional Excel, and HTML/PDF report exports.
- Integrated local Web UI (FastAPI + HTMX + SSE) with live crawl monitoring.
- Customizable HTML/PDF client reports (Arabic/RTL via Playwright).
- Reliable async resume and crash-safe re-runs (no duplicate rows).
- SSRF protection, gzip-bomb caps, and CSV/Excel formula-injection neutralization.
- Detailed logs and `metrics.json` observability output.
- GitHub Actions CI.

## Quick Start

```bash
python -m pip install -r requirements.txt
python main.py --help
python main.py --mode audit --url https://example.com/
```

For optional JavaScript rendering and PDF reports:

```bash
playwright install chromium
```

### Web UI

```bash
python -m pip install fastapi "uvicorn[standard]" jinja2 python-multipart
python webapp/run.py            # then open http://127.0.0.1:8000
```

### Docker (one command, bundles Chromium)

```bash
docker compose up --build       # then open http://127.0.0.1:8000
```

Built on the official Playwright image, so JavaScript rendering and PDF reports work out of
the box. Outputs persist in `./webapp_jobs`. Secrets are read at runtime from `.env` (never
baked into the image); optional Google credentials can be mounted under `./credentials`.

### Windows installer (no Docker, no admin)

```powershell
powershell -ExecutionPolicy Bypass -File installer\install.ps1
```

Sets up an isolated `.venv`, installs all requirements + Chromium for Playwright, and adds
Desktop + Start Menu shortcuts that launch the local web UI. See `installer/README.md`.

The UI lets you configure settings, set the target URL, choose a mode, start/stop
crawls with live progress (SSE), and download HTML/PDF/Excel/JSON reports. Each job's
artifacts are stored under `webapp_jobs/<job_id>/`.

## Usage

```bash
python main.py --mode audit
python main.py --mode audit --url https://example.com/
python main.py --mode competitor --url https://competitor.example/
python main.py --mode compare
python main.py --analyze-only --skip-external
python main.py --clear-cache
```

## Project Structure

```text
Simple_Crawler_Tool_SCT/
├── main.py                  # Root launcher
├── config.yaml              # Local runtime config
├── config.example.yaml      # Public example config
├── requirements.txt         # Python dependencies
├── ROADMAP.md               # Product and technical roadmap
├── docs/                    # Planning and architecture docs
└── seo_crawler/seo_crawler/ # Main application package
```

The maintained implementation lives in `seo_crawler/seo_crawler`.

## Modes

| Mode | Purpose |
| --- | --- |
| `audit` | Full technical SEO audit for a site you own or manage. |
| `competitor` | Respectful, lighter crawl for competitor research. |
| `compare` | Crawl multiple sites from `sites_to_compare` and export comparison summaries. |

## Configuration

Use `config.example.yaml` as a safe public template, then copy it to `config.yaml` and adjust it for your website.

Important sections:

- `site`: start URL and primary domain.
- `crawl`: limits, delays, retries, robots policy, SSL verification, concurrency.
- `extraction`: which page elements to extract.
- `analysis`: thresholds for titles, descriptions, content, URLs, and depth.
- `output`: export formats and output directory.
- `state`: SQLite/cache settings.
- `external_check`: external link checking behavior.
- `observability`: logging and metrics controls.

## Outputs

By default, SCT writes timestamped output folders under `output/`.

Typical outputs include:

- `complete_audit.json`
- CSV files for pages, links, images, headings, schema, redirects, SEO issues, URL issues, and canonical issues.
- Optional `master_audit.xlsx` if `openpyxl` is installed.
- `report.html` and `report.pdf` when `html`/`pdf` are in `output.formats` (PDF needs Playwright).
- `metrics.json` with timings, counters, gauges, and recent events.

## Open Source Readiness

This repository includes:

- MIT license.
- Contribution guide.
- Security policy.
- Changelog.
- GitHub Actions CI.
- Public example config.
- Roadmap.

## Web UI, PDF & Unified Reporting

The integrated Web UI, customizable HTML/PDF reports, and the unified report (Technical SEO
+ GSC + GA4 + cross-referenced priority opportunities) are implemented. For optional
integration setup (Lighthouse / GSC / GA4 / ZAP) see
[docs/EXTERNAL_TOOLS_GUIDE.md](docs/EXTERNAL_TOOLS_GUIDE.md).

## Tests

```bash
python -B -m compileall -q seo_crawler/seo_crawler tests
python -B -m unittest discover -s tests
```

## Notes

- SCT respects `robots.txt` when configured to do so.
- Use conservative concurrency when crawling websites you do not own.
- JavaScript rendering is optional and should be enabled selectively.
- Excel export is skipped gracefully if `openpyxl` is not installed.

## License

MIT License. See [LICENSE](LICENSE).
