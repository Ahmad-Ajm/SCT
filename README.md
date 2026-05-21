# SCT - Simple Crawler Tool

SCT is an open-source technical SEO crawler built with Python. It helps audit websites for crawlability, indexability, on-page SEO issues, links, images, structured data, canonicals, hreflang, mixed content, redirects, and exportable reports.

The project started as a lightweight alternative for technical SEO checks, then evolved into a multi-mode crawler with async crawling, SQLite storage, CSV/JSON/Excel exports, observability metrics, and a roadmap toward GUI and PDF reporting.

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
- CSV, JSON, and optional Excel exports.
- Detailed logs and `metrics.json` observability output.
- GitHub Actions CI.

## Quick Start

```bash
python -m pip install -r requirements.txt
python main.py --help
python main.py --mode audit --url https://example.com/
```

For optional JavaScript rendering:

```bash
playwright install chromium
```

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

## GUI and PDF Reporting Roadmap

See [docs/GUI_PDF_REPORTING_PLAN.md](docs/GUI_PDF_REPORTING_PLAN.md) for the planned GUI, PDF reporting, scheduling, PDF customization, and JavaScript rendering strategy.

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
