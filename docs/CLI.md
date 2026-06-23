# SCT — Command-line reference

> النسخة العربية: [`CLI_AR.md`](CLI_AR.md).
> For the web UI (the recommended interface), see [`USER_GUIDE.md`](USER_GUIDE.md).

SCT ships with two entrypoints:

1. **`python main.py`** — runs a single crawl / audit (no web server).
2. **`python webapp/run.py`** — starts the local web UI (FastAPI + uvicorn).

Both read the same `config.yaml` for defaults. CLI flags override anything in the config.

---

## 1. The crawler / audit CLI — `python main.py`

```
usage: main.py [-h]
               [--mode {audit,competitor,compare}]
               [--url URL]
               [--config CONFIG]
               [--sync]
               [--analyze-only]
               [--no-resume]
               [--skip-external]
               [--integrations-only]
               [--phase2]
               [--clear-cache]
```

### Flags

| Flag | Default | What it does |
|---|---|---|
| `--mode {audit,competitor,compare}` | `audit` | Crawl mode. `audit` = full site audit. `competitor` = limited crawl of a competitor (uses the same analyzers but doesn't expect ownership). `compare` = crawl several sites from `sites_to_compare` in the config and produce a comparison Excel. |
| `--url URL` | (config's `site.start_url`) | Override the start URL for this run only. Domain is derived from the URL. |
| `--config CONFIG` | `config.yaml` | Path to a different config file. |
| `--sync` | off | Use the synchronous crawler instead of the async one. Slower, but useful for diagnostics on environments where `aiohttp` misbehaves. |
| `--analyze-only` | off | Skip the crawl phase and re-analyze a previously stored SQLite DB (under `state_dir`). Useful when you only changed analyzer thresholds. |
| `--no-resume` | off | Start fresh: ignore any saved `visited`/`queue` state and crawl from scratch. |
| `--skip-external` | off | Don't check external link statuses (faster). |
| `--integrations-only` | off | Skip the crawl entirely; only fetch the optional integrations (GSC/GA4/PageSpeed) and export their CSVs. |
| `--phase2` | off | v1.08: run **Phase 2** — re-uses `deferred_urls.csv` from the matching Phase 1 output as the seed list and bypasses the URL classifier (every URL is crawled). Extends the existing `audit.json` instead of writing a new one. Useful when Phase 1 deferred pagination-deep / redirect-wrapper / filter-combination URLs and you've decided you do want them crawled. |
| `--clear-cache` | off | Wipe the API cache (`state/api_cache.db`) and exit. |

### Example scenarios

```bash
# Default: full async audit using config.yaml's site.start_url
python main.py

# Quick competitor scan, overriding the URL
python main.py --mode competitor --url https://example.com/

# Resume a crashed run, do not re-crawl already-visited URLs
python main.py

# Re-run analyzers without re-crawling (e.g. after changing thresholds)
python main.py --analyze-only

# Fresh run, ignore any saved state
python main.py --no-resume

# Compare several sites listed in config.yaml::sites_to_compare
python main.py --mode compare

# Fetch only the integration data, no crawl
python main.py --integrations-only

# Run Phase 2 on the deferred URLs the previous run produced
# (extends the existing audit.json in the same output folder)
python main.py --phase2

# Use a different config (e.g. a per-client config)
python main.py --config configs/clientA.yaml

# Wipe the on-disk API cache (PageSpeed/etc.) and exit
python main.py --clear-cache
```

### Environment variables

| Env var | Effect |
|---|---|
| `PAGESPEED_API_KEY` | PageSpeed Insights key, read as a fallback if config is empty. |
| `AI_API_KEY` | Key for the AI advisor (provider chosen in config). |
| `GA4_PROPERTY_ID`, `GA4_CREDENTIALS_FILE` | Fallback values for the GA4 integration. |
| `SCT_PROGRESS_FILE` | Set automatically by the web `JobRunner` so the subprocess can stream phase/counter updates to a JSON file the UI polls. |
| `SCT_NONINTERACTIVE` | Set to `1` by the web `JobRunner`. When set, OAuth never opens a local browser; it returns a clear error instead of hanging the subprocess. |
| `SCT_NO_AUTO_INSTALL` | Set to `1` to disable the auto-install helper (`utils/auto_install.py`). Optional libraries will then need to be installed manually with `pip`. |
| `SCT_AUTO_INSTALL` | v1.12: opt-in re-enable of the auto-install helper. Default is **off** since v1.12 (used to be on). Set to `1` only if you need the legacy behavior. |
| `BACKLINKS_API_KEY` | v1.04 backlinks integration. Ahrefs v3 uses `Authorization: Bearer <key>`; Majestic OpenApp expects the same env var. Off by default — only consulted when `integrations.backlinks_api` is enabled in config. |

---

## 2. The web UI launcher — `python webapp/run.py`

```
usage: run.py [-h] [--host HOST] [--port PORT] [--reload]
```

| Flag | Default | What it does |
|---|---|---|
| `--host` | `127.0.0.1` | Network interface to bind. Use `0.0.0.0` to expose on the LAN. |
| `--port` | `8000` | TCP port. |
| `--reload` | off | uvicorn auto-reload (development only). |

Examples:

```bash
# Local-only UI on the default port
python webapp/run.py
# then open http://127.0.0.1:8000

# LAN-accessible on a custom port
python webapp/run.py --host 0.0.0.0 --port 9000

# Hot-reload during development
python webapp/run.py --reload
```

The web UI gives you everything the CLI gives you, plus job tracking, integration setup,
the Action Board, the URL drill-down, and log analysis. For one-shot CLI use, `main.py`
remains the lighter option.

---

## 3. Docker — `docker compose up --build`

The official Playwright image bundles Chromium so JS rendering and PDF reports work out
of the box. Outputs persist in `./webapp_jobs`, secrets are read from `.env` at runtime
(never baked into the image). See the project `README.md` for details.

---

## 4. Windows installer — `installer/install.ps1`

A no-admin PowerShell installer that creates a local venv, installs requirements,
installs Chromium for Playwright, and adds Desktop + Start Menu shortcuts that launch
the web UI. See `installer/README.md`.
