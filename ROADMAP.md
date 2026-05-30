# SCT Roadmap

This roadmap lists the **remaining** proposed improvements. Completed items are removed (see
`CHANGELOG.md` for the full history of shipped work).

## Pending features (by expected impact)

| Priority | Feature | Importance | Notes |
| --- | --- | --- | --- |
| P2 | Crawl comparison surfaced in the UI/report | Medium | `analyzers/crawl_compare.py` (fixed/new/persisting) is ready and tested; add a UI action to pick two runs and a report section. |
| P3 | Log file analysis | Medium | Parse server logs for Googlebot crawl budget and bot-crawled orphans (Botify/OnCrawl style). Large, needs log access. |
| P3 | Crawl visualizations | Low | Force-directed crawl map / directory tree. Needs a rendering lib (matplotlib not installed here); consider exporting a JSON graph the UI renders instead. |
| P3 | Windows installer | Low | Docker packaging now ships (`docker compose up`); a native one-click installer (PyInstaller/Inno Setup) for non-Docker Windows users is still open. |
| P3 | Live third-party backlink APIs | Low | Backlink data via CSV is already supported through the AWT importer (`integrations/awt_importer.py`). A live Ahrefs/Majestic/Moz API integration (paid keys, off by default) is the remaining step. |

## Recently shipped (highlights)

- Deep PageSpeed/Lighthouse structured tables (audits / network requests / JS treemap / failed
  audits) extracted from the raw report — no extra API calls.
- GSC insights: keyword cannibalization + internal-link opportunities; GSC URL Inspection
  (real index status); CrUX History (CWV trend).
- Sitemap generator; crawl-over-time comparison; prioritized issue hints (impact/effort/why/how);
  adaptive throttle; e-commerce platform presets; auto-install of optional requirements.
- Priority Engine v2 + Action Board: multi-factor per-page priority (severity × impact × ease ×
  confidence) with page-type and ease/owner classification → `page_priority.csv` /
  `action_board.csv` + expert-report section. Non-interactive, time-bounded Google connection tests.
- Web UI toggles for the shipped options (platform preset, adaptive throttle, sitemap generation,
  GSC URL Inspection, CrUX History) — everything operable without the terminal.
- Accessibility checks (axe-core) wired into the JS-render path → `accessibility.csv` /
  `accessibility_issues.csv`. Interactive Action Board page (`/jobs/<id>/board`). Docker
  packaging (`Dockerfile` + `docker-compose.yml`) on the official Playwright image.
- Easier Google sign-in (own-credentials): site/property dropdowns, paste-the-code fallback
  for headless machines, full disconnect, in-UI 3-step setup guide. URL drill-down detail
  panel in the Action Board joining crawl + GSC + GA4 + PageSpeed + priority + accessibility
  per URL (`/api/jobs/<id>/url-detail`, `reporting/url_detail`).
- Custom extraction (CSS/XPath/regex) and rendered-vs-raw JS diff (already implemented).
- Internal link score (PageRank); near-duplicate (SimHash+LSH); orphan finder; JavaScript
  rendering wired into the async crawler with a page cap.
- Reliability + security hardening; HTML/PDF reports (Arabic/RTL); integrated local web UI.

## Current top targets

1. Crawl comparison surfaced in the UI/report.
2. Log file analysis (crawl budget / bot-crawled orphans).
3. Windows installer (PyInstaller/Inno Setup) for non-Docker users.
