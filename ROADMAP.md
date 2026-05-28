# SCT Roadmap

This roadmap lists the **remaining** proposed improvements. Completed items have been removed (see `CHANGELOG.md` for the history of shipped work).

## Pending features (by expected impact)

| Priority | Feature | Importance | Notes |
| --- | --- | --- | --- |
| P1 | Custom extraction | High | Support CSS selectors, XPath, and regex extraction into custom columns. One of the most useful pro SEO crawler workflows. |
| P1 | Internal link score | High | Calculate simple internal PageRank/link equity signals to prioritize important orphan/low-link pages. |
| P2 | JavaScript rendered/raw diff | Medium | Compare raw vs. rendered HTML for title, meta, h1, canonical, links, and content. Useful for JS-heavy platforms; also wire JS rendering into the async path (currently sync-only). |
| P2 | Adaptive concurrency | Medium | Slow down when the site returns 429/5xx or becomes slow. |
| P2 | Sitemap generator | Medium | Export clean XML sitemaps from crawled indexable pages. |
| P2 | Crawl comparison (run vs. run) | Medium | Compare two crawl runs and show fixed/new/unchanged issues over time. |
| P2 | Accessibility checks | Medium | Optional axe/Playwright checks as a separate module. |
| P3 | Installer / packaging | Medium | One-click installer (PyInstaller/Inno Setup) that bundles deps and runs `playwright install chromium` post-install. |
| P3 | Docker image | Medium | Easier setup for non-Python users. |
| P3 | E-commerce presets | Medium | Presets for Zid, Salla, Shopify, WooCommerce (esp. Arabic commerce). |
| P3 | AI-assisted recommendations | Low | Summarize issues and suggest fixes (must not replace deterministic checks). |

## Recently shipped (highlights)

- Reliability fixes: async termination (no hang on `max_pages`), real async resume, no duplicate child rows on re-crawl.
- Security hardening: SSRF guards, gzip decompression cap, robots checks on redirects, CSV/Excel formula-injection neutralization.
- HTML + PDF reports (Arabic/RTL via Playwright), customizable per client.
- Integrated local Web UI (FastAPI + HTMX + SSE): configure settings, run/stop crawls, live monitoring, and report downloads.
- Open-source readiness, CI quality gate, local fixture test server, URL/canonical analyzers, robust analyze-only mode.

## Current top targets

1. Custom extraction (CSS/XPath/regex).
2. Internal link score.
3. Installer / packaging for non-technical users.
