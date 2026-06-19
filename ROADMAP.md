# SCT Roadmap

This roadmap lists the **remaining** proposed improvements. Completed items are removed (see
`CHANGELOG.md` for the full history of shipped work).

## Pending features (by expected impact)

| Priority | Feature | Importance | Notes |
| --- | --- | --- | --- |
| P3 | Single-file Windows `.exe` (PyInstaller) | Low | The PowerShell installer (`installer/`) is the supported non-Docker Windows path. A true bundled `.exe` is the next step — needs a Windows CI build host (offline dev environment can't produce/test it). |

## Recently shipped (highlights)

- v1.04 ROADMAP cleanup: queue counter clarity when max_pages hit, silence-aware
  "why am I waiting?" hint, Excel + XML added to on-demand generation, crawl
  visualization page (`/jobs/<id>/graph`) with depth/status bars + URL hierarchy
  tree + force-directed link map, log analyzer → Action Board join
  (`POST /api/jobs/<id>/log-board` surfacing wasted Google budget + high-value
  pages with issues + orphan-at-Google), live backlinks API integrations
  (Ahrefs v3 + Majestic OpenApp under `integrations/backlinks_api.py`).
- v1.03 UI/UX overhaul: hoverable tooltips on every control with time-cost hints,
  multi-stage phase visibility (current URL + percent during PageSpeed/External-links/
  Analysis/Export), optional-requirements status row, on-demand HTML/PDF generation
  (cuts crawl wall-time), AI advisor per-provider field cleanup with explicit local-model
  option, PageSpeed DNS-error retry + grouped error summary, depth default lowered to 5
  with explanatory tooltip, mode + speed fine-tuning + platform preset moved into
  Advanced. Two new docs: `docs/OAUTH_SETUP.md` and `docs/GA4_PROPERTY_ID.md`.
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
- Crawl-over-time comparison surfaced in the UI (`/jobs/<id>/compare` + `/api/jobs/list` +
  `/api/jobs/<id>/compare`). Server log analyzer (`/logs`, `analyzers/log_analyzer`).
  Windows installer scripts (`installer/install.ps1` + `run.bat` + `uninstall.ps1`).
- Custom extraction (CSS/XPath/regex) and rendered-vs-raw JS diff (already implemented).
- Internal link score (PageRank); near-duplicate (SimHash+LSH); orphan finder; JavaScript
  rendering wired into the async crawler with a page cap.
- Reliability + security hardening; HTML/PDF reports (Arabic/RTL); integrated local web UI.

## Current top targets

1. **Single-file Windows `.exe` (PyInstaller)** — packages everything in one click.
   The only remaining roadmap item. Needs a Windows build host with CI.
