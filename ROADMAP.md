# SCT Roadmap

This roadmap lists the proposed improvements for turning SCT into a reliable open-source technical SEO crawler. Priority is ordered by expected impact on trust, usefulness, and maintainability.

| Priority | Feature | Importance | Notes |
| --- | --- | --- | --- |
| P0 | Open-source readiness | Critical | Add license, contribution guide, security policy, changelog, and a safe example config. This makes the project publishable without leaking site-specific settings. |
| P0 | CI quality gate | Critical | Run tests and compile checks on every push/PR. This protects the project from regressions as contributors start sending changes. |
| P0 | Local fixture test server | Critical | Add deterministic tests for redirects, robots, sitemap, 404/500, and normal pages. Real websites change; local fixtures keep tests stable. |
| P0 | URL issues analyzer | High | Detect long URLs, uppercase paths, underscores, excessive parameters, tracking parameters, fragments, and non-ASCII URLs. These are common technical SEO issues and easy to export. |
| P0 | Canonical analyzer | High | Detect missing canonicals, canonicals to non-200 URLs, canonicals outside the site, and canonical chains/loops. Canonical mistakes can directly affect indexation. |
| P1 | Robust analyze-only mode | High | Make analysis work from SQLite without importing crawl-only dependencies. This enables repeatable reporting from saved crawl data. |
| P1 | Crawl resume improvements | High | Persist and restore queue, visited URLs, and partial progress safely. This is essential for large sites and long crawls. |
| P1 | HTML report | High | Generate a readable report with issue priorities, summaries, and recommendations. Non-technical users need more than CSV/JSON. |
| P1 | Custom extraction | High | Support CSS selectors, XPath, and regex extraction into custom columns. This is one of the most useful pro SEO crawler workflows. |
| P1 | Internal link score | High | Calculate simple internal PageRank/link equity signals. This helps prioritize important orphan/low-link pages. |
| P2 | JavaScript rendered/raw diff | Medium | Compare raw HTML and rendered HTML for title, meta, h1, canonical, links, and content differences. Useful for platforms like Zid, but expensive. |
| P2 | Adaptive concurrency | Medium | Adjust crawl speed when the site returns 429/5xx or becomes slow. This improves speed without being aggressive. |
| P2 | Sitemap generator | Medium | Export clean XML sitemaps from crawled indexable pages. Helpful, but many sites already have platform sitemap support. |
| P2 | Crawl comparison | Medium | Compare two runs and show fixed/new/unchanged issues. Excellent for ongoing SEO work after baseline reporting exists. |
| P2 | Accessibility checks | Medium | Integrate optional axe/Playwright checks. Valuable, but heavier and better as an optional module. |
| P3 | Docker image | Medium | Make installation easier for non-Python users. Useful after the CLI/API shape stabilizes. |
| P3 | E-commerce presets | Medium | Add presets for Zid, Salla, Shopify, and WooCommerce. This can be a unique SCT strength, especially for Arabic commerce sites. |
| P3 | Web UI | Low | A small local dashboard would improve usability, but should come after the core crawler and reports are stable. |
| P3 | AI-assisted recommendations | Low | Summarize issues and suggest fixes. Nice to have, but should not replace deterministic checks. |

## Known Issues — Deferred (Will Not Fix Soon)

| Issue | Severity | Decision |
| --- | --- | --- |
| `max_pages` overshoot in the async crawler | Low (cosmetic) | The per-worker limit check is lock-free and `pages_crawled` is incremented after processing, so a crawl can exceed `max_pages` by up to `(workers - 1)` pages. A correct fix needs a shared budget lock that risks introducing deadlock/hang. **Intentionally deferred for the foreseeable future.** |

## Current Top 5 Implementation Targets

1. Open-source readiness.
2. CI quality gate.
3. Local fixture test server.
4. URL issues analyzer.
5. Canonical analyzer.
