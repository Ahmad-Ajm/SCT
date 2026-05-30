# SCT — Architecture & design decisions

> Audience: developers who want to read, extend, or fork SCT.
> النسخة العربية: [`ARCHITECTURE_AR.md`](ARCHITECTURE_AR.md).
> For end-user usage, see [`USER_GUIDE.md`](USER_GUIDE.md).
> For the CLI flags, see [`CLI.md`](CLI.md).

---

## 1. Bird's-eye view

SCT is a **local-only** SEO crawler + audit tool. It runs entirely on the user's machine,
exposes a small FastAPI web UI on `127.0.0.1`, and never phones home. Every external
integration (GSC, GA4, PageSpeed, CrUX, AI) is **optional and off by default**; the user's
own credentials stay on disk and are never committed.

```
                ┌──────────────────────────────────────────────────────┐
                │                Web UI (FastAPI + Jinja)              │
                │   /          /jobs/<id>   /jobs/<id>/board /logs ... │
                └──────────────┬────────────────────────┬──────────────┘
                               │ HTTP                   │ HTTP
                               ▼                        ▼
                       ┌───────────────┐       ┌────────────────┐
                       │  job_runner   │──────►│  subprocess    │
                       │  (orchestrator)        │  (main.py)     │
                       └───────┬───────┘       └────────┬───────┘
                               │                        │
                               │           ┌────────────┴──────────────┐
                               │           ▼                           ▼
                               │   ┌───────────────┐         ┌──────────────────┐
                               │   │ Crawler (async │         │  Analyzers       │
                               │   │ aiohttp + sync │────────►│  (pure functions │
                               │   │ fallback)      │         │   over rows)     │
                               │   └────────┬───────┘         └────────┬─────────┘
                               │            │                          │
                               │            ▼                          ▼
                               │       ┌─────────┐              ┌────────────────┐
                               │       │ SQLite  │              │ Reporting:     │
                               │       │ per-job │              │ priority engine│
                               │       └─────────┘              │ build_unified  │
                               │                                └────────┬───────┘
                               │                                         │
                               │           ┌─────────────────────────────┘
                               │           ▼
                               │   ┌─────────────────────────────────────────────┐
                               │   │ Exporters: CSV / Excel / XML / JSON /       │
                               │   │   HTML + PDF (Playwright) / sitemap.xml     │
                               │   └─────────────────────────────────────────────┘
                               │
                               ▼
                  ┌──────────────────────────────────────────────────────┐
                  │ Optional integrations (off by default):              │
                  │   GSC · GA4 · PageSpeed · CrUX · Lighthouse · AWT    │
                  │   AI advisor · axe-core accessibility                │
                  └──────────────────────────────────────────────────────┘
```

---

## 2. Module map

```
seo_crawler/seo_crawler/
├── main.py                     orchestrator (run_analysis, run_export, _run_integrations_only)
├── config_presets.py           e-commerce platform presets (Zid / Salla / Shopify / Woo)
├── crawler/
│   ├── async_core.py             async crawler (aiohttp); workers, queue, JS render hook
│   ├── core.py                   sync fallback crawler
│   ├── js_renderer.py            Playwright wrapper (JS render + axe injection)
│   ├── adaptive_throttle.py      back off on 429/5xx, recover on healthy responses
│   └── robots_parser.py          robots.txt with streaming size cap
├── extractors/                 per-page extractors (content, meta, links, schema, …)
├── analyzers/                  pure analyzers over the crawled data
│   ├── seo_issues.py             aggregates everything into a severity-tagged list
│   ├── broken_links.py, duplicate_detector.py, canonical_analyzer.py, …
│   ├── link_score.py             internal PageRank
│   ├── near_duplicate.py         SimHash + LSH
│   ├── gsc_insights.py           keyword cannibalization + link opportunities
│   ├── crawl_compare.py          before/after diff for two audit JSONs
│   ├── log_analyzer.py           Apache/Nginx CLF + Googlebot extraction
│   ├── accessibility.py          axe-core result summariser
│   └── hints.py                  impact/effort/why/how on every issue
├── integrations/               external APIs (all off by default)
│   ├── google_auth.py            OAuth client_secret + token (allow_interactive gate)
│   ├── gsc_api.py                Search Console + URL Inspection
│   ├── ga4_api.py                GA4 Data API + Admin API (property listing)
│   ├── pagespeed_api.py          PageSpeed + deep Lighthouse table extraction
│   ├── crux_history.py           Core Web Vitals time series
│   └── awt_importer.py           AWT (Ahrefs Webmaster) CSV import
├── reporting/
│   ├── report_join.py            build_unified: technical × GSC × GA4 per URL
│   ├── opportunities.py          compute_opportunities (legacy priority)
│   ├── priority_engine.py        v2: severity × impact × ease × confidence + Action Board
│   ├── url_detail.py             per-URL detail for the drill-down panel
│   └── report_builder.py         loads audit JSON, renders HTML/PDF
├── exporters/                  csv_exporter, excel_exporter, json_exporter,
│                                xml_exporter, html_exporter, sitemap_generator
├── storage/                    SQLite DB + APICache
└── utils/                      helpers (SSRF guard, formula neutraliser, normalize_url),
                                logger, observability, auto_install

webapp/
├── app.py                      FastAPI app (routes, endpoints, /api/jobs/…)
├── job_runner.py               JobRunner: spawns subprocess, tracks state, deletes
├── run.py                      uvicorn entrypoint
├── static/                     app.css, i18n.js (ar + en dicts)
└── templates/                  index.html, job.html, board.html, compare.html, logs.html,
                                explore.html
tests/
└── test_core_behaviors.py      regression suite (~70 tests, all offline)
```

