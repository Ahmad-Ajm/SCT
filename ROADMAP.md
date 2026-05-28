# SCT Roadmap

This roadmap lists the **remaining** proposed improvements. Completed items are removed (see
`CHANGELOG.md` for the full history of shipped work).

## Pending features (by expected impact)

| Priority | Feature | Importance | Notes |
| --- | --- | --- | --- |
| P1 | UI toggles for the new options | High | Surface the recently-added config options in the web UI (no terminal): `output.generate_sitemap`, `crawl.adaptive_throttle`, `gsc.url_inspection`, `pagespeed.crux_history`, `site.platform_preset`. Backend + config + tests already shipped; this is the form/i18n/job_runner wiring. |
| P2 | Live wiring of accessibility (axe-core) | Medium | The pure summarizer + page runner exist (`analyzers/accessibility.py`); wire it into the JS-render path (run axe while the Playwright page is alive) and export `accessibility.csv`. Needs `playwright` + an axe-core source. |
| P2 | Crawl comparison surfaced in the UI/report | Medium | `analyzers/crawl_compare.py` (fixed/new/persisting) is ready and tested; add a UI action to pick two runs and a report section. |
| P3 | Log file analysis | Medium | Parse server logs for Googlebot crawl budget and bot-crawled orphans (Botify/OnCrawl style). Large, needs log access. |
| P3 | Crawl visualizations | Low | Force-directed crawl map / directory tree. Needs a rendering lib (matplotlib not installed here); consider exporting a JSON graph the UI renders instead. |
| P3 | Installer / packaging | Medium | One-click installer (PyInstaller/Inno Setup) or Docker image bundling deps + `playwright install chromium`. Build tooling, environment-specific. |
| P3 | Live third-party backlink APIs | Low | Backlink data via CSV is already supported through the AWT importer (`integrations/awt_importer.py`). A live Ahrefs/Majestic/Moz API integration (paid keys, off by default) is the remaining step. |

## Recently shipped (highlights)

- Deep PageSpeed/Lighthouse structured tables (audits / network requests / JS treemap / failed
  audits) extracted from the raw report — no extra API calls.
- GSC insights: keyword cannibalization + internal-link opportunities; GSC URL Inspection
  (real index status); CrUX History (CWV trend).
- Sitemap generator; crawl-over-time comparison; prioritized issue hints (impact/effort/why/how);
  adaptive throttle; e-commerce platform presets; auto-install of optional requirements.
- Custom extraction (CSS/XPath/regex) and rendered-vs-raw JS diff (already implemented).
- Internal link score (PageRank); near-duplicate (SimHash+LSH); orphan finder; JavaScript
  rendering wired into the async crawler with a page cap.
- Reliability + security hardening; HTML/PDF reports (Arabic/RTL); integrated local web UI.

## Current top targets

1. UI toggles for the shipped config options (keep everything operable without the terminal).
2. Live axe-core accessibility wiring + `accessibility.csv`.
3. Installer / packaging for non-technical users.
