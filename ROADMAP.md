# SCT Roadmap

This roadmap lists the **remaining** proposed improvements. Completed items are removed (see
`CHANGELOG.md` for the full history of shipped work).

## Pending features (by expected impact)

| Priority | Feature | Importance | Notes |
| --- | --- | --- | --- |
| P3 | Single-file Windows `.exe` (PyInstaller) | Low | The PowerShell installer (`installer/`) is the supported non-Docker Windows path. A true bundled `.exe` is the next step — needs a Windows CI build host (offline dev environment can't produce/test it). |

## Recently shipped (highlights)

- **v1.13 (2026-06-20–23)** — final REFACTOR-tests-split (1,414 LOC monolith →
  6 categorized files + conftest.py), then a same-day polish + OSS-readiness
  train (v1.13.1 label_for differentiates JSON files, v1.13.2 `withToken()`
  for SSE + downloads, v1.13.3/6 triple-path auto-show + live polling,
  v1.13.4 docs parity + RUNBOOK_AR, **v1.13.5 WordPress platform preset**
  with 19 exclude patterns + 7 query-param strips, v1.13.7 defensive URL
  scheme normalization, **v1.13.8** OSS blocker fixes — client-name leak
  scrubbed, SECURITY.md rewritten around GitHub Private Advisory channel
  + v1.10+ threat model, ROADMAP backfilled through v1.13, CONTRIBUTING
  stale `main.py::run_*` paths fixed, **v1.13.9** docs continuation —
  USER_GUIDE Backlinks/WordPress/graph/counters/local-token sections,
  CLI --phase2 + env-var additions, ARCHITECTURE rewritten for the v1.12
  services/+routers/ refactor, RUNBOOK self-id bumped, pip-audit CI
  comment vs `continue-on-error` contradiction resolved). 92/92 tests.
- **v1.12 (2026-06-20)** — security/quality overhaul. CVE bumps (Playwright
  base v1.47→v1.55, aiohttp 3.10→3.12, jinja2 3.1.4→3.1.6, python-multipart
  0.0.12→0.0.18). `SCT_AUTO_INSTALL` flipped from opt-out to opt-in.
  REFACTOR-services split `main.py` 2,339→513 LOC (−78%) into 14 service
  modules. REFACTOR-app-routers split `webapp/app.py` 2,098→143 LOC (−93%)
  into 9 APIRouter modules + `security.py` + `deps.py` + `constants.py`.
- **v1.11 (2026-06-20)** — debuggability sweep (17 `log.error` → `log.exception`
  across 9 files), hot-loop import hoisting in `crawler/core.py`, new
  `docs/RUNBOOK.md` (8 operator scenarios with shell + PowerShell commands),
  multi-stage Dockerfile, `tools/freeze_lock.bat` for reproducible lockfile.
- **v1.10 (2026-06-20)** — webapp hardening. Local auth token at
  `~/.sct/local_token` (Bearer + ?token=), CSRF Origin guard, rate limits
  (10/min on `/api/start`, 120/min on `/api/*`), `/health` + `/readyz` for
  orchestrators, correlation IDs (`X-Request-ID`), global exception handler,
  SQL identifier whitelist (`_ALLOWED_TABLES`), MIME validation on uploads.
  Plus root-level launchers: `START.bat` / `START.ps1` / `start.sh` /
  `STOP.bat` (v1.10.1).
- **v1.09 (2026-06-20)** — 12-batch audit response: SSRF defense-in-depth
  (IPv4-mapped IPv6 + fails-closed DNS), API-key removal from URL queries,
  atomic token writes, XSS guard on `graph.html`, argv injection lockdown,
  log-board OOM cap, status-code coercion across 9 analyzers,
  url_classifier precedence fix, gsc_token corruption survival.
- **v1.08 (2026-06-20)** — two-phase crawl (URL classifier auto-defers
  pagination_deep / redirect_wrapper / filter_combination; user runs Phase
  2 from a panel after Phase 1 finishes). `deferred_urls.csv` +
  `deferred_summary` in `audit.json`.
- **v1.07 (2026-06-20)** — aggressive URL normalization
  (`set_extra_strip_params`) shrinks queue 40-70% on storefronts with
  `sort_by=…` filter combinatorics.
- **v1.06 (2026-06-20)** — Google OAuth token-expiry detection (the 7-day
  Testing-mode revocation surfaces before crawl-start instead of mid-crawl),
  integrations-only jobs handled correctly in report generator.
- **v1.05 (2026-06-20)** — User-Agent presets (Googlebot, Googlebot-Mobile,
  Bingbot) for revealing Cloudflare/WAF bot-specific blocks.
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