---

## 3. Data flow (one full audit)

1. **User submits the form** → `POST /api/start` → `JobRunner.start(overrides)`.
2. `JobRunner._build_job_config` writes a per-job `config.yaml` under
   `webapp_jobs/<job_id>/`. Secrets (PageSpeed/AI keys) are stripped from the file and
   passed via `os.environ` to the subprocess instead.
3. `JobRunner.start` spawns `python -m seo_crawler.main` as a child process with
   `SCT_PROGRESS_FILE=…` and `SCT_NONINTERACTIVE=1`.
4. **`main.main_async`** orchestrates the run:
   - `run_analysis` → analyzers (pure) produce `analysis["…"]` dicts.
   - `run_integrations` → optional clients fetch GSC/GA4/PageSpeed/CrUX.
   - `build_unified(pages, analysis, gsc_pages, ga4_landing_pages)` joins per-URL.
   - `compute_opportunities(unified_rows)` (legacy) and
     `compute_priority(unified_rows, platform)` (v2 + Action Board).
   - `run_export` writes CSV / Excel / JSON / XML / HTML / PDF / sitemap.
5. **Web UI polls progress** via `/api/jobs/<id>/events` (SSE) until done.
6. **Outputs** are listed at `/api/jobs/<id>/files`; secondary views
   (`/board`, `/explore`, `/compare`, drill-down panel) read the audit JSON.

---

## 4. Key design decisions

1. **Local-only, no central backend.** Every user runs their own copy. This means no
   shared OAuth app, no shared PageSpeed key, no shared database — and consequently no
   shared quota that one user can drain on behalf of another.
2. **Async crawler with a sync fallback.** Async is 5–10× faster; sync still ships for
   diagnosis and for environments where aiohttp misbehaves.
3. **SQLite per job** for resumability + crash safety. Each `webapp_jobs/<id>/state/`
   is self-contained and can be deleted without touching others.
4. **Deterministic prioritization, AI only for text.** The Priority Engine score
   (`severity × impact × ease × confidence`) is a transparent formula in
   `reporting/priority_engine.py`. AI is used for *narrative* (executive summary,
   suggested rewrites), never for the ranking itself. This keeps the tool
   explainable, reproducible, and free to operate without an LLM.
5. **All integrations off by default.** Every config block defaults to `enabled: false`.
   The tool runs the technical audit without any external service.
6. **No secrets in the repo.** `client_secret.json`, `*_token.json`, `.env`, and
   `credentials/` are all gitignored. Per-job credentials live under
   `webapp_jobs/_google/` (also gitignored).
7. **Each user/agency brings their own OAuth Desktop client.** Quota and the "unverified
   app" warning are tied to the OAuth project — owning your own keeps you isolated and
   removes the 100-user cap.
8. **Bilingual i18n by construction.** Every `data-i18n` key has both `ar` and `en`
   entries (`webapp/static/i18n.js`). A small audit script catches drift.
9. **Streaming + size caps on every external fetch.** robots.txt (2 MB), PageSpeed JSON,
   log uploads (500 MB), client_secret uploads (64 KB), audit JSON (300 MB read guard).
10. **Defense-in-depth security.** SSRF guard on user-supplied URLs, formula-injection
    neutraliser on CSV/Excel, `defusedxml` for XML, gzip-bomb caps, path-traversal
    checks under `_safe_under_jobs`/`_safe_output_file`, OAuth `SCT_NONINTERACTIVE` gate
    so background processes never wait for a browser.

---

## 5. Extension points

- **New analyzer:** see `CONTRIBUTING.md §5`. Pattern is "pure function → main wires it →
  CSV export → test".
- **New integration:** see `CONTRIBUTING.md §6`. Pattern is "off-by-default config → small
  client class → run_integrations hook → UI card with test button".
- **New export format:** add a module to `exporters/`, wire it in `main.run_export`,
  register in `output.formats`.
- **New UI tab:** see `CONTRIBUTING.md §7`. Existing tab JS picks up `data-tab` /
  `data-pane` generically.
- **New CLI flag:** add to `main.py`'s `argparse.ArgumentParser`, then document in
  `docs/CLI.md`.

---

## 6. Where to look for…

| Question | File(s) |
|---|---|
| How is a single page crawled and stored? | `crawler/async_core.py::_crawl_page` |
| How are issues aggregated and labeled? | `analyzers/seo_issues.py` + `analyzers/hints.py` |
| How is the priority score computed? | `reporting/priority_engine.py::compute_priority` |
| How are integrations gated? | `main.py::run_integrations` + `config.example.yaml::integrations` |
| How do secrets reach the subprocess? | `webapp/job_runner.py::_build_job_config` (`_secret_env` → `start` env) |
| How does the UI know the job state? | `/api/jobs/<id>/events` SSE + `webapp_jobs/<id>/progress.json` |
| How are tokens stored / revoked? | `webapp/app.py::/api/google/upload|authorize|disconnect` + `_google_dir()` |
| How does i18n switch language? | `webapp/static/i18n.js` (loads on every page; `langToggle` button) |

---

## 7. Testing

The full suite is **offline-deterministic** and runs in seconds:

```bash
python -B -m unittest discover -s tests
```

Live integrations (GSC, GA4, PageSpeed, AI) are tested via **parsers** on synthetic
responses — never against the real network. The crawler is tested against a tiny
in-process HTTP fixture (`tests/test_core_behaviors.py`).

See `CONTRIBUTING.md §1` for the full commit gate.
