# Contributing to SCT

Thanks for helping improve SCT (the *Simple Crawler Tool*). The project aims to stay
**reliable**, **transparent**, **respectful to crawled websites**, and **bilingual**
(every user-facing string in Arabic and English).

> النسخة العربية لهذا الدليل في [`CONTRIBUTING_AR.md`](CONTRIBUTING_AR.md).
> Architecture, module map, and design decisions live in
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## 1. Local setup

Requires **Python 3.10+**.

```bash
python -m pip install -r requirements.txt
playwright install chromium      # only for JS rendering + PDF reports
python webapp/run.py             # then open http://127.0.0.1:8000
```

Run the test suite:

```bash
python -B -m compileall -q seo_crawler webapp
python -B -m unittest discover -s tests
```

Validate UI JS:

```bash
node --check webapp/static/i18n.js
```

The full commit gate is `compileall + unittest`, plus `node --check` on `i18n.js` and any
inline `<script>` block you touched (strip Jinja first — see `docs/ARCHITECTURE.md`).

---

## 2. Code style

**Python:** PEP 8 + the project conventions you'll see in existing modules:

- Type hints everywhere.
- `from __future__ import annotations` at the top of new modules.
- Docstrings on every public function/class — Arabic is fine for internal notes; keep
  function/parameter names in English.
- Prefer **pure functions** for analyzers/parsers (they're easy to test offline).
- Use `utils.logger.get_logger(__name__)` for logging — never `print()` in library code.

**JavaScript** (inline in templates + `webapp/static/i18n.js`):

- ES2015+ (arrow functions, `const`/`let`, template strings).
- No build step — keep it inline / vanilla. Don't pull in jQuery, React, or bundlers.
- Every user-visible string must use `data-i18n="key"` (HTML) or `T('key', 'fallback')`
  (JS). Both AR and EN entries are required (see §4).

**HTML/CSS:** the form lives in `webapp/templates/index.html`. Tabs are flat panes
(`data-pane="..."`), not heavy components. Style sits in `webapp/static/app.css` and a
small inline `<style>` in `index.html`.

---

## 3. Safety rules (hard constraints — do not break)

- **No secrets in the repo.** OAuth client secrets, API keys, tokens, `.env` files, and
  any `*_token.json` are all gitignored. Credentials enter through `.env` or per-job UI
  config (kept under `webapp_jobs/_google/` which is gitignored).
- **All external integrations are optional and OFF by default.** When you add one, the
  default config value is `false`/empty, and the tool must work without it.
- **No PII** is collected from GA4 or sent to AI providers — only URLs, issue types, and
  aggregate numbers.
- **Outbound HTTP that follows user URLs** must pass through `utils.helpers.is_safe_remote_url`
  (SSRF guard) unless the user explicitly opted into private hosts.
- **CSV/Excel outputs** must neutralise formula injection — use `utils.helpers.neutralize_formula`.
- **XML parsing** must use `defusedxml`, not the standard library.
- **Streaming downloads with size caps** for anything user-fetched (sitemap, robots.txt,
  log uploads, etc.).
- **Don't commit generated folders** — `output/`, `state/`, `logs/`, `webapp_jobs/`,
  `__pycache__/`, `.pytest_cache/` are all gitignored.

---

## 4. Bilingual i18n discipline

Every user-facing string lives in `webapp/static/i18n.js` under both `ar` and `en` dicts.
After editing UI, run the local audit:

```bash
python _review/i18n_audit.py
```

It compares keys used in templates/JS against both dicts and prints any missing keys per
language. The two dicts must stay perfectly aligned (every key in `ar` is also in `en`).

For dynamic strings in JS, use `T('key', 'AR fallback')` so the page still works if a key
is missing (and the audit will catch it on next run).

---

## 5. Adding a new analyzer

Analyzers are pure functions over crawled data. Pattern:

1. Create `seo_crawler/seo_crawler/analyzers/<name>.py` exporting a function
   `analyze_<name>(...)` that returns a `dict` with `{"<rows>": [...], "summary": {...}}`.
2. In `seo_crawler/seo_crawler/main.py::run_analysis`, import and call it, storing the
   result under `results["<name>"]`.
3. In `seo_crawler/seo_crawler/main.py::run_export`, add a CSV export from the rows.
4. Optional: add an HTML report section in `seo_crawler/seo_crawler/exporters/html_exporter.py`
   (register in `EXPERT_SECTIONS` or `CLIENT_SECTIONS`).
5. Add a regression test in `tests/test_core_behaviors.py` with synthetic input — should
   run offline in milliseconds.

See `analyzers/gsc_insights.py` or `analyzers/log_analyzer.py` for clean examples.

---

## 6. Adding a new integration (off by default)

1. Create `seo_crawler/seo_crawler/integrations/<name>_api.py` with a small client class.
2. Add `<name>: { enabled: false, ... }` to `config.example.yaml` + `config.yaml`.
3. Wire it in `main.py::run_integrations` (gated by `enabled`).
4. Add a card to the *Integrations & AI* tab in `webapp/templates/index.html` with the
   enable checkbox + config fields + a test button.
5. Add a JSON endpoint `/api/test/<name>` if you want a "Test connection" button.
6. Secrets: never write to disk; pass via `os.environ` from `job_runner._secret_env`
   (see how `PAGESPEED_API_KEY` and `AI_API_KEY` are handled).

---

## 7. Adding a new UI tab / page

- Tab inside the main form: add `<button data-tab="X" data-i18n="tab_X">` and
  `<div class="tabpane" data-pane="X">` in `webapp/templates/index.html`. Existing JS
  picks them up generically.
- Separate page (like the Action Board / Log analyzer): add a FastAPI route returning
  `templates.TemplateResponse("<name>.html", ...)`, the template under
  `webapp/templates/`, and the AR + EN i18n keys.
- A persistent top-bar link to a separate page goes in the `<header class="topbar">` of
  `index.html` *and* `job.html`.

---

## 8. Branching, commits, and pull requests

- Default branch: `main`.
- Feature branches: short, lowercase, dash-separated (`add-foo-analyzer`).
- Commit messages: imperative mood, one focused change per commit (`Add foo analyzer`),
  not (`updated stuff`). Reference an issue when relevant.
- Before opening a PR:
  ```bash
  python -B -m compileall -q seo_crawler webapp
  python -B -m unittest discover -s tests
  node --check webapp/static/i18n.js
  python _review/i18n_audit.py
  ```

---

## 9. Release process

SCT uses a simple two-digit decimal scheme: `1.00 → 1.01 → 1.02 → …`. Every shipped
change bumps the digits after the dot. Steps:

1. Update **`seo_crawler/seo_crawler/exporters/json_exporter.py`** — change
   `_meta.version` to the new number.
2. Update **`webapp/templates/index.html`** — the topbar `<small class="version-tag">`.
3. Add a section to **`CHANGELOG.md`** at the top: `## vX.YY — YYYY-MM-DD` with
   `### Added / ### Fixed / ### Changed`.
4. Run the full verify (§8).
5. Commit on `main` with a message like `vX.YY: <one-line summary>`.
6. `git push origin main`.

---

## 10. Reporting bugs / suggesting features

- Bugs: open a GitHub issue with reproduction steps, the relevant section of
  `webapp_jobs/<job_id>/run.log`, and your environment (OS, Python, mode).
- Features: open a discussion or issue prefixed with `[idea]`. Items that are clearly
  scoped get added to `ROADMAP.md`.

---

By contributing you agree your work is licensed under the project's MIT licence
(see [`LICENSE`](LICENSE)) and that you'll follow the
[Code of Conduct](CODE_OF_CONDUCT.md).
