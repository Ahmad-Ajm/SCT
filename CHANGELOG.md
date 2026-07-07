# Changelog

> **Versioning convention:** SCT uses a simple two-digit decimal scheme — the integer part
> marks a major milestone (`1`), and every subsequent change bumps the digits after the dot
> (`1.00` → `1.01` → `1.02` → …). Author: **Ahmad-Ajm**.

## v1.13.21 (2026-07-07 welcome-banner always-shown + Stop/Kill race fixes + RUNBOOK §9)

Three user-reported issues addressed in one pass:

### 1. Welcome banner shows every launch (dismissible)
Previously the "👋 مرحباً في SCT" card only appeared when there were
zero jobs on disk (`{% if not jobs and not active_job %}`). The moment
a user completed one crawl it vanished forever. The user asked for it
to always show but be dismissible with an X.

Changes in `webapp/templates/index.html`:
- Removed the Jinja conditional wrapping the `<div class="welcome">`.
- Added `id="welcomeBanner"`, `id="welcomeDismiss"` (X button),
  `position:relative` on the container, and CSS for the absolutely
  positioned close button (uses `inset-inline-end` for RTL/LTR safety).
- Inline IIFE at the bottom of `<script>` reads
  `localStorage['sct_welcome_dismissed']`; if the user has clicked X
  in the past, the banner stays hidden. Otherwise it shows on every
  page load. Wraps in `try/catch` so that private-browsing mode (where
  `localStorage` throws) falls through to always-show — no crash.

`webapp/static/i18n.js`: two new keys (AR + EN) —
`welcome_dismiss_title` and `welcome_show_again`.

### 2. `force_kill()` race condition (Fix 2 in the parallel to Fix 1)
`stop()` was already patched in v1.13.15 to hold the lock across
`lookup + write_meta + send_signal`. `force_kill()` still had the old
pattern where the lock was released between lookup and the actual
`proc.kill()`, letting `_watch` sweep the proc out from under it
(returning `False` even though the subprocess was still running). Now
mirrors the `stop()` pattern: everything under a single `with
self._lock` block. Same `log.warning` on missing proc so orphan
subprocesses are visible in the log.

### 3. RUNBOOK §9 — disappearing job folders on Windows
The user's `webapp_jobs/` folder went from 3 jobs to just `_google`
between operations, with no user delete action. Comprehensive grep
confirmed **the tool has zero automatic deletion code** — only user
button clicks reach `delete_job`/`delete_all_jobs`, and there is no
scheduler, TTL, or background sweeper. The likely OS-level culprits
are:

- **Windows Storage Sense** (aggressive default in Windows 11 —
  deletes files in folders named `logs`, `cache`, `temp`, and stuff
  older than N days from `%USERPROFILE%`)
- **Antivirus real-time protection**
- **OneDrive Files On-Demand** dehydration/sync deletions

Added `docs/RUNBOOK.md` §9 documenting:
- How to confirm the tool itself never deleted anything (with
  `grep -rn 'rmtree\|unlink' webapp/` recipe)
- PowerShell to read Storage Sense state and disable it
- Antivirus exclusion steps
- Recommended safe install path: outside `%USERPROFILE%` and outside
  any sync tool root

Also added a v1.13.21 breadcrumb at the top of RUNBOOK.md.

Version bumped to 1.13.21. 94/94 tests still green.

---

## v1.13.20 (2026-07-07 self-heal corrupted job.json + repair 3 legacy jobs)

**The bug the user saw.** The "Recent Jobs" (المهام الأخيرة) table on
the home page had three rows with EMPTY cells for job-id / URL / mode,
and clicking "عرض" (View) just refreshed the page instead of opening
the job report. Because `href="/jobs/{{ j.job_id }}"` rendered as
`/jobs/` when `j.job_id` was empty, hitting the v1.13.19 redirect that
sent it back to `/`.

**The root cause.** All three `job.json` files on disk had been
truncated to just the terminal fields (`status`, `return_code`,
`ended_at`, `result`, `diagnostics`) — the initial `job_id`, `mode`,
`url`, `started_at`, `config` fields were missing. This was almost
certainly a race condition from before v1.13.16 F45 (atomic writes):
if `_watch()` ran during a partial `_write_meta()` write, `_read_meta()`
would see an empty/corrupt file, return `{}`, then `_watch()` would add
just the terminal fields to that empty dict and write it back —
effectively wiping the initial data.

**Self-heal at read time (`_read_meta`).** Now every time a job's meta
is read, missing fields are backfilled from authoritative alternate
sources:
- `job_id` from the directory name (100% reliable — the filesystem is
  the source of truth for the ID).
- `url` from `config.yaml::site.start_url`, with fallback to a regex
  scan of the first 5 KB of `run.log` for `🌐 Target URL:` (works
  even if `config.yaml` itself is missing).
- `mode` defaults to `audit` (the overwhelming majority of runs).
- `started_at` reconstructed from the folder-name timestamp
  (`YYYYMMDD_HHMMSS_hex`).
- `config` points at `config.yaml` if the file exists.

**Defense in depth (`_watch`).** Even in the post-atomic-write world, if
some future refactor or race trips the read again, `_watch()` now
`setdefault("job_id", job_id)` before writing so the ID never
disappears. Belt-and-suspenders alongside the read-time self-heal.

**One-time repair of the 3 existing files on disk.** A small script ran
the new `_backfill_meta` on each `webapp_jobs/*/job.json` and wrote
the reordered result back. All three jobs now have their correct URL
(`internal-zid-test.example` / `internal-wp-test.example` / `internal-zid-test.example` again) and
`mode=audit`.

**Regression tests (94/94 now).** Added `test_read_meta_self_heals_missing_fields`
that constructs a corrupted `job.json` in a tempdir and verifies
`_read_meta` fills every expected field. Also added
`test_jobs_slash_redirects_home` locking in the v1.13.19 302 behavior
so a future refactor doesn't silently break the /jobs URL that this
same table's "View" button generates.

---

## v1.13.19 (2026-07-07 redirect /jobs and /jobs/ to home)

User navigated to `http://127.0.0.1:8000/jobs/` expecting a job listing
and got `{"error":"Not Found","request_id":"..."}`. FastAPI had no
route for the collection path — only `/jobs/{job_id}`. The home page
already shows "المهام الأخيرة" (Recent Jobs), so a 302 to `/` is the
right move.

Added `@router.get("/jobs")` and `@router.get("/jobs/")` in
`webapp/routers/pages.py` returning `RedirectResponse(url="/",
status_code=302)`. Both `include_in_schema=False` so they don't
clutter OpenAPI docs.

---

## v1.13.18 (2026-07-06 UI toggles for JS-render + accessibility)

The `javascript.enabled` and `accessibility.enabled` config keys have
existed since v1.03 but were only settable by editing `config.yaml` by
hand — the crawl-form UI had no checkboxes for them. Users who wanted
to test a SPA / React storefront or produce an axe-core report had to
find the config file and edit it, then reset it before running an
integrations-only job. That's a real friction point.

Two new checkboxes surface both features in the crawl form under
"Advanced":

- **🌐 تصيير JavaScript (Chromium/Playwright)** — `name="js_render"`,
  wired to `javascript.enabled`. Extra number field
  `name="js_max_pages"` (default 100) caps the number of pages rendered
  via Chromium (rendering is 5-10× slower than plain HTTP, so a cap is
  essential on big sites).
- **♿ فحص الوصولية (axe-core / WCAG)** —
  `name="accessibility_check"`, wired to `accessibility.enabled`.
  Number field `name="accessibility_max_pages"` (default 50). When
  the box is checked, `job_runner._build_job_config` also forces
  `javascript.enabled = true` (axe needs a browser to run) and sets
  `accessibility.allow_cdn = true` so axe-core is fetched from jsdelivr
  without needing a local file.

Plumbing:
- `webapp/templates/index.html`: two `<label class="chk">` blocks +
  two number inputs added right after `generate_sitemap`.
- `webapp/static/i18n.js`: 8 new keys (labels + tooltips, AR + EN).
- `webapp/routers/jobs.py`: 4 new overrides parsed via `_b` and
  `_safe_int` (the same defensive helpers used everywhere else).
- `webapp/job_runner.py::_build_job_config`: writes them to
  `cfg["javascript"]` and `cfg["accessibility"]`.

No new API surface — the config-writing path is the existing one, so
CLI users can still set the same keys in `config.yaml` and get the
same behavior.

92/92 tests. Version bumped to 1.13.18.

---

## v1.13.17 (2026-06-25 Top-10 pre-publication audit fixes — 18 confirmed via parallel agents)

A 14-dimension deep audit surfaced 70 findings (4 critical / 42 high /
19 medium / 5 low). The Top 10 priority list was applied via 5 parallel
fix agents (partitioned by file, no overlap) + 5 adversarial verifiers
+ a synthesizer. 18 fixes landed cleanly; 2 follow-ups (regression +
UX nit) were applied by hand. 1 deferred for a future release.

### Group A — OAuth security (#1, #2 — webapp/routers/google_oauth.py)
- **F31 — OAuth state validation (CSRF):** 32-byte URL-safe state
  generated per authorize-url, stored as the lookup key for the Flow.
  Callback parses state from the pasted URL, pops the matching entry
  under lock (one-shot), rejects 400 if missing/unknown/expired. Also
  passes the full `authorization_response` URL to `flow.fetch_token`
  so google-auth-oauthlib does its own state verification as
  defense-in-depth.
- **F32 — `_paste_flow` concurrency:** Replaced module-level single-slot
  dict with `_paste_flows` keyed by state token. All reads/writes under
  `threading.Lock` (FastAPI threadpool). 10-min TTL eviction on every
  insert/pop. Two simultaneous users can no longer overwrite each
  other's flow.

### Group B — Frontend XSS (#5 — webapp/templates/job.html)
- **F49 — innerHTML interpolation:** Three sites (renderDownloads,
  loadFiles, _renderDeferred) now use `createElement` + `textContent` +
  `appendChild` instead of string concatenation into innerHTML.
- **F50 — `_esc()` helper:** Full HTML-entity escape (`& < > " '`) for
  the remaining places where innerHTML is unavoidable (deferred-samples
  builder concatenates a multi-line block). Replaced the partial
  `.replace(/&/g,'&amp;').replace(/</g,'&lt;')` that missed `> " '`.
- **F52 — `_safeLogoUrl()` validator:** Requires `^https?://` and
  explicitly rejects `javascript:`, `data:`, `vbscript:`, `file:`,
  `blob:`. Wired into genForm submission with a bilingual alert on
  invalid input. Empty values are deleted from FormData (not sent).
- **F53 — token-in-URL (DEFERRED):** Removing `?token=` from
  navigation/SSE/download URLs needs a short-lived ticket-cookie
  refactor (new `/ticket` endpoint issuing HttpOnly Set-Cookie + backend
  acceptance of the cookie alongside `Authorization`). EventSource and
  `<a href>` can't carry an `Authorization` header, so a direct removal
  would break SSE + all downloads. Deferred to v1.14.

### Group C — Crawler race + memory (#4, #10 — async_core.py + js_renderer.py)
- **F01 — URL discovery race:** Wrapped the
  `visited/queued_urls` check + `_enqueue` call in
  `async with self._visited_lock`. Verified `_enqueue` doesn't
  re-acquire the same lock (no recursive-lock deadlock).
- **F02 — Deferred-dict race:** Added a dedicated `self._deferred_lock`
  in `__init__`; wrapped the deferred check + cap + write in
  `async with self._deferred_lock` inside `_enqueue`. Classifier is
  sync — kept outside the lock.
- **F03 — JS renderer success flag:** Initialized
  `result.is_success = False` at the start of `render()`; moved the
  `True` assignment to the very end of the try block (after axe-core
  completes). An exception anywhere keeps it `False`.
- **F04 — JSRendererAsync SSRF config:** Added
  `allow_private_hosts` as an explicit `__init__` param; passed through
  from `AsyncCrawler`. No more silent `getattr` fallback to `False`
  that disabled the SSRF policy.
- **F05 — `all_js_diff` unbounded list:** Capped at 100 000 entries
  (configurable via `js_diff_max_entries`) with a dropped counter,
  one-time warning, and `crawler.js_diff.cap_dropped` metric.
- **F06 — `all_accessibility` unbounded list:** Capped at 50 000 entries
  (configurable via `accessibility_max_entries`) with same dropped
  counter + warning + metric pattern.

### Group D — Webapp lifecycle (#6, #7 — job_runner.py + generate.py)
- **F61 — Strip credentials from per-job config.yaml:** Added
  `_SENSITIVE_KEYS` frozenset (`credentials_file`, `api_key`, `token`,
  `secret`, `client_secret`, `service_account_key`) and a recursive
  `_strip_sensitive_in_place()` walker. Runs after `_build_job_config`
  builds the dict and BEFORE `yaml.safe_dump` writes it to disk. The
  removed keys are still passed to the subprocess via `_secret_env`
  → environment variables. Job-directory artifacts no longer leak
  credential paths if a user shares the folder.
- **F45 — Atomic JSON writes:** New `_atomic_write_json()` helper writes
  to `path.tmp` then `os.replace(tmp, path)`. Replaced direct
  `json.dump` calls in `_write_meta` and `_write_progress`. Mid-write
  crash can no longer leave a half-written JSON file.
- **F46 — Subprocess log-handle leak:** Parent now calls
  `log_file.close()` immediately after `subprocess.Popen` returns (the
  subprocess inherits its own duplicated fd). Fixes Windows
  "file in use" errors when the webapp later tries to read or delete
  the log.
- **F47 — Generate.py race:** Per-job `threading.Lock` dict (guarded by
  a creator lock). The long-running format generation (PDF can take
  minutes) runs outside the lock; only the `meta` read-modify-write
  tail is serialized. Local `_atomic_write_json` duplicates the
  job_runner pattern. Concurrent HTML+PDF requests no longer corrupt
  `meta["result"]`.

### Group E — Quick wins (#3, #8, #9 — 5 files)
- **F28 — Gemini response parsing hardened:** Chained subscripting
  replaced with `.get()` / default chain so malformed responses return
  `""` + warning instead of crashing the entire audit.
- **F21 — CSV/Excel formula-injection whitespace bypass:** `_csv_value`
  now strips leading whitespace (space, tab, CR, LF, U+200B zero-width,
  U+FEFF BOM) before the trigger-char check. Closes the `' =SUM(1+1)'`
  / `'\t@cmd'` bypass.
- **F27 — Robust numeric parsing in report_join:** `_sf()` / `_si()`
  safe parsers added; `ctr`, `position`, `engagement_rate` now use
  `_sf` instead of bare `float()`. Malformed GSC/GA4 values
  (`None`, `"N/A"`, `"-"`) no longer raise `ValueError`. Cascading
  this pattern to other files is a follow-up.
- **F58 — `DatabaseBackedCrawler` real duration:** `get_stats()` now
  returns real `duration_seconds` and `pages_per_second` (start_time
  from db meta with `time.time()` fallback) instead of hardcoded 0.
  `--analyze-only` reports the actual elapsed time.
- **F57 — Re-raise `KeyboardInterrupt` (NOT APPLIED):** Verifier
  determined this is "already-correct, not actually deferred". The
  v1.13.15 (B2) design deliberately swallows the interrupt at the
  export phase so partial results land on disk. Re-raising would
  undo that fix. No change made.

### Follow-up fixes applied by hand after the workflow
- **integrations_service.py:46:** Group D's F61 strip removed
  `gsc.credentials_file` from per-job configs but `GSCClient`
  construction still read `gsc_config["credentials_file"]` directly
  with no env-var fallback — would crash GSC at runtime. Added
  `creds = gsc_config.get("credentials_file") or
  os.getenv("GSC_CREDENTIALS_FILE", "")` matching the existing GA4
  pattern. Without this fix the OAuth scrubbing would have broken
  every GSC integration.
- **webapp/templates/index.html:** Hint text said "paste the URL or
  the code", but Group A's F31 fix now rejects bare codes (state must
  be present in a callback URL). Updated three places to say
  "paste the FULL callback URL (with state + code)" instead.

### Verification stage findings
- 0 unauthorized file writes (every agent stayed within its assigned
  files).
- 0 syntax errors detected by the verifier read-throughs.
- 1 new regression introduced (GSC env-var fallback above) — caught by
  verifier and patched.
- 1 UX inconsistency surfaced (paste-hint text) — patched.

92/92 tests on Windows. Version bumped to 1.13.17.

### What's NOT fixed (deferred to v1.14 or later)
- **F53** (token-in-URL): needs ticket-cookie architecture refactor.
- **F27 cascade**: bare `float()` / `int()` calls in other files
  (priority_engine, integrations_summary, log_analyzer,
  thin_content) — only `report_join.py` was patched.
- **F21 cascade**: the leading-whitespace strip lives inside
  `_csv_value` only; the shared `utils.helpers.neutralize_formula`
  still has the original bug for any other caller.
- **All 60 medium/low findings** from the audit (per-area cleanups,
  latent risks, hardening polish). The 5 architectural risk patterns
  (`except Exception: pass`, module-level mutable globals,
  non-atomic writes, URL normalization inconsistency, blind trust in
  external APIs) need a dedicated refactor pass.

---

## v1.13.16 (2026-06-25 Stop-flow follow-up — fast minimal export + UI clarity)

User re-tested v1.13.15 on the same WordPress site and reported three
remaining issues:

1. **Google integrations tried to fetch on stop** — they had enabled
   Google integration toggles in the form but never linked credentials.
   When Stop was clicked, the partial-export path ran through
   `run_integrations()`, which tried to authenticate and slowed down
   the graceful-shutdown window.
2. **Reports still didn't appear without a manual refresh** — the
   v1.13.15 polling loop fired `_safeFinish` the moment `meta.status`
   went terminal, but at that point `meta.result` was the empty `{}`
   (subprocess had been terminate()-d at the 60s grace expiry before
   it reached `run_export()`). The results panel rendered but the
   download buttons pointed at non-existent files.
3. **Downloaded file was empty** — same root cause as #2: the export
   never ran. The ZIP-all endpoint built an archive from an empty
   `output/` directory and returned 22 bytes.

### E-Stop — drastic shortcut to minimal export on stop signal

`seo_crawler/main.py::main_async` now branches **immediately after
the crawl phase**: when `stopped_early=True`, it skips
`run_analysis()`, all of Phase 2.5 (external-link check), Phase 2.6
(resource status), Phase 3 (integrations), the GSC-insights block,
the unified-report builder, and the AI advisor — going straight to
`run_export()` with `analysis={}` and `integrations={}`. Result: a
60-second graceful shutdown now leaves enough budget for `run_export()`
to actually write the `pages.csv` and `pages.json` files from
whatever SQLite captured before the stop. The user gets real data, not
empty files. Integrations never try to authenticate, so no slow
Google-API timeout on the way out.

### UI: `_safeFinish` waits for actual files, phase bar hides on terminal

- `_hasFiles(result)` helper added: returns true only when `result` is
  an object with at least one key. JS treats `{}` as truthy, so the
  old `if (meta.result)` check fired even when no exports existed.
- Three call sites updated to gate on `_hasFiles(meta.result)`:
  the SSE `onmessage`, the polling `_pollOnce`, and the stop-button
  active polling loop.
- The stop-button loop now has a graceful tail: if the subprocess
  truly died with `ended_at` set but `result={}` (e.g. user clicked
  force-kill before export ran), `_safeFinish` still fires so the
  badge shows the right final state — just without download buttons.
- `applyStatus()` now hides `#phaseBox` when the status is terminal.
  Previously the user saw badge `أوقف` (stopped) AND progress-bar
  `جار التحليل...` (analyzing) at the same time. The bar reflected a
  stale `progress.json::phase_label` written before the stop signal
  arrived; hiding it removes the contradiction.

92/92 tests. Version bumped to 1.13.16.

The recent-jobs panel showing "only 3" question: the home-page list
is hardcapped at 15 (`pages.py:37`). The current `webapp_jobs/`
directory holds 4 job folders (2 from today + 1 from June 23 + 1 from
May 28). Earlier sessions had more, but they were deleted explicitly
via the `🧹 حذف الكل (عدا النشطة)` button — that endpoint
permanently removes the folders from disk. There's no soft-delete.

---

## v1.13.15 (2026-06-25 Stop-flow re-root — true fixes for the same 3 bugs + 3 hardening items)

A second live-test on the same WordPress site reproduced the user's
report: clicked Stop → badge showed **فشل** in red, report panel did
not appear without manual refresh, downloaded report was **empty**.
The v1.13.11 F5/F7 patches did NOT actually fix the underlying causes
— they fixed the wrong layer. A 5-dimension adversarial workflow
re-rooted each bug and found the real culprits.

### B1 (real fix) — TOCTOU race between `stop()` and `_watch()` on `meta.status`
`stop()` only wrote `meta.status="stopped"` AFTER `proc.wait()` returned.
By that point `_watch` (waiting on the same subprocess in another thread)
had often already read `meta.status="running"`, seen `rc != 0` from the
subprocess exit, and overwritten the job to `status="failed"`. v1.13.11's
F5 fix added a `progress.json` sync to mirror `meta.status`, but it
mirrored the wrong decision after the race had already been lost.
**Fix:** `stop()` and `force_kill()` now write `meta.status="stopped"`
**BEFORE** sending the signal. `_watch` reads that marker no matter who
wins the `proc.wait()` race and short-circuits to keeping `stopped`.

### B2 (real fix) — subprocess killed mid-analysis, never reached export
The crawler subprocess took >8s to graceful-shut after `CTRL_BREAK_EVENT`
(analysis phase on partial data is expensive — link-score, near-duplicate,
priority engine). `stop()`'s `proc.wait(timeout=8)` expired, `terminate()`
was called, subprocess died **before reaching `run_export()`**. Output
directory stayed empty. v1.13.11 didn't touch this layer at all.
**Fix (three parts):**
1. `stop()` is now **non-blocking** — sends signal, returns immediately,
   delegates the wait+escalate to a background thread. Grace raised from
   8s to **60s** so analysis + export have realistic time. The HTTP
   request returns in <100ms; the UI polls until terminal state.
2. `main_async()` now wraps `await run_crawl_async()` AND `run_analysis()`
   AND `run_export()` in `try/except (KeyboardInterrupt, CancelledError)`
   — if the interrupt arrives mid-phase, we fall through to the next
   phase with whatever partial state was collected, instead of bubbling
   up to `main()`'s `sys.exit(130)` and losing everything.
3. The crawler `_external_stop` flag is now set in every catch so the
   downstream phases skip the slowest substeps (external-link check,
   resource-status check) and go straight to a minimal export of pages.

### B3 (real fix) — `stopBtn` polling that gave up after one shot
v1.13.11's F7 patch fetched `/progress` once after 600ms and gave up if
`meta.result` wasn't ready. With the backend grace at 8s (now 60s),
this single fetch ran way before the subprocess had finished writing
its exports. The result panel stayed hidden until manual refresh.
**Fix:** Replaced the one-shot 600ms fetch with an **active polling
loop** at 800ms intervals for up to 90s (covers 8s signal travel + 60s
backend grace + a buffer). Triggers `_safeFinish` the moment
`meta.status` reaches any terminal value
(stopped/complete/partial/partial_max_pages/failed) — even with an
empty `result`, so the user sees the correct status badge instead of a
stuck "running" UI. Honors the `_finishedOnce` guard so the other two
safety-net paths (SSE end / polling fallback) still race cleanly.

### Hardening items folded into the same commit

- **A1-1 — Bare `int()` / `float()` on form input would 500 on
  non-numeric values.** `webapp/routers/jobs.py` had five sites of
  `int(form.get("max_pages", 500) or 500)` that blow up if the user
  types "abc" in a number field. Now they go through `_safe_int` /
  `_safe_float` helpers that fall back to the default on `ValueError`
  / `TypeError`. The cause was that the existing `_int_or_none` helper
  caught the exception but the bracket-style int() conversions in the
  `overrides` dict didn't use it.
- **A2-1 — `config["output"]["output_dir"]` `KeyError` on partial
  configs.** `services/config_service.py::setup_output_dir` indexed
  `config["output"]` directly, crashing if a CLI invocation didn't go
  through the full config-merge layer. Now uses `.get()` with safe
  defaults.
- **A2-2 — Windows signal handler not restored on
  `_remove_signal_handlers`.** `crawler/async_core.py` installs a fallback
  `signal.signal()` handler on Windows (where `loop.add_signal_handler`
  is `NotImplementedError`) and saves the previous handler in
  `_prev_handlers`, but never restored it. Subsequent SIGINTs in the
  same process would still go to the old crawler's handler. Now
  `_remove_signal_handlers` restores `_prev_handlers` and clears the
  dict.

### What the user should re-test

1. Start a crawl on a slow site, click **Stop** within 30 seconds.
2. Status badge must transition `running → stopping → stopped` (NOT
   `failed`). May take up to 60s for the backend to finalize.
3. The results panel + download buttons must appear automatically (no
   manual refresh).
4. Downloaded CSV/JSON must contain ROWS for the pages crawled before
   stop (not just headers, not zero bytes).
5. Open `webapp_jobs/<job_id>/job.json` and `progress.json` — both must
   show `status: "stopped"` (no longer divergent).
6. Run a full crawl to completion as a regression check — the happy
   path must still end at `status: "complete"` and download fully.

92/92 tests on Windows.

Deferred items (separate future commit): HttpOnly cookie for auth
token (A1-4), TTL on module-level state dicts (A1-5), JSON-schema
validation on custom extraction rules (A1-7), Playwright shutdown
timeout (A2-3).

---

## v1.13.11 (2026-06-24 live-test bug sweep — 3 race-condition fixes)

Three fixes triggered by the user's live WordPress crawl test, surfaced
by a 7-dimension adversarial workflow:

- **F5: status race condition between `job.json` and `progress.json`.**
  When a subprocess exited non-zero mid-analysis, `job_runner._watch`
  wrote `meta.status = "failed"` to `job.json` but the last-known
  `progress.json` still carried the in-flight phase (e.g. `analyzing`).
  The job page reads both: badge shows "فشل" while the bar shows "جار
  التحليل…". Fix: after deciding final status, merge it into
  `progress.json` before writing `job.json`. Counters and phase fields
  are preserved (a failed job still shows how far it got).

- **F7: stop-button auto-show regression.** After clicking Stop, the
  results panel and download buttons stayed hidden until manual
  refresh. The v1.13.3 triple safety net only covered natural
  completion paths (`event: end`, FINISHED `data:`, polling) — Stop
  fired `POST /api/jobs/{id}/stop` and waited for SSE, which sometimes
  never came. Now: Stop awaits a 600 ms grace then pulls
  `/api/jobs/{id}/progress` and calls `_safeFinish(meta)` itself,
  matching the v1.13.3 pattern.

- **F6: failed-card tooltip accuracy.** Tooltip said "4xx/5xx أو فشل
  اتّصال", implying both. The code path actually counts only
  `_fetch_page` failures (timeout / DNS / connection reset / redirect
  loop / SSRF block / robots block / page-too-large) — 4xx/5xx are
  recorded as crawled-pages-with-status, not as failures. Tooltip
  rewritten to match: "صفحات فشل جلبها بعد كل محاولات الإعادة … 4xx/5xx
  لا تُحتسب هنا — تظهر كـ‹صفحات› مع كود الحالة."

Background investigations that did **not** need a fix:

- **N2** (Recent Jobs panel shows only 3): confirmed only 3 valid job
  folders exist under `webapp_jobs/`. Display limit is 15; nothing
  lost. User had deleted older jobs at some point.
- **N3** (`webapp_jobs/` tracking): confirmed gitignored since day one;
  zero tracked files. 359 MB on disk stays local.
- **N4** (card tooltips): all 6 cards have HTML5 `title=` working
  fine; the `data-tip-key` attributes are placeholders for a future
  bilingual styled tooltip system (not v1 launch scope).
- **N8** (live job `20260624_121003_2370cd`): no crash. The user
  clicked Stop manually after the crawl had collected 316 pages of
  the 500-page cap; analysis finished and exported partial results.
  The 6 "failed" pages were genuine fetch failures (the new F6
  tooltip will help readers understand that).

Version bumped to 1.13.11. 92/92 tests.

Also in this commit: `git filter-repo --replace-text` was run before
the first public push to surgically replace internal validation-site
references everywhere in history with neutral placeholders. Commit
graph, dates, authorship, and messages are preserved. All commit SHAs
changed (the natural consequence of any history rewrite). The
pre-rewrite `.git` is kept only as a local rollback backup and is
never pushed.

---

## v1.13.10 (2026-06-24 final pre-publication scrub)

A targeted publication-readiness pass run as a 6-dimension adversarial
audit workflow (sensitive-data sweep / git-history scan / docs
completeness / leftover code / repo hygiene / first-impression test +
adversarial verification on every dimension + a synthesis judge). The
audit cleared the project for publication after **one** hard blocker
and surfaced 4 high-ROI polish items:

- **Blocker fix — preset validation-site anonymization.** The v1.13.9
  CHANGELOG block named a specific WordPress preset-validation site in
  plaintext. Replaced with a neutral placeholder
  (`a healthcare WordPress site`), matching the same style used for
  the v1.13.8 generic-platform scrub.
- **`config.yaml` untracked (recommended OSS pattern).** Was committed
  with only example values, but having both `config.yaml` and
  `config.example.yaml` in the repo invited accidental commits of real
  user start URLs / domains. Now `config.yaml` is gitignored and
  `services/config_service.py::load_config` falls back to
  `config.example.yaml` if the default path is missing — fresh clones
  run with zero setup, and users only create their own `config.yaml`
  when they need overrides (which then stays out of git).
- **`pyproject.toml` added.** Enables `pip install git+<repo-url>`
  (no PyPI publish required) and sets up the project for future PyPI
  release with zero rework. Includes name, version, MIT license, full
  classifiers (Development Status :: 5 - Production/Stable, AR + EN
  natural languages, Python 3.10/3.11/3.12), URLs (Homepage, Docs,
  Changelog, Issues), and a `sct` console-script entry point.
  Dependencies are still managed in `requirements.txt` to keep parity
  with Docker/CI — duplicating them in pyproject would invite drift.
- **README badges (AR + EN).** Both READMEs gained a 4-badge row
  (CI status, Python 3.10+, MIT license, AR+EN docs link) — the
  audit's "first-impression test" agent rated this the single
  highest-ROI no-code fix.
- **`docs/OAUTH_SETUP.md` and `docs/GA4_PROPERTY_ID.md` are now English.**
  The Arabic content moved to `OAUTH_SETUP_AR.md` and
  `GA4_PROPERTY_ID_AR.md`, matching the rest of the project's
  EN-at-canonical / AR-at-`_AR` convention.

The audit's history scan over 41 commits found **zero** API keys, .env
leaks, or credentials. `` exists in commit `2c14c11` but was
already scrubbed in v1.13.8 — wiping history is **not** recommended:
it would cost 41 commits of attribution + the visible v1.13.x polish
narrative that signals active maintenance, and would gain nothing the
existing fix didn't already buy. The full verdict is in the workflow
output.

Version bumped to 1.13.10. 92/92 tests.

---

## v1.13.1 — v1.13.9 (2026-06-23 same-day polish + open-source readiness)

Nine patches consolidating user-reported UI bugs, auth-edge cases, the
first WordPress preset, and a final docs-and-CI sweep before v1.14.
Each landed on a green test suite. The full per-commit story is in the
git log; the consolidated behavior changes are:

- **v1.13.1 — `label_for` differentiates JSON files.** The "النتائج
  والتقارير" panel used to label every `.json` file as
  "الأرشيف الكامل (JSON)" regardless of content. Now: `metrics.json`,
  `integrations_<slug>_<ts>.json`, `audit_*.json`, `pagespeed_raw/*.json`
  (with Mobile/Desktop suffix), `comparison_summary.json`, and any
  `*deferred*.json` get distinct labels in both languages. Fallback for
  unknown JSONs is `<stem> (JSON)` instead of the generic "Full audit
  archive".

- **v1.13.2 — `withToken()` for non-fetch navigation.** Download buttons,
  `<a target=_blank>` view links, and the SSE EventSource all used
  plain `<a href>` / `window.location` / `EventSource(url)`, none of
  which trigger the `window.fetch` monkey-patch that injects the v1.10
  `Authorization: Bearer` header. So every download silently returned
  401 since v1.10. Fix: a tiny `withToken(url)` helper appends
  `?token=...` to every URL used as navigation. Eight call sites
  patched, plus the SSE URL. Backend was already prepared:
  `_extract_token()` (security.py) reads from either the Bearer header
  or the `?token=` query.

- **v1.13.3 — Triple safety net for auto-show.** The "report + downloads
  appear automatically when crawl finishes" behavior depended only on
  the SSE `event: end` handler. Three failure modes (`event: end`
  delayed by a backend race, mid-stream disconnect, total SSE failure)
  all left the results panel hidden until refresh. Now: three paths
  share a `_finishedOnce` guard so `finish(meta)` runs exactly once.
  Path 1 is still `event: end`. Path 2 is "incoming `data:` already
  carries a `FINISHED` status with `meta.result`". Path 3 is a 3-second
  polling fallback hitting `/api/jobs/{id}/progress`.

- **v1.13.4 — Docs language-parity catch-up.** `README_ar.md` had drifted
  behind `README.md` (still mentioned the old `SCT_NO_AUTO_INSTALL`,
  no `START.bat` launcher, no RUNBOOK link). Resynced. New
  `docs/RUNBOOK_AR.md` (460 LOC, all 8 scenarios) for parity with the
  English RUNBOOK.

- **v1.13.5 — WordPress platform preset.** Added the fifth preset to
  `config_presets.PRESETS`. Excludes 19 vanilla-WP traps (most
  importantly `?replytocom=` which can multiply queue size 10–50×,
  `/feed/` on every taxonomy/post, `/tag/`, `/author/`,
  `/wp-admin`, `/wp-json/`, `/xmlrpc.php`) and strips 7 query params
  (`replytocom`, `attachment_id`, `unapproved`, `moderation-hash`,
  `preview`, `preview_id`, `preview_nonce`). Detection signature added
  to `_SIGNATURES` after WooCommerce so a WP+Woo store still picks
  the more specific `woocommerce` preset. Form label updated from
  "قالب منصّة التجارة" to "قالب منصّة جاهز" since the field is no
  longer e-commerce-exclusive. Whitelist tuple in
  `webapp/job_runner.py` extended; comments in `config.yaml` and
  `config.example.yaml` updated. New test
  `test_wordpress_preset_present_and_excludes_traps` (4 assertions:
  preset present, critical patterns included, `apply_preset` merges
  without losing user patterns, `detect_platform` yields to Woo on
  overlap). 92/92 tests.

- **v1.13.6 — Polling updates counters live + card tooltips.** User
  reported that refreshing the job page mid-crawl returned all six
  live counters to 0. The v1.13.3 polling fallback only triggered
  `_safeFinish` at FINISHED — it never called `applyProgress` or
  `applyStatus` during running. Now: every poll updates the badge and
  the counters even while running, first poll fires immediately (no
  3-second delay), and the panel still shows only on real completion.
  Also added Arabic `title=` tooltips to all 6 cards (pages / queue /
  failed / ext_checked / speed / sec) explaining what each measures
  and how to read its value.

- **v1.13.7 — Defensive URL scheme normalization.** API calls that
  passed `example.com` without a scheme silently broke the crawl
  (empty `netloc` → empty `domain` → everything looked external).
  `job_runner` now auto-prepends `https://` if the value doesn't start
  with `http://` or `https://`. Browsers were already guarded by the
  HTML5 `type="url"` validator on the form. Internal-page URLs like
  `https://example.com/blog/post-1` work fine as start URLs but still
  crawl the full host (not just `/blog/`); subpath-scoped crawls
  need an `include` pattern.

- **v1.13.8 — OSS-readiness fixes.** Blocked an early CHANGELOG
  validation-site name leak (replaced with a neutral placeholder,
  "an e-commerce site"), rewrote SECURITY.md's reporting section around the
  GitHub Private Security Advisory channel + added a v1.10+ surfaces
  block + a one-paragraph threat model, extended ROADMAP's "Recently
  shipped" from v1.04 stop through v1.13, refreshed README/README_ar's
  platform-preset bullet for WordPress, added an "Operations & API
  auth" paragraph documenting Bearer/`?token=` + `/health` + `/readyz`
  + rate limits, and unified CONTRIBUTING/_AR stale paths (the v1.12
  refactor moved `run_analysis` / `run_export` / `run_integrations`
  from `main.py` to their `services/<name>_service.py` modules).

- **v1.13.9 — Docs continuation + CI consistency.**
    * USER_GUIDE.md + USER_GUIDE_AR.md: added Backlinks API row to the
      integrations table, replaced the platform-preset paragraph with
      the WordPress-aware version, added §13 "Link graph view" describing
      `/jobs/<id>/graph`, added §14 "The 6 live counters" with how to
      read each card, added §12's "Local auth token" subsection (token
      path + Bearer/?token= + exempt routes + rotation + rate limits).
    * CLI.md + CLI_AR.md: added `--phase2` row to the flag table and a
      matching scenario block (Phase 2 re-uses `deferred_urls.csv` and
      extends `audit.json`), added `SCT_AUTO_INSTALL` and
      `BACKLINKS_API_KEY` to the env-var table.
    * ARCHITECTURE.md + ARCHITECTURE_AR.md: rewrote the module map for
      v1.12's refactor (added `services/` with all 14 modules, added
      `webapp/security.py` + `deps.py` + `constants.py` + the 9
      `webapp/routers/`), added `ai_advisor.py` + `backlinks_api.py` +
      `lighthouse_importer.py` to the integrations list, added
      `url_classifier.py` to analyzers, refreshed the "Where to look
      for…" table to point to services/ and routers/ instead of the
      removed `main.py::run_integrations` and
      `webapp/app.py::/api/google/…` paths, refreshed §7 testing to
      reference `conftest.py` + `test_crawler.py` (the v1.13 split).
      Fixed the stale `_run_integrations_only` reference (the public
      function is `run_integrations_only`, no underscore).
    * RUNBOOK.md + RUNBOOK_AR.md: bumped self-identifying version from
      v1.11 to v1.13, fixed appendix `expect: 91/91` to `92/92`.
    * .github/workflows/ci.yml: resolved the pip-audit
      "blocks on high/critical" comment vs `continue-on-error: true`
      contradiction — clarified the job is **advisory only** and
      documented how to flip it to hard-fail (`--strict` + drop
      `continue-on-error`).
    * Validation on a WordPress site configuration confirmed the
      preset filters traps as designed and the UI flow works through
      to download/auto-show. 92/92 tests.

---

## v1.13 — 2026-06-20 (REFACTOR-tests-split content migration)

The final REFACTOR from the v1.11 audit. tests/test_core_behaviors.py
(1,414 LOC, 77 tests in 3 classes) is split into 6 categorized files
under tests/, with the v1.12.7 `conftest.py` providing shared fixtures
(sys.path bootstrap + FakeResponse + MinimalPage + _FakeAIResp).

### The 6 new test files

| File | Tests | LOC | Covers |
|---|---:|---:|---|
| `tests/test_crawler.py` | 17 | 308 | robots, db persistence, async_core, classifier, content/custom extractors, adaptive throttle, platform presets, Phase 2 seed injection |
| `tests/test_analyzers.py` | 23 | 379 | every analyzer module (canonical, url_issues, duplicate, redirect, schema, security, hreflang, pagination, link_score, near_duplicate, spell_check, hints, accessibility, gsc_insights, crawl_compare, log_analyzer, _coerce) |
| `tests/test_integrations.py` | 12 | 226 | gsc_api, ga4_api, pagespeed_api, crux_history, ai_advisor (incl. SSRF rejection), lighthouse_importer, backlinks_api |
| `tests/test_exporters.py` | 8 | 166 | csv_exporter, html_exporter, report_builder (incl. client/expert/both audiences), sitemap_generator, unified join, opportunities |
| `tests/test_priority.py` | 3 | 121 | reporting/priority_engine (classify, ease, scores, action board) + reporting/url_detail |
| `tests/test_utils.py` | 14 | 199 | utils/helpers, utils/monitoring, utils/auto_install, storage/cache, webapp/job_runner internals, webapp/app helpers (_probe_token_expired, _run_conn_test) |

### Mechanics

- `tools/split_tests.py` (new, 200 LOC) — one-shot migration tool that
  parses test_core_behaviors.py with `ast`, maps each of the 77 tests
  to a category, and emits the 6 target files with category-specific
  module-level imports (each file only imports what its tests use).
- Per-class context (CoreBehaviorTests, RegressionTests, V109BatchTests)
  is collapsed: each new file gets a single `TestX(unittest.TestCase)`
  class that holds all tests for the category. The legacy class
  membership wasn't load-bearing — there were no shared setUp methods
  across the 3 old classes.
- `tests/test_core_behaviors.py` deleted. Pre-v1.13 imports for
  `from tests.test_core_behaviors import ...` no longer work — any
  external code that did this (none in-tree) needs to update to
  `from tests.test_<category> import ...`.

### Test status

```
v1.13 → 91/91 OK (77 from the 6 split files + 14 webapp endpoint tests)
```

Identical pass count + behavior to v1.12.7. The split is pure
refactoring — no test logic changed.

### Repository structure post-v1.13

The full v1.11-audit-driven refactor is complete. Summary:

| Area | Before | After | Modules |
|---|---:|---:|---|
| `seo_crawler/main.py` | 2,339 LOC | 513 LOC (−78%) | 14 services modules |
| `webapp/app.py` | 2,098 LOC | 143 LOC (−93%) | 12 webapp modules |
| `tests/test_core_behaviors.py` | 1,414 LOC | (deleted) | 6 split files + conftest.py |

Total new modules across v1.12.0–v1.13: **32**. All behavior preserved
through re-exports + module-level fixtures. Every release shipped on
green tests.

---

## v1.12.1 — v1.12.7 (2026-06-20 same-day patches — full refactor completion)

The v1.12.0 release shipped the supply-chain + dependency fixes (DEP-1, DEP-6,
DEP-12 + DEP-2/3/5 bonus) + the first 8 of 14 services modules. The same-day
v1.12.1–v1.12.7 patches finish the structural refactor that was explicitly
deferred from v1.11, all gated on green 91/91 tests between batches.

### Final REFACTOR-services (v1.12.1 + v1.12.2)

`seo_crawler/main.py`: **2,339 → 513 LOC (−78%)** with 14 service modules:

| Module | Tier | LOC | Owns |
|---|---|---:|---|
| `progress_service` | 0 leaf | 57 | `emit_phase` |
| `deferred_service` | 0 leaf | 45 | `deferred_list`, `deferred_summary` |
| `integrations_summary` | 0 leaf | 48 | `gsc_summary`, `ga4_summary` |
| `export_helpers` | 1 leaf | 186 | 11 flatten helpers + `get_value` |
| `config_service` | 1 | 99 | `load_config`, `setup_output_dir`, `validate_config`, `slugify_label`, `configure_target_site` |
| `db_facade` | 1 | 75 | `DatabaseBackedCrawler` + `AttrDict` |
| `ai_service` | 1 | 54 | `run_ai_analysis` |
| `crawl_service` | 2 | 115 | `run_crawl_sync/async`, Phase 2 helpers |
| `analysis_service` | 2 | 285 | `run_analysis` (14 analyzer lazy imports) |
| `external_check_service` | 3 | 226 | `run_external_links_check`, `run_resource_status_check` |
| `integrations_service` | 3 | 243 | `run_integrations`, `MinimalCrawler` |
| `export_service` | 4 | 449 | `run_export` (the biggest single extraction) |
| `integrations_only_service` | 5 | 101 | `run_integrations_only` |
| `compare_service` | 5 | 202 | `run_compare_workflow`, `build_compare_summary`, `summarize_crawler_result` |

main.py re-exports every public name for backward compat — tests + external
callers (`from main import DatabaseBackedCrawler` etc.) keep working.

### Full REFACTOR-app-routers (v1.12.3 + v1.12.4 + v1.12.5 + v1.12.6)

`webapp/app.py`: **2,098 → 143 LOC (−93%)** with 12 webapp modules:

- **`webapp/constants.py` (144 LOC)** — pure data + i18n: EXTRACTION_GROUPS,
  OUTPUT_FORMATS, SECTIONS, SEVERITIES, UA_PRESETS, MAX_AUDIT_JSON_MB,
  CSV_LABELS + `label_for()`.
- **`webapp/security.py` (240 LOC)** — auth token + 4 middlewares + 2
  exception handlers + `register_middlewares(app)` / `register_exception_handlers(app)`.
  Preserves the v1.10 middleware execution order
  (CSRF → rate → correlation → auth → handler, last-registered = first-executed).
- **`webapp/deps.py` (87 LOC)** — singletons (`runner`, `templates`,
  `FINISHED_STATUSES`) + path helpers (`_safe_under_jobs`, `_job_output_dir`,
  `_safe_output_file`) + Google helper (`_google_dir`) + `_run_conn_test`.
  Single source of truth — no duplicate helper definitions across routers.

The 9 APIRouter modules under `webapp/routers/`:

| Router | LOC | Endpoints |
|---|---:|---|
| `pages.py` | 87 | 7 HTMLResponse routes (/, /jobs/{id}, /jobs/{id}/{explore,board,compare,graph}, /logs) |
| `jobs.py` | 315 | Job lifecycle: /api/start (heaviest, ~170 LOC of form parsing), progress, events (SSE), phase2, deferred, stop, kill, delete, delete-all |
| `downloads.py` | 214 | report rebuild + file delivery + ZIP packaging (with `only=` filter) |
| `generate.py` | 191 | background HTML/PDF/Excel/XML build + status. Owns `_gen_state`/`_gen_lock` |
| `google_oauth.py` | 318 | full OAuth flow (8 endpoints). Owns `_paste_flow` state + `_probe_token_expired` + `_save_google_tokens` |
| `connections.py` | 98 | /api/test/{gsc,ga4,pagespeed} |
| `setup.py` | 214 | /api/setup/{tool}, /api/requirements, /docs/{name} + markdown→HTML |
| `analytics.py` | 310 | read-only audit-JSON endpoints (/api/jobs/{id}/{pages,compare,url-detail,graph,priority}) + _build_graph_payload |
| `logs.py` | 103 | /api/logs/analyze + /api/jobs/{id}/log-board |

app.py final shape: FastAPI instantiation → static mount → deps/security/
constants imports → `register_middlewares(app)` + `register_exception_handlers(app)`
→ 9 `app.include_router(...)` → `/health` + `/readyz` → backward-compat
re-exports of `_extract_oauth_code`, `_probe_token_expired` for test imports.

### REFACTOR-tests-split infrastructure (v1.12.7)

`tests/conftest.py` extracted from `test_core_behaviors.py`:
- sys.path bootstrap (so any test file can `from analyzers.X import Y`)
- Shared fixtures: `FakeResponse`, `MinimalPage`, `_FakeAIResp`.

`test_core_behaviors.py` now imports fixtures from conftest, removing
duplicated definitions. The actual category-split of the 77 tests across
6 files (test_crawler/analyzers/integrations/exporters/priority/utils) is
deferred to v1.13 — needs a focused session to categorize each test and
migrate while preserving setUp/tearDown state, helper closures, and the
local HTTP fixture server. v1.12.7 ships the prerequisite plumbing.

### Test status across all v1.12 patches

```
v1.12.0 → 91/91 OK
v1.12.1 → 91/91 OK
v1.12.2 → 91/91 OK
v1.12.3 → 91/91 OK
v1.12.4 → 91/91 OK
v1.12.5 → 91/91 OK
v1.12.6 → 91/91 OK
v1.12.7 → 91/91 OK
```

Every patch landed on green tests before the next started.

### Final v1.12 totals

- **main.py: 2,339 → 513 LOC (−78%)** + 14 services modules (2,200 LOC)
- **webapp/app.py: 2,098 → 143 LOC (−93%)** + 12 webapp modules (2,500 LOC)
- **tests/conftest.py** seeded for v1.13 category-split
- **Zero behavior changes** — all public APIs preserved through re-exports
- **All 91 tests green** at every checkpoint

---

## v1.12 — 2026-06-20 (high-severity deps + supply-chain hardening + services/ leaves)

### Scope

v1.11 audit's 6 must-do findings split into three categories: **3 dependency/
supply-chain** fixes (DEP-1, DEP-6, DEP-12, plus DEP-2/3/5 bonus) and the
**3 structural refactors** (services/ extraction, app.py routers, tests split).
v1.12 ships ALL the must-do dep fixes plus the first ~22% of the services
extraction (8 leaf modules under `seo_crawler/services/`). The remaining
refactors continue in v1.12.x with the same green-test-gate discipline.

All 91 tests still pass.

### High-severity dependency + supply-chain fixes

**DEP-1 — Playwright base image bump** (`Dockerfile`). From
`v1.47.0-jammy` (October 2024, 21 months stale at v1.12 release) to
`v1.55.0-noble`. Picks up ~21 months of Chromium V8/Blink security patches,
moves the OS layer to Ubuntu Noble (24.04 LTS, jammy nears EoL). The
multi-stage `dist-packages` copy path updated from `python3.10` to
`python3.12` to match the new base.

**DEP-2 — playwright Python pin updated** to match new base
(`playwright>=1.55.0,<2.0`).

**DEP-3 — aiohttp bumped** from `3.10.11` (EoL branch) to `>=3.12.13,<4.0`.
Picks up the 2024-2025 CVE fixes.

**DEP-5 — jinja2 bumped** from `3.1.4` to `>=3.1.6,<4.0` to pick up the
sandbox-escape CVE-2025-27516 fix.

**DEP-6 — python-multipart bumped** from `0.0.12` to `>=0.0.18,<1.0` to
address CVE-2024-53981, an unauthenticated CPU-DoS via malformed multipart
boundary on FastAPI form endpoints.

**DEP-12 — `utils/auto_install.py` flipped to opt-in.** Previously enabled
by default (could be disabled with `SCT_NO_AUTO_INSTALL=1`). The audit
flagged it as a supply-chain risk: it installed unpinned latest versions
from PyPI for an allowlist that included lxml/aiohttp/requests/PyYAML,
silently defeating `requirements.txt` pinning and creating dev/prod skew
(writes fail under Docker `USER sct`). v1.12 inverts the default: auto-
install is **disabled** unless `SCT_AUTO_INSTALL=1` is set. Missing
optional extras now log a clear actionable error naming the package and
the exact `pip install …` command instead of silently fetching it. The
`SCT_NO_AUTO_INSTALL` variable is still recognized but is now a no-op
(disabled is the default). README updated.

### REFACTOR-services — first 8 modules under `seo_crawler/services/`

`seo_crawler/main.py` shrinks from **2,339 LOC** to **1,834 LOC** (−22%).
The v1.11 scouting workflow's recommended Tier-0/Tier-1 leaves are now
in place; main.py re-exports every public name for backward-compatibility
so `tests/test_core_behaviors.py:454` and any external code that imports
`DatabaseBackedCrawler`/`emit_phase`/`load_config`/etc. from `main` keeps
working without modification.

| Module | Tier | LOC | Contents |
|---|---|---:|---|
| `services/progress_service.py` | 0 leaf | 57 | `emit_phase` (used by 7+ sites) |
| `services/deferred_service.py` | 0 leaf | 45 | `deferred_list`, `deferred_summary` (Phase 2 UI) |
| `services/integrations_summary.py` | 0 leaf | 48 | `gsc_summary`, `ga4_summary` |
| `services/export_helpers.py` | 1 leaf | 186 | 11 pure flatten helpers for run_export + integrations_only |
| `services/config_service.py` | 1 | 99 | `load_config`, `setup_output_dir`, `validate_config`, `slugify_label`, `configure_target_site` |
| `services/db_facade.py` | 1 | 75 | `DatabaseBackedCrawler` + `AttrDict` (read-only DB facade) |
| `services/ai_service.py` | 1 | 54 | `run_ai_analysis` (Phase 3.5, optional AI advisor) |
| `services/crawl_service.py` | 2 mid | 115 | `run_crawl_sync`, `run_crawl_async`, `inject_phase2_seeds`, `find_phase2_deferred_csv` |

`services/__init__.py` documents the Tier hierarchy. Each module gets its
own `log = get_logger(__name__)` so log records show service-of-origin
(per the v1.11 scout's risk-rated guidance). `from __future__ import
annotations` is preserved on every file so `TYPE_CHECKING`-only types
keep resolving.

### Continuing in v1.12.x

These mid-tier and orchestrator extractions remain mapped + risk-rated in
the v1.11 scouting workflow output but are scheduled across follow-up
v1.12.x patches with a green-test-gate between each. Doing them all in
one PR would have produced a ~1,600-LOC diff with no checkpoint, which
the scout explicitly warned against:

- `services/analysis_service.py` (run_analysis, ~260 LOC)
- `services/external_check_service.py` (run_external_links_check +
  run_resource_status_check, ~210 LOC)
- `services/integrations_service.py` (run_integrations + _MinimalCrawler,
  ~230 LOC)
- `services/export_service.py` (run_export, ~410 LOC — highest-risk, last)
- `services/integrations_only_service.py` (~74 LOC)
- `services/compare_service.py` (~155 LOC)
- `seo_crawler/cli.py` (main + main_async)
- REFACTOR-app-routers (webapp/app.py → 9 APIRouters, separate PR series)
- REFACTOR-tests-split (test_core_behaviors.py → 6 files + conftest.py)

### Test status

```
Ran 91 tests in 5.4s
OK
```

No test changes in v1.12 base — all changes are behavior-preserving.
Tests use `from main import DatabaseBackedCrawler` which still works via
the re-export.

---

## v1.11 — 2026-06-20 (debuggability, hot-path imports, operator docs)

### Scope

Follow-up to v1.10's 58-prompt audit, scoped to the remaining Medium/Low
findings that don't require structural refactoring. A multi-agent scouting
workflow mapped 25 high-value `log.error → log.exception` conversions,
13+ hot-loop inline imports in `crawler/core.py`, and operator-doc gaps.
Larger refactors (services/ split, webapp router split, test-file split)
were deferred to v1.12 because the workflow flagged them as "ship in a
clean tree after v1.11 lands". Test suite still **91/91 passing**.

### Debuggability — log.exception across 9 files (M-10 follow-up)

17 sites converted from `log.error(f"...: {e}")` (or silent `log.warning`)
to `log.exception(...)` / `log.warning(..., exc_info=True)`. Every site
was chosen because a traceback materially helps triage:

- `utils/state_manager.py` — save / load / load_meta now emit a stack on
  failure. Lost resume-state is one of the worst debugging hot-spots.
- `crawler/robots_parser.py` — robots fetch/parse failure now logs the
  underlying SSL/HTTP/parser exception.
- `crawler/js_renderer.py` — sync + async Playwright start failures and
  per-page render failures now carry a stack.
- `crawler/http_client.py` — the catch-all after specific
  `Timeout/ConnectionError/RequestException` branches now logs the stack
  for genuinely "unexpected" errors.
- `crawler/async_core.py` — DB snapshot save was demoted to `log.debug`
  with no trace; promoted to `log.warning(exc_info=True)`.
- `integrations/ga4_api.py` — GA4 authenticate() failure now logs a stack.
- `integrations/pagespeed_api.py` — final "other" exception bucket logs
  a stack instead of `log.debug` with truncated string.
- `checkers/external_links_checker.py` — catch-all that previously bumped
  a metric without any log line now also writes a warning + stack.
- `seo_crawler/main.py` — sitemap generation, GSC insights, unified
  report build, GSC page+query fetch all log stacks.
- `webapp/app.py` — module-level `log = logging.getLogger("sct.webapp")`
  added; 10 endpoint handlers now log a stack before returning their
  500 (Google OAuth flow, OAuth code exchange, GSC sites list, GSC test,
  GA4 test, tool setup subprocess, report regeneration, log analyzer,
  log+audit join, audit compare). The truncated `str(e)[:300]` returned
  to the client stays the same — the stack lands in the server log keyed
  by `request_id`.

### Performance hygiene — hot-loop inline imports hoisted (M-9)

`seo_crawler/crawler/core.py` previously re-executed 13 `from extractors.X
import Y` statements inside `_extract_page_data()`, once per crawled page.
None of them had a cycle risk with `crawler/`. v1.11 hoists them to the
module top alongside the existing `crawler.*` and `utils.helpers` imports:

- `extract_meta`, `extract_headings`, `extract_canonical`, `extract_hreflang`,
  `extract_pagination`, `extract_og_twitter`, `extract_schema`,
  `extract_content`, `extract_images`, `extract_links`, `extract_headers`,
  `detect_mixed_content`, `extract_custom`, `extract_resources`.
- `compile_rules` (was inside `Crawler.__init__`) hoisted too.
- `format_bytes` / `format_duration` (was inside a stats-print) hoisted.

This removes ~14 redundant import-cache lookups per page. On a 10,000-page
crawl that's 140,000 lookups eliminated. Not a giant win individually, but
a clear stylistic improvement and the workflow explicitly recommended it.

### Operator docs — `docs/RUNBOOK.md` (L-5)

New 8-scenario incident runbook for SCT operators. Each scenario uses a
**Symptoms → Diagnosis → Fix** structure with concrete shell and
PowerShell commands, plus verbatim expected log lines. Covers: Google
OAuth `invalid_grant` (the 7-day Testing-mode expiry), missing/wrong
`~/.sct/local_token`, `/readyz` 503 (filesystem write-probe failing),
port 8000 already in use, Phase 2 button failures (4 distinct causes),
residual `database is locked` cases after v1.10's busy_timeout, disk-full
cleanup via `/api/jobs/delete-all`, and CSP/security-headers scanner
complaints (with the explicit "SCT is single-user local, not a hardened
public web app" framing). Linked from README.md.

### USER_GUIDE updates — deferred-URL panel (L-4)

Both `docs/USER_GUIDE.md` (English) and `docs/USER_GUIDE_AR.md` (Arabic)
get a new section documenting the v1.08 two-phase crawl: why it exists
(the 14,553 `/auth/login?redirect_to=...` case in plain language, no
client name needed), what the amber panel shows (kinds + counters +
samples + Phase 2 button + CSV download), when to run Phase 2 vs skip
it (decision table), where `deferred_urls.csv` lands, the configurable
`pagination_max` / `filter_max` thresholds, and the sync-crawler caveat.

### Dockerfile — multi-stage (M-12)

`Dockerfile` is now multi-stage. Stage 1 (builder) installs requirements
+ ensures Chromium. Stage 2 (runtime) uses the **same** Playwright base
image — slimming the runtime to `python:slim` would force re-downloading
Chromium and re-installing libnss/libatk/fonts, rarely worth it and
fragile across Playwright versions. The split isolates the pip cache and
any future build dependencies (gcc, headers for source wheels) from the
final image. v1.09's non-root `sct` user, v1.10's HEALTHCHECK against
`/health`, and the original `CMD` are all preserved. Header comment
documents the design choice.

### Lockfile generation — `tools/freeze_lock.bat` (L-3)

System `pip freeze` captures every host-installed package, not just
SCT's dependencies. The new helper creates a temporary clean venv,
installs only `requirements.txt`, and freezes the resulting closed set
into `requirements.lock.txt` — a true reproducible lockfile. Documented
inline.

### Deferred to v1.12

Per the multi-agent scouting workflow's explicit recommendation:

- **`seo_crawler/main.py` → `services/` split** (2,300 LOC, 13 modules
  proposed): orchestrator extractions (compare, integrations-only,
  cli.py) require multi-batch verification and are best done against
  a clean tree.
- **`webapp/app.py` → 9 router split** (2,085 LOC): middleware ordering
  + SSE smoke test + exception-handler conversion are subtle; deserves
  its own release.
- **`tests/test_core_behaviors.py` → 6 file split** (1,414 LOC): needs
  a shared `conftest.py` for fixtures first.

These extractions are mapped, risk-rated, and ordered in the v1.11
scouting workflow output — ready for v1.12 to apply.

### Test status

```
Ran 91 tests in 7.4s
OK
```

No test changes in v1.11 — all changes are behavior-preserving.

---

## v1.10 — 2026-06-20 (58-prompt deep audit response)

### Scope

A 58-prompt structured audit (`D:\audit_prompts\01-58`) applied verbatim to
the SCT codebase. Each prompt was treated as binding. Findings spanned
architecture, code quality, backend API, services, data access, security,
performance, tests, dependencies, observability, config, SQLite (all 6
prompts), backend lifecycle (9 prompts), and cross-cutting concerns (12
prompts). PostgreSQL and Next.js prompts skipped — not applicable.

Outcome: **3 Critical + 8 High + 12 Medium + 5 Low = 28 new findings**
on top of the ~40 already resolved in v1.09. v1.10 closes all 3 Critical,
6/8 High, and 6/12 Medium. Test suite expanded **77 → 91 passing** (+14
new TestClient-based webapp tests).

### Critical fixes

**A1 — local auth token on every endpoint** (Prompts 7, 39, 40, 51).
Before v1.10 any process with network access to `127.0.0.1:8000` (Docker
bridge, LAN host, VPN, another app on the same machine) could delete jobs,
start crawls, upload OAuth secrets, and read all client data. v1.09 added
a CSRF Origin guard but that only blocks browser-cross-origin attacks.
v1.10 generates a per-install token at startup into `~/.sct/local_token`
(mode 0600), enforces it on every POST/PUT/DELETE and on every `/api/*`
endpoint via middleware, injects it into all 7 Jinja2 templates and
monkey-patches `window.fetch` to set `Authorization: Bearer <token>`
automatically. `GET /` and `GET /health`/`GET /readyz` remain exempt
(required for bootstrap + orchestrators). Constant-time comparison via
`hmac.compare_digest` prevents timing attacks. The fetch-patch is in every
template's `<head>` before `i18n.js` loads.

**A2 — SQL injection lockdown via table whitelist** (Prompt 16).
Four f-string interpolation sites in `storage/database.py` (lines 405,
408, 1025, 1064 in the v1.09 codebase) used `f"PRAGMA table_info({table})"`,
`f"ALTER TABLE {table} ADD COLUMN {column} {definition}"`, and
`f"SELECT COUNT(*) FROM {table}"`. Names were compile-time constants but
the pattern was dangerous — any future contributor copying it with a user
input would create an injection. v1.10 introduces `_ALLOWED_TABLES`
frozenset, `_safe_table()` guard, and `_IDENT_RE` / `_DEFN_RE` regex
gates. Every interpolation now passes through them. The `get_stats()`
loop also passes through `_safe_table()` even though its list is
hardcoded — defense in depth.

**A3 — global FastAPI exception handler** (Prompt 42). Roughly 30
sites used the `return JSONResponse({"error": str(e)[:300]}, 500)`
pattern, leaking internal exception messages (file paths, table names,
sometimes frame state via `repr`). v1.10 adds `@app.exception_handler(Exception)`
that logs the full traceback with the request_id and returns a generic
`{"error": "internal_error", "request_id": rid}` payload. A separate
`StarletteHTTPException` handler preserves the explicit `status_code` and
`detail` from intentional `HTTPException` raises but adds the request_id.

### High-severity fixes

**B1.a — `slowapi`-style rate limiting** (Prompt 4/39). 10 starts/hour
on `/api/start`, 120 requests/min on all other `/api/*`. In-memory
token-bucket per (IP, scope) — no new dependency. `/health`, `/readyz`,
and `/static/` are exempt. Returns `429 {"error": "rate_limited", ...}`.

**B1.b — correlation IDs** (Prompt 11). Every request gets a 12-char
UUID via middleware. Available as `request.state.request_id`. Returned
as `X-Request-ID` header. Used by the v1.10 exception handler.

**B1.c — `/health` + `/readyz`** (Prompt 11). `/health` always returns
`{"status": "ok"}` for liveness. `/readyz` probes a write to `webapp_jobs/`
to confirm the app can actually serve work — returns 503 on filesystem
error.

**B2 — 14 webapp TestClient endpoint tests** (Prompt 9). New
`tests/test_webapp_endpoints.py` covers: health/readyz without auth,
401 on missing/bad token, 200 on Bearer + query token, CSRF cross-origin
rejected, CSRF localhost passes, X-Request-ID present, invalid job_id
rejected on xml download, unknown job 404 handling, phase2 on missing
job, generate with bad format, log-board on missing job. All **91/91**
pass in 6.2s.

**B3.a — `requirements-dev.txt`** (Prompt 10). Split dev-only deps:
`pip-audit` for CVE feeds + `httpx` for the FastAPI TestClient.

**B3.b — `pip-audit` step in CI** (Prompt 10/56). `security-audit` job
runs after Linux tests. Uses `--strict` flag on `requirements.txt` from
the PyPI Advisory DB. `continue-on-error: true` so transient feed issues
don't break the pipeline — failures show as annotations in the run
summary.

**B3.c — Windows CI runner** (Prompt 47). New `test-windows` job on
`windows-latest` with Python 3.11. Catches Windows-specific regressions
(path separators, `CREATE_NEW_PROCESS_GROUP`, file locks on cache DBs)
that the existing 3-version Linux matrix can never see.

### Medium fixes

**C1.M-2 — `Form()` validation** is rolled into the existing handlers;
many already had practical limits via in-function checks. Not changed
broadly to avoid breaking compatible API behavior.

**C1.M-3 — UploadFile MIME validation** on `/api/google/upload`.
Accepts only `application/json`, `text/plain`, `text/json`,
`application/octet-stream`, or empty. Rejects everything else with 400.
Other upload endpoints (`/api/logs/analyze`, `/api/jobs/<id>/log-board`)
take log files — text input, validated via decode rather than MIME.

**C1.M-4 — SQLite `PRAGMA busy_timeout = 5000`** on every connection.
This is on top of the existing `sqlite3.connect(timeout=30.0, ...)`
arg, which only applies at `BEGIN` time. The PRAGMA applies inside
every nested write — drastically reduces `database is locked` errors
when multiple worker threads hit the same DB.

**C1.M-8 — `validate_config()` at startup** in `main.py`. Checks
`site.start_url` scheme, `crawl.max_pages` >= 0, `concurrent_requests`
1..100, `delay_seconds` >= 0, `seed_strategy` in
`{homepage, sitemap, hybrid}`, `deferred_crawl.pagination_max` >= 0.
Warnings print to `stderr` before logging boots so misconfiguration is
visible immediately.

**C1.M-11 — `HEALTHCHECK`** in Dockerfile (30s interval, 5s timeout,
3 retries) hitting `/health`. Orchestrators now know whether the
container is actually serving, not just running.

### Low fixes

**D1.L-1 — `healthcheck:` block** in `docker-compose.yml` so
`docker compose ps` shows `healthy` state.

**D1.L-2 — `.env.example`** template documenting `PAGESPEED_API_KEY`,
`BACKLINKS_API_KEY`, `AI_API_KEY`, and `SCT_NO_AUTO_INSTALL`. None of
these are commit-able; the template is.

### Verified

```
91/91 tests pass (6.2s, +14 new TestClient tests)
compileall clean
node --check on inline JS clean
SSRF helper + auth token + CSRF + rate limit all confirmed via TestClient
```

### Findings deferred to a future release

- M-1 (folder nesting `seo_crawler/seo_crawler/`) — disruptive refactor.
- M-6 (`/api/v1/` versioning) — would break frontend without coordinated
  rewrite; deferred until OpenAPI work begins.
- M-7 (custom OpenAPI schemas) — pairs with M-6.
- H-4/H-5 (split `main.py`/`app.py`/`test_core_behaviors.py`) — large
  scope; planned for v1.11.
- L-3 (lockfile), L-4 (USER_GUIDE deferred panel docs), L-5 (incident
  runbook) — documentation backlog for v1.11.

### Remaining ROADMAP item

- **Single-file Windows `.exe` (PyInstaller)** — needs a Windows CI build host.

## v1.09 — 2026-06-19 (large audit batch)

### Scope

A parallel 4-agent adversarial audit of v1.03→v1.08.1 surfaced ~40 findings
across crawler, webapp, analyzers, exporters, integrations, storage, tests,
and docs. This release fixes every Critical + High finding and most of the
Mediums in twelve focused batches (B1–B12). Test suite expanded
70 → 77 passing.

### Critical fixes

- **B1 — Phase 2 was broken by default.** `_inject_phase2_seeds` looked for
  `output/csv/deferred_urls.csv` in the *current* job's output dir, but with
  the default `timestamped_folder=true` Phase 2 always runs from a fresh
  output dir → CSV never found → Phase 2 silently a no-op. Now searches the
  newest sibling output dir containing the CSV. Also validates each loaded
  URL through `is_safe_remote_url` to close the user-edited-CSV SSRF window.
- **B1 — `_restore_state` routed resumed URLs through the classifier.** URLs
  the crawler had previously committed to fetching were re-classified on
  resume → many landed in `self.deferred` instead of the queue, silently
  stranding work. Likewise for `start_url` and `sitemap_seeds`. v1.09 adds a
  `bypass_classifier=True` parameter to `_enqueue` and uses it at all three
  call sites. Also emits a single warning + `crawler.deferred.cap_dropped`
  metric when the `max_tracked` cap is hit (was silent drop).
- **B2 — Status-code coercion crashed analyzers on DB-backed rows.**
  `sitemap_diff`, `hreflang_validator`, `thin_content`, `duplicate_detector`,
  `broken_links`, `canonical_analyzer`, `security_analyzer`, `url_issues`,
  `redirect_analyzer` all assumed `int`. With `"301 Moved"` or `None` from a
  resumed DB row they either crashed the whole report (TypeError on
  comparison) or silently zeroed results (`!= 200` on string). New shared
  helper `analyzers/_coerce.status_of()` handles all variants. `seo_issues.py`
  also got a safe `d.get("urls") or []` on duplicate-rows dict access.
- **B3 — Stored XSS in `graph.html` → CSRF pivot.** `_renderTree` used
  `innerHTML` with `node.name`/`node.url` straight from crawled paths.
  A malicious target site containing `/<img src=x onerror=fetch('/api/...')>`
  in a URL path would execute JS in the auditor's browser, enabling CSRF
  against `/api/jobs/delete-all`, `/api/start`, etc. v1.09 builds the tree
  via `textContent` and validates URL schemes (http/https only).
- **B3 — CSRF Origin guard.** New FastAPI middleware rejects POST/PUT/DELETE
  requests whose `Origin` is set and not `127.0.0.1`/`localhost`/`::1`. CLI
  callers (no Origin header) are unaffected.

### High-severity security fixes

- **B4 — subprocess argv injection.** `mode` is whitelisted to
  `{audit, competitor, compare}` before reaching `main.py`. `url` is
  validated as `http(s)://` and rejected if it starts with `--`. Uses
  `--url=value` (single argv element) to prevent flag injection.
- **B4 — `_valid_job_id` guard added** at the top of `download(kind=xml)`
  where `job_id` interpolates into a tempfile prefix before any other check.
- **B4 — `MAX_AUDIT_JSON_MB` guard added** to `/api/jobs/<id>/log-board`
  (was the only audit-JSON-reading endpoint missing it).
- **B4 — `lighthouse_importer` size cap (100MB).** Was an unbounded
  `json.load` on user files → DoS vector.
- **B5 — `is_safe_remote_url` SSRF hardening.** Now (a) rejects IPv4-mapped
  IPv6 (`::ffff:127.0.0.1`) via a new `_is_unsafe_ip` helper, (b) fails
  *closed* on DNS resolution errors (was failing *open*, allowing NXDOMAIN
  → SSRF window), (c) checks IP literals directly before DNS lookup.
- **B5 — JS renderer SSRF check.** Both sync + async `render(url)` now
  consult `is_safe_remote_url` before `page.goto`.
- **B5 — `http_client.head()` follows redirects manually**, validating each
  hop via `is_safe_remote_url`. Previously `allow_redirects=True` could
  follow a 3xx Location into `169.254.169.254/latest/...`.
- **B6 — CrUX key moved from URL query to `X-goog-api-key` header.**
- **B6 — Majestic key (forced by their API to be a query param) documented
  with a code comment forbidding any `r.url` logging.**
- **B6 — Google token writes now atomic** (temp + `os.replace`) — Ctrl-C
  mid-write no longer truncates the token file. New `_atomic_write_text`
  helper in `app.py`; `integrations/google_auth.py:131` switched to same
  pattern.
- **B6 — AI advisor PII strip.** `build_audit_summary_for_ai` strips the
  query string from `top_opportunities[].url` before sending to the LLM,
  removing `?session=`, `?email=`, `?utm_*`, etc.

### Cleanup batch

- **B7 — `config.example.yaml` drift fixed.** Added missing
  `crawl.deferred_crawl.*` and `integrations.backlinks.*` blocks.
- **B7 — `storage/cache.py` API identity in cache key.** SHA256-fingerprinted
  `api_key` (or `app_api_key`) is mixed into `_make_key` so shared cache DBs
  cannot leak one user's response to another user.
- **B7 — `storage/cache.py` `max_size_mb` actually enforced.** New
  `_enforce_size_cap` deletes expired entries first, then drops the oldest
  10% if still over the cap. Runs every 200 `set()` calls.
- **B7 — `utils/logger.py` file handler bug.** A second `get_logger(name)`
  call with `file_output=True` now adds a `FileHandler` if one isn't already
  attached. Previously the cached-logger short-circuit silently returned
  console-only.
- **B7 — `utils/state_manager.py` atomic JSON writes.** `_atomic_json_write`
  helper: temp + fsync + `os.replace`. Ctrl-C during snapshot no longer
  corrupts the visited/queue/meta files.
- **B8 — `url_classifier` operator precedence bug.** `or`/`and` in the
  filter-combo check were parenthesized wrongly, counting empty params
  (`?filter_brand=` with no value) as filters. Explicit parens.
- **B8 — Sync crawler warns** when `deferred_crawl.enabled` is set but the
  sync path doesn't honor it (deferred classification is async-only).

### Remaining mediums (B9)

- **`log_analyzer`** — `last_seen` comparison parsed via
  `datetime.strptime(..., "%d/%b/%Y:%H:%M:%S")` instead of lexicographic on
  CLF strings (which was wrong across year/month boundaries).
- **`accessibility.py`** — CDN fetch wrapped in `with requests.get(...)`
  context manager so the streaming response always closes (previously
  leaked on success path).
- **`crawl_compare.py`** — `utf-8-sig` decoding tolerates BOM-prefixed
  audit JSON files.
- **`awt_importer.py`** — `pd.read_csv(..., nrows=1_000_000)` cap to
  prevent OOM on malicious large CSV.
- **`backlinks_api.py`** — three silent `log.debug` failures upgraded to
  `log.warning` (Ahrefs refdomains, Ahrefs anchors, Majestic topbacklinks).
- **`start_phase2` lock window** — placeholder `_procs[job_id] = None`
  inserted under the lock prevents two parallel requests from both passing
  the "no active job" check.

### New tests (B10)

Seven new tests added (`V109BatchTests`):
- `test_url_classifier_branches` — all 6 kinds via classifier.
- `test_backlinks_provider_unknown_returns_none` — factory error path.
- `test_probe_token_expired_corrupt_file` — corrupt token treated as expired.
- `test_cache_key_differs_per_api_identity` — B7 cache identity mixing.
- `test_inject_phase2_seeds_skips_missing_csv` — graceful no-CSV handling.
- `test_ssrf_blocks_ipv4_mapped_ipv6` — B5 SSRF bypass closed.
- `test_status_of_handles_strings_and_none` — B2 coercion helper.

### Docs + infra (B11)

- **`SECURITY.md`** — new "v1.04+ surfaces" section documenting backlinks
  egress, Google token rewrite, Phase 2 deferred CSV seed, CSRF origin check,
  subprocess argv hardening, SSRF fixes, PII strip.
- **`Dockerfile`** — non-root user `sct` with explicit ownership of
  `/app/webapp_jobs`. Reduces blast radius of any container escape.
- **`config.example.yaml`** — v1.08 `deferred_crawl` and v1.04 `backlinks`
  blocks documented (see B7).

### Verified

```
77/77 tests pass (5.5s)
compileall clean
node --check on inline JS clean
Jinja render of index.html + job.html + graph.html clean
SSRF helper now correctly rejects IPv4-mapped IPv6 and fails closed on NXDOMAIN
```

### Deferred (only remaining ROADMAP item)

- **Single-file Windows `.exe` (PyInstaller)** — needs a Windows CI build host.

## v1.08.1 — 2026-06-19 (hotfix)

### Fixed — critical NameError in `_discover_new_links`

A real-world crawl on an e-commerce site raised
`NameError: name 'url' is not defined` **6,500 times**. Every product
page fetched, every product page failed at link-discovery, every product
page logged a traceback. 3,246 pages were saved (sitemap-seeded), but **zero
new URLs were discovered from page content** — the bug fired on the first
iteration of every `for a_tag in soup.find_all("a", href=True)` loop.

**Root cause:** v1.08 M2 added `source_url=url` to the `_enqueue` call in
`async_core._discover_new_links`, but the method signature is
`_discover_new_links(self, page, soup, depth)` — the URL parameter is named
`page` (a `PageData` object), not `url`. The fix is one character: read
`page.url` instead.

**Why our v1.08 verification missed it:**
- `compileall` doesn't catch undefined-at-runtime names (the line is
  syntactically valid Python).
- `unittest` covers 69 component-level tests; none of them actually drove
  `AsyncCrawler._discover_new_links` against an HTML soup with anchor tags.
- The classifier sanity tests exercised classification only, not the
  enqueue path.

**Added a regression smoke test** (`test_discover_new_links_smoke_smoke`)
that instantiates a real `AsyncCrawler` with minimal config, runs
`_discover_new_links` against a 4-link HTML soup, and asserts (a) no
exception, (b) primary URLs enter the queue, (c) deferred URLs enter
`crawler.deferred`. Verified the test correctly fails when the bug is
present — temporarily reverting the fix triggered the same `NameError`,
confirming the test guards against this exact class of regression.

### Verified

```
70/70 tests pass (4.2s, includes new smoke test)
compileall clean
node --check on inline JS clean
```

### Practical recommendation

The failed 5h crawl produced no audit JSON (return code 1, output dir
empty). Delete it from the recent-jobs panel and start a fresh crawl.

## v1.08 — 2026-06-18

### Added — Two-phase crawl with deferred-URL panel

The biggest UX shift since v1.04. Instead of asking the user upfront how
many pages to crawl (a guess they can't make without seeing the site), the
crawler now **classifies URLs as it discovers them** and quietly defers
known-wasteful patterns. After Phase 1 finishes, a panel surfaces what was
deferred — grouped by reason — and the user decides whether to spend the
extra time on Phase 2.

#### What gets deferred (and why)

| Kind | Trigger | Why we defer |
|---|---|---|
| `pagination_deep` | `?page=N` (or `p=`, `pg=`) where N > **3** | Same template, similar SEO target; first 3 pages catch any pattern issue |
| `redirect_wrapper` | `/auth/login?redirect_to=…`, `/login?next=…`, etc. | Cloudflare/WAF typically returns 403 to bots — wastes budget |
| `filter_combination` | More than 1 `?filter[]=` / `category=` / `brand=` etc. | Cartesian explosion, same products different facets |

URLs in **sitemap** + the **start URL** are always primary (never deferred).
Everything else (`other`) is primary by default.

#### What you see after Phase 1

A new amber panel between status and downloads:
> 🔍 **Discovered URLs not crawled in Phase 1**
> The primary URLs have been crawled. The URLs below were deferred…
>
> [📄 Deep pagination] [🚪 Auth wrappers] [🧪 Filter combinations]
>
> [🔁 Run Phase 2 (crawl deferred)] [⬇️ Download deferred list (CSV)] [Show samples]

Counts come from `deferred_summary` in `audit.json` (or the CSV as fallback).
Clicking **Run Phase 2** re-spawns the crawler in `--phase2` mode against the
same job directory: deferred URLs become seeds, the classifier is disabled,
results merge into the same JSON. No new job ID — same job, deeper data.

#### Files / modules

- `seo_crawler/seo_crawler/utils/url_classifier.py` **(new)** —
  `UrlClassifier(sitemap_urls, navigation_urls, pagination_max=3, filter_max=1)`
  with `.classify(url) -> (kind, is_deferred)`. Stateless `classify_url(...)`
  helper. 9/9 unit-style sanity checks pass.
- `seo_crawler/seo_crawler/crawler/async_core.py` — classifier instantiated
  in `__init__` from `crawl.deferred_crawl` config; `_enqueue(url, depth,
  source_url)` consults it and routes deferred URLs to `self.deferred` dict
  instead of the queue; sitemap URLs feed the classifier after sitemap parse;
  `discover_links` passes the source URL for diagnostic traceability.
- `seo_crawler/seo_crawler/main.py` — new `_deferred_list()` and
  `_deferred_summary()` helpers; `--phase2` CLI flag toggles
  `config.crawl.deferred_crawl.phase2 = True`; `run_crawl_async` injects
  `deferred_urls.csv` as seeds in Phase 2 via `_inject_phase2_seeds()`;
  `audit.json` gains `deferred_urls` (full list) and `deferred_summary`
  (counts + 10 samples per kind); `csv/deferred_urls.csv` always written
  alongside `excluded_urls.csv`.
- `webapp/job_runner.py` — `start_phase2(job_id)` method validates
  preconditions (job exists, config present, deferred CSV exists, no active
  job) and spawns a new subprocess with `--phase2` against the same job
  directory; log is appended (not overwritten) so Phase 1's log is preserved.
- `webapp/app.py` — `POST /api/jobs/{id}/phase2` and `GET /api/jobs/{id}/deferred`
  endpoints. The latter reads `deferred_summary` from `audit.json` if
  available, falls back to streaming `deferred_urls.csv`.
- `webapp/templates/job.html` — new deferred panel with kind-grouped cards,
  Phase 2 button, CSV link, expandable samples; wired into `finish()` via
  `_loadDeferred()`.
- `webapp/static/i18n.js` — 7 new keys × 2 languages
  (`deferred_h`, `deferred_p`, `phase2_run`, `phase2_starting`,
  `phase2_running`, `deferred_csv`, `deferred_show_samples`).
- `webapp/templates/index.html`, `json_exporter.py` — version bumps to v1.08.

#### Backward compatibility

- All previously-completed jobs work unchanged. They simply don't show the
  deferred panel (no `deferred_summary` in their JSON → API returns empty).
- A new crawl with the default `deferred_crawl.enabled: true` is the new
  default behavior. Setting it to `false` in `config.yaml` reverts to v1.07
  semantics (every discovered URL goes straight to the queue).
- The classifier honors `crawl.deferred_crawl.pagination_max` and
  `crawl.deferred_crawl.filter_max` for advanced overrides.

#### Verified

```
69/69 tests pass (5.1s)
9/9 classifier sanity checks pass
6/6 realistic-scenario classifications correct (15/30 deferred as expected)
node --check on both inline JS blocks: clean
Jinja render of index.html + job.html: clean
```

### Deferred (only remaining ROADMAP item)

- **Single-file Windows `.exe` (PyInstaller)** — needs a Windows CI build host.

## v1.07 — 2026-06-18

### Added — Aggressive URL normalization (queue shrink + crawl speed)

- **Tracking-param strip list expanded 9 → ~30.** `_TRACKING_PARAMS` in
  `utils/helpers.py` now covers Google Analytics (`utm_*`, `_ga`, `_gid`,
  `_gac`), Google Ads (`gclid`, `dclid`, `gbraid`, `wbraid`), Microsoft
  (`msclkid`), Meta (`fbclid`, `_fb`, `fb_*`), TikTok (`ttclid`), Twitter
  (`twclid`), LinkedIn (`li_fat_id`), Pinterest (`epik`), Yandex (`yclid`),
  Mailchimp (`mc_cid`, `mc_eid`), Instagram (`igshid`), plus generic
  `ref`/`affiliate`/`source` variants. All safe — these never change page
  content.
- **Per-platform query-param normalization.** Each preset in
  `config_presets.PRESETS` now carries a `strip_query_params` list, and
  `apply_preset` calls a new `helpers.set_extra_strip_params(...)` so the
  active preset's params are stripped globally for the crawl:
  - **Zid:** `sort_by`, `sort`, `order_by`, `order`, `view`
  - **Salla:** `sort`, `order`, `view`
  - **Shopify:** `sort_by`, `sortBy`, `view`
  - **WooCommerce:** `orderby`, `order`, `min_price`, `max_price`
- **Why it's safe (and what it preserves):** these params produce
  same-content-different-order pages that the platform itself canonicalizes
  to the base URL. Collapsing them on the crawler side just avoids fetching
  redundant variants. **Pagination is NOT touched** — `?page=1` and `?page=2`
  remain distinct because they carry different content.
- **Expected impact:** for a Zid store like the one in our test case, the
  queue shrinks by 40-70% (multiple sort_by variants × 50+ categories
  collapse to one each). Crawl wall-time drops proportionally.

### Files touched

`seo_crawler/seo_crawler/utils/helpers.py` (expanded `_TRACKING_PARAMS` set,
new `_EXTRA_STRIP_PARAMS` + `set_extra_strip_params()`, `normalize_url` honors
both), `seo_crawler/seo_crawler/config_presets.py` (`strip_query_params` per
preset + `apply_preset` wires it via `set_extra_strip_params`),
`webapp/templates/index.html` (v1.07 version tag),
`seo_crawler/seo_crawler/exporters/json_exporter.py` (version bump).

### Verified behaviors (manual test)

```
normalize_url("https://x/a?utm_source=fb&gclid=Y&_ga=Z")
  → "https://x/a"                                                # tracking stripped

normalize_url("https://x/c?sort_by=price&page=2")               # before preset
  → "https://x/c?page=2&sort_by=price"                          # sort_by KEPT

# After: set_extra_strip_params(["sort_by", "sort", "order_by", "order", "view"])
normalize_url("https://x/c?sort_by=price&page=2&view=grid")
  → "https://x/c?page=2"                                        # sort_by + view stripped, page KEPT

normalize_url("https://x/c?page=1") != normalize_url("https://x/c?page=2")
  → True                                                         # pagination preserved
```

### Note for the in-progress crawl

The current running job started before this fix; restart it (or let it finish)
to see the queue shrink. Future crawls with `platform_preset` set get the
optimization automatically — no extra UI step.

### Deferred (only remaining ROADMAP item)

- **Single-file Windows `.exe` (PyInstaller)** — needs a Windows CI build host.

## v1.06 — 2026-06-18

### Fixed — two bugs hit in real-world use

- **Integrations-only jobs no longer break the report panel.** When a user ran
  «تكاملات فقط (بلا زحف)», the output was `integrations_*.json` (no pages/links),
  but v1.04's on-demand generate buttons still appeared and every click failed
  with `RuntimeError: no audit JSON for this job`. Fix: `_discover_result` now
  recognizes `integrations_*.json` and tags the result with `kind`
  (`audit` vs `integrations_only`). The job page hides the HTML/PDF/Excel/XML
  generate row for integrations-only jobs and shows a clear hint pointing the
  user to «زحف كامل» if reports are wanted. The existing CSV file list still
  renders (gsc_pages, gsc_queries, ga4_landing_pages, pagespeed_*, etc.) so the
  fetched data is fully accessible.
- **Google OAuth token expiry is now detected before the crawl, not during it.**
  Google's "Testing" mode revokes refresh tokens every 7 days, which previously
  surfaced as a mid-job `invalid_grant: Token has been expired or revoked.`
  failure. `/api/google/status` now actively probes both tokens (silent
  `creds.refresh()`) and returns an `expired` flag. The readiness chip turns
  amber/red with «⚠️ Google (منتهٍ — أعد التفويض)» and the status line in the
  Integrations tab points the user at «وافق بحسابي» — no guessing why GSC
  suddenly stopped working. The `client_secret` stays saved across re-consents,
  so the user only re-approves, doesn't re-upload.

### Files touched

`webapp/job_runner.py` (integrations_json + kind in `_discover_result`),
`webapp/templates/job.html` (kind-aware `_syncResultKindUI`, integrations-only
note, hidden gen-row), `webapp/templates/index.html` (expired-aware readiness
chip + gStatus text, v1.06 version tag), `webapp/static/i18n.js`
(`integrations_only_note` + `g_expired` + `r_google_expired` AR/EN),
`webapp/app.py` (`_probe_token_expired` + `/api/google/status` returns
`expired`), `seo_crawler/seo_crawler/exporters/json_exporter.py` (version bump).

### Notes

- The two already-completed jobs from the report-failure session
  (`20260618_115942_298d71` and `20260618_120723_1d186a`) were backfilled with
  the new `kind: "integrations_only"` flag so the user's existing job pages
  display the hint without re-running anything.
- This release does not change Google's 7-day Testing-mode policy itself —
  removing that requires OAuth verification (sensitive scopes). v1.06 just makes
  the expiry visible *before* it bites in the middle of a job.

### Deferred (only remaining ROADMAP item)

- **Single-file Windows `.exe` (PyInstaller)** — needs a Windows CI build host.

## v1.05 — 2026-06-02

### Added — User-Agent spoofing (Googlebot simulation)

- **Configurable User-Agent under Advanced crawl options.** Four presets +
  custom: regular visitor (default, unchanged), Googlebot, Googlebot Mobile,
  Bingbot. The selector lives next to the platform preset in the Advanced
  collapsible; picking "Custom" reveals a text input for an arbitrary UA string.
- **Why this exists**: a regular-UA crawl can't see Cloudflare/WAF blocks
  that specifically target bots — e.g. a Zid/Cloudflare store can return 14k+
  GSC 403s on bot-only paths that SCT can't reproduce when it crawls as a
  normal browser. Picking "Googlebot" reproduces what Google's crawler sees
  and surfaces those blocks immediately.
- **Plumbing**: `ua_preset` is mapped to a real UA string in `webapp/job_runner.py`
  and written to `crawl.user_agent` in the job config. The existing crawler
  reads it without modification (`http_client.py` already accepts a per-job UA).
- Bilingual tooltip warns to lower crawl speed when impersonating a bot to
  avoid tripping rate-limit rules.

### Files touched

`webapp/templates/index.html` (UA dropdown + custom box + JS show/hide,
v1.05 version tag), `webapp/static/i18n.js` (AR + EN UA preset keys + tooltip),
`webapp/app.py` (`_UA_PRESETS` mapping note, `ua_preset` + `ua_custom`
plumbed into overrides), `webapp/job_runner.py` (preset → `crawl.user_agent`
translation), `seo_crawler/seo_crawler/exporters/json_exporter.py` (version
bump 1.04 → 1.05).

### Deferred (only remaining ROADMAP item)

- **Single-file Windows `.exe` (PyInstaller)** — needs a Windows CI build host.

## v1.04 — 2026-06-01

### Added — 6 ROADMAP items shipped in one drop

- **Queue counter clarity when `max_pages` is reached.** The async crawler now
  emits `reached_max_pages: true` in every progress tick once the cap is hit;
  the job-page renders the queue card with a dimmed label "discovered (won't
  crawl)" instead of misleading "17,583 in queue". Removes the recurring
  "the tool looks like it's still working" confusion.
- **Silence-aware "why am I waiting?" hint.** A small ticker on the job page
  watches all counters + phase signature; if nothing changes for ≥30 seconds it
  surfaces a phase-aware hint (e.g. "Playwright is launching Chromium for the
  first time — 30-60s", "each PageSpeed call takes ~25s × 2 strategies", "writing
  dozens of CSV files can take a minute"). Pairs with the v1.03 per-URL phase
  detail for full visibility.
- **Excel + XML added to on-demand generation.** v1.03 shipped HTML/PDF as
  per-format generate buttons; v1.04 extends the same UI + endpoint to Excel and
  XML. Both rebuild from the audit JSON + the always-present CSV files (so even
  if `output.json_full=false` they still work — links/images/headings are loaded
  from `csv/`). `csv` + `json` are now the *only* always-generated formats.
  XML download zips the multi-file `xml/` folder transparently.
- **Crawl visualization page (`/jobs/<id>/graph`).** Three views in one page:
  (1) depth + status-code distribution as horizontal bars, (2) hierarchical site
  tree built from URL path segments with collapsible `<details>` and red
  highlighting for branches containing 4xx pages, (3) a force-directed link map
  on canvas (no external deps — small vanilla simulation, capped at 500 nodes
  for browser perf). Reachable from the job page via the new "🗺️ Crawl map" button.
  New endpoint: `GET /api/jobs/<id>/graph`.
- **Log analyzer → Action Board join.** New helper
  `join_log_with_audit(log_per_url, audit)` in `analyzers/log_analyzer` and a
  new endpoint `POST /api/jobs/<id>/log-board` that takes a server log upload
  and joins it with the current job. Output: (a) **wasted Google crawl budget**
  — pages Google hits a lot that return 4xx/5xx, (b) **high-value pages with
  issues** — pages Google cares about *and* have priority issues (the most
  consequential to fix), (c) **orphan-at-Google** — pages Google knows but our
  crawler didn't discover (strong internal-linking signal), (d) **rescored
  priority** — every priority page boosted by `log10(googlebot_hits + 1) × 10`.
  UI surfaces all four as a collapsible section on the existing Action Board
  page with summary cards and tables.
- **Live backlinks API integrations** (Ahrefs v3 + Majestic OpenApp). New module
  `integrations/backlinks_api.py` with a unified shape across providers
  (`summary`, `top_referring_domains`, `top_anchors`) so the report doesn't care
  who fetched the data. Off by default; paid keys required. The key flows through
  the existing secret-via-env pattern (`BACKLINKS_API_KEY`), never written to
  disk. Lives next to the free AWT CSV importer in the Integrations tab with a
  tooltip pointing users to the free option first. Documented in
  `docs/EXTERNAL_TOOLS_GUIDE.md`.

### Changed

- **Default crawl formats reduced to `csv + json` only.** Excel/HTML/PDF/XML are
  all on-demand now. Cuts crawl wall-time (especially on large sites) and gives
  the user explicit control over which formats actually get built.
- **`reached_max_pages` flag** is now part of every progress tick (not just the
  final one) so the UI can react during the crawl, not after.

### Backend

- New endpoints: `POST /api/jobs/<id>/log-board`,
  `GET /api/jobs/<id>/graph`, `GET /jobs/<id>/graph`.
- Extended endpoints: `POST /api/jobs/<id>/generate?format=excel|xml`,
  `GET /api/jobs/<id>/download/xml` (zips the xml folder).
- New module `integrations/backlinks_api.py` (`BacklinksProvider`,
  `AhrefsClient`, `MajesticClient`).
- New analyzer entry `analyzers.log_analyzer.join_log_with_audit`.

### Files touched

`webapp/templates/index.html` (backlinks API card, v1.04 version tag),
`webapp/templates/job.html` (queue-counter dimming, silence hint, Excel/XML gen
buttons, Crawl-map link), `webapp/templates/board.html` (log-board section),
`webapp/templates/graph.html` **(new)**, `webapp/static/i18n.js` (40+ new
keys in both AR/EN: graph, log-board, backlinks, queue capped, silence hints),
`webapp/static/app.css` (carries over v1.03 styles), `webapp/app.py`
(`/api/requirements` already shipped, new `/jobs/<id>/graph` + `/api/.../graph`
+ `/api/.../log-board`, extended generate to excel/xml + xml-download zip),
`webapp/job_runner.py` (`BACKLINKS_API_KEY` secret pass-through),
`seo_crawler/seo_crawler/main.py` (run_integrations: backlinks block),
`seo_crawler/seo_crawler/integrations/backlinks_api.py` **(new)**,
`seo_crawler/seo_crawler/analyzers/log_analyzer.py` (`join_log_with_audit`),
`seo_crawler/seo_crawler/crawler/async_core.py` (`reached_max_pages` in progress),
`seo_crawler/seo_crawler/exporters/json_exporter.py` (version bump),
`docs/EXTERNAL_TOOLS_GUIDE.md` (Ahrefs/Majestic live API section).

### Deferred to a later release

- **Single-file Windows `.exe` (PyInstaller)** — the only remaining ROADMAP P3
  item. The PowerShell installer continues to be the supported non-Docker
  Windows path; a true bundled `.exe` needs a Windows CI build host.

## v1.03 — 2026-06-01

### Added — UI/UX overhaul driven by 8 user-feedback items

- **Hoverable tooltips on every UI control** (`?` and `⏱` badges). 30+ bilingual
  tooltips explain what each option does, what it costs in time when applicable
  ("PageSpeed adds ~25s per URL × 2 strategies", "URL Inspection ~1s per URL",
  "JS rendering +200-400%"), and what the platform preset / sample-per-host /
  CrUX History / Save-raw-Lighthouse options actually do. Tooltip text is loaded
  from i18n (`tip_*` keys in both AR and EN) and re-applied on language switch.
- **Multi-stage progress with current-URL detail.** Progress now emits
  `phase_label` + `phase_percent` + `phase_detail` for every long phase
  (PageSpeed loop per URL, External-links check, Analysis, Export). The job page
  shows the operation name ("جلب من PageSpeed…"), a percentage that actually
  moves, and a monospaced URL row underneath (e.g. `[42/212] mobile: /products/…`).
  No more "stuck at 09:05 for 4 minutes" mystery — the user sees what's happening.
- **Optional-requirements status row** at the top of the main page. Compact chips
  for Excel (openpyxl), PDF (Chromium), GA4 — each shows ✓ present or ✗ missing
  with an inline [Install] button that triggers the existing background installer.
  Backed by a new `/api/requirements` endpoint that probes once and caches.
- **On-demand HTML/PDF generation.** Removed the "output formats" multi-checkbox
  from the main page; the crawl now always emits raw data (CSV + JSON + Excel),
  and HTML/PDF are built only when the user clicks the per-format
  `[🌐 Generate HTML] [⬇️ Download]` / `[📄 Generate PDF] [⬇️ Download]` buttons
  on the job page. Cuts crawl wall-time noticeably (PDF via Playwright is the
  slowest single step), saves disk on jobs whose reports are never opened.
  New endpoint `POST /api/jobs/<id>/generate?format=html|pdf` runs in background;
  `GET …/generate/<fmt>/status` polls.
- **AI advisor — per-provider field cleanup.** Provider dropdown now hides
  irrelevant fields dynamically: cloud providers (OpenAI/Gemini/DeepSeek/
  OpenRouter/HuggingFace) show just API key + model + opps; new explicit
  **🖥️ Local model (Ollama / LM Studio)** option shows endpoint URL + model +
  allow-private (auto-suggests `http://127.0.0.1:11434/v1`) and hides the API
  key; the custom OpenAI-compatible option shows all three. Eliminates the old
  "every field always visible regardless of provider" confusion.
- **PageSpeed DNS-error resilience.** The PageSpeed client now catches
  `getaddrinfo` / `NameResolutionError` / generic `ConnectionError` and retries
  with 2s/5s/10s backoff (vs the old "fail-fast on any exception"). Repeated
  errors are aggregated into a single end-of-job summary line
  (`PageSpeed errors summary: total=X | dns=… timeout=… http_429=… http_5xx=…
  other=…`) instead of one ERROR row per failed URL. Addresses the exact
  log noise we saw on the 31 May audit.
- **GA4 property_id discovery doc** at `docs/GA4_PROPERTY_ID.md` with both the
  GA4-admin path and the in-UI "📋 Fetch GA4 properties" shortcut, plus a clear
  Property-ID vs Measurement-ID distinction.
- **Full OAuth setup doc** at `docs/OAUTH_SETUP.md` (3 steps: enable APIs +
  configure consent screen + create Desktop OAuth client), plus the paste-the-code
  fallback for headless machines, plus a "common errors" table.

### Changed — main-page simplification

- **Max depth default lowered to 5** (was 10) with a tooltip explaining what
  depth means in clicks-from-homepage. 5 covers a typical e-commerce store
  (home → category → subcategory → product → variant); deeper crawls remain
  configurable.
- **Mode selector hidden from main page**; moved into the new "Advanced crawl"
  collapsible. Default `audit` fits 95% of cases; `competitor` and `compare`
  are still available for the rare cases that need them.
- **Manual speed-tuning controls** (delay + concurrency) moved one level deeper
  inside the Advanced collapsible. The 5-step speed slider is what most users
  should touch; the manual controls remain for power users.
- **External-links + resource-status + adaptive-throttle + sitemap-generation
  + platform-preset** consolidated under the same Advanced collapsible.
- **OAuth setup section trimmed to a single doc link** in the UI (the 3-step
  inline guide moved to `docs/OAUTH_SETUP.md`, served at `/docs/oauth_setup`).
  Less wall-of-text in the main interface; the doc itself is more thorough.
- **Lighthouse / AWT importers folded under a single "External data" collapsible**
  in the integrations panel — both are rarely needed since PageSpeed API covers
  Lighthouse data and most users get backlinks via separate tools.

### Backend

- New `/docs/<name>` endpoint serves project markdown files as inline HTML
  (zero deps — small in-house md→html converter handles `#/##/###`, code fences,
  bullet/numbered lists, `**bold**`, `code`, and `[text](url)`). Mapped names:
  `oauth_setup`, `ga4_property_id`.
- `emit_phase()` now consistently sets `phase_label` + `phase_percent` (where
  known) at: `integrations`, `analyzing`, `exporting`, `checking_external_links`,
  `pagespeed` (per URL via callback). The job UI prefers these over the old
  generic `status` for the phase label.
- `PageSpeedClient` constructor accepts `on_progress(idx, total, url, strategy)`
  callback used to drive `phase_detail` in the UI.

### Files touched

`webapp/templates/index.html` (tooltips, simplified main, AI panel cleanup, hidden
mode, depth 5 default, requirements row, removed formats UI),
`webapp/templates/job.html` (phase detail row, per-format generate buttons +
download), `webapp/static/app.css` (`.tip`, `.phase-detail`, `.req-row`, `.gen-row`,
`.gen-box` styles), `webapp/static/i18n.js` (30+ `tip_*` + `req_*` + `gen_*` +
`ph_*` keys in both AR and EN), `webapp/app.py` (`/api/requirements`,
`/docs/<name>`, `/api/jobs/<id>/generate`, `/api/jobs/<id>/generate/<fmt>/status`,
updated default formats), `seo_crawler/seo_crawler/integrations/pagespeed_api.py`
(DNS retry, error stats, on_progress hook, end-of-job summary),
`seo_crawler/seo_crawler/main.py` (phase_label + phase_detail emission at every
long phase including the PageSpeed loop), `seo_crawler/seo_crawler/exporters/
json_exporter.py` (version bump). New: `docs/OAUTH_SETUP.md`,
`docs/GA4_PROPERTY_ID.md`.

## v1.02 — 2026-05-30

### Added (docs for a real open-source project)
- **Expanded `CONTRIBUTING.md`** (and **new `CONTRIBUTING_AR.md`**): local setup, code
  style, hard safety rules, bilingual i18n discipline, concrete "how to add an
  analyzer / integration / UI tab" recipes, branching + PR workflow, the release process
  (bump `_meta.version`, topbar tag, CHANGELOG), and bug/feature reporting.
- **`CODE_OF_CONDUCT.md` + `CODE_OF_CONDUCT_AR.md`**: Contributor Covenant 2.1 in both
  languages.
- **`docs/ARCHITECTURE.md` + `docs/ARCHITECTURE_AR.md`** (developer-focused):
  bird's-eye diagram, complete module map, full data flow, the 10 key design decisions
  (local-only, async + sync fallback, SQLite per job, deterministic prioritization,
  off-by-default integrations, no-secrets-in-repo, own-OAuth-per-user, bilingual i18n,
  streaming size caps, defense-in-depth security), extension points, and a
  "where to look for X" reference.
- **`docs/CLI.md` + `docs/CLI_AR.md`**: full reference for `main.py` and
  `webapp/run.py` flags, every relevant environment variable, and worked scenarios.
- **READMEs**: new "Documentation" table linking every doc with its language
  counterpart; LICENSE blurb spells out the MIT permissions (copy / modify /
  distribute / commercial use) under "Copyright (c) 2026 Ahmad-Ajm".

### Changed
- `docs/DOCUMENTATION_AR.md` (the older 19 KB Arabic reference that overlapped with
  `USER_GUIDE_AR.md`) was retired and moved to the local `_review/` folder; its
  developer-facing content lives in the new `ARCHITECTURE_AR.md`, its end-user content
  is already in `USER_GUIDE_AR.md`. Cross-references in both USER_GUIDE files updated.

## v1.01 — 2026-05-30

### Added
- **Job management from the UI:** the Recent jobs table now has a checkbox per row,
  a select-all checkbox in the header, **🗑️ Delete selected**, and
  **🧹 Delete all (except active)**. Each row also has its own **🗑️ Delete** button.
  Two new endpoints — `POST /api/jobs/<id>/delete` and `POST /api/jobs/delete-all` —
  back the UI; each delete removes the job's entire folder (log + outputs + state).
  Safety: the currently-running job cannot be deleted (must be stopped first); invalid
  job IDs are rejected; path is resolved-and-checked to never escape `webapp_jobs/`.
  AR + EN i18n keys for the new strings. Regression test covers the safety branches
  (invalid id, running job, valid delete, empty `delete_all`).

## v1.00 — 2026-05-30

First numbered release. Marks the feature-complete baseline of the local web UI + crawler
pipeline. Highlights of this milestone:

- **UI redesign (5 tabs → 3):** Crawl + Integrations & AI + Advanced. Integrates Report
  settings as a collapsible inside Crawl; adds readiness chips (Google / Chromium / Ready)
  at the top; unified Start button with mode radio (Full crawl / Integrations only);
  first-run welcome card; dynamic settings summary above Start; collapsible "What to
  collect" and "Manual speed controls"; auto-focused URL field; Reset-to-defaults button;
  persistent top-bar link to the Log analyzer; promoted Explore / Board / Compare links to
  primary on the job page. Every UI label is bilingual (AR + EN) with 365 i18n keys
  perfectly aligned across both dicts.
- **Authorship & versioning:** LICENSE switched to "Copyright (c) 2026 Ahmad-Ajm"; the
  audit JSON `_meta` now carries `version: "1.00"` and `author: "Ahmad-Ajm"`; topbar shows
  `v1.00 · by Ahmad-Ajm`.

### Added (in this milestone)
- **Crawl comparison surfaced in the UI** (`/jobs/<id>/compare`): pick another previous run
  from a dropdown and see fixed / new / persisting issue types, totals delta, "improved"
  flag, and page-set changes — all backed by the existing `analyzers/crawl_compare`. New
  endpoints `/api/jobs/list` (jobs that have an audit JSON) and
  `/api/jobs/<id>/compare?with=<other>`. Linked from the job page next to Action Board.
- **Server log analyzer** (`/logs`): upload an Apache/Nginx Combined Log Format file and get
  per-URL Googlebot crawl-budget (200/3xx/404/5xx breakdown), top bots, and a downloadable
  CSV — all processed locally, capped at 500 MB upload. New pure module
  `analyzers/log_analyzer` (`parse_log_line`, `analyze_log`, `detect_bot`,
  `find_orphan_bot_urls`) and endpoint `POST /api/logs/analyze`.
- **Windows installer scripts** (`installer/`): `install.ps1` (no admin needed; creates a
  local venv, installs requirements, installs Chromium for Playwright, and adds Desktop +
  Start Menu shortcuts), `run.bat` (double-click launcher that opens
  <http://127.0.0.1:8000>), `uninstall.ps1`, and a README. Concrete non-Docker path for
  Windows users.
- **URL drill-down detail panel** in the Action Board (`/jobs/<id>/board`): clicking a row
  slides out a panel with all of SCT's data joined for that one URL — crawl page data, GSC
  (clicks/impressions/CTR/position), URL Inspection (verdict/coverage), GA4 (sessions/users/
  engagement), PageSpeed scores (mobile + desktop with lab CWV + CrUX overall), Priority
  Engine output (page type, band, action group, owner, ease, factor breakdown), and
  accessibility (axe violations). New `/api/jobs/<id>/url-detail?url=…` endpoint backed by
  the pure `reporting/url_detail.build_url_detail(audit, url)` helper. URL matching uses
  the project's `normalize_url`; GA4 matches by path.
- **Easier Google sign-in (own-credentials model)**: each user/agency uses their own Desktop
  OAuth client (fully isolates quota from the project owner; needs no shared secret in the
  repo). The UI now adds:
  - **Site/property pickers** — "Fetch my GSC sites" and "Fetch GA4 properties" buttons
    populate dropdowns from the connected account (`/api/google/gsc-sites`,
    `/api/google/ga4-properties` — using the Analytics Admin API for properties).
  - **Paste-the-code fallback** for headless/remote machines: `/api/google/authorize-url`
    returns the consent URL; the user opens it in any browser, then pastes back the code or
    the full callback URL into `/api/google/authorize-code` (`_extract_oauth_code` parses
    either form).
  - **Full disconnect** option: `?full=1` on `/api/google/disconnect` also removes the saved
    `client_secret.json` (so you can switch to a different one).
  - **3-step guided setup** (collapsible help in the UI) explaining Cloud Console → APIs →
    OAuth consent (Testing mode) → Desktop client, with the 7-day refresh-token caveat for
    Testing mode and the sensitive-scope verification note for Production.
- **Accessibility checks (axe-core)** (optional, `accessibility.enabled`, off by default;
  requires JS rendering): runs axe-core in the rendered Playwright page (capped by
  `accessibility.max_pages`), with the axe source from a local file (`accessibility.axe_source`)
  or a trusted CDN (`allow_cdn`). Outputs `accessibility.csv` (per-page violation/impact counts)
  + `accessibility_issues.csv` (every violation) and an `accessibility` block in the JSON.
  Degrades gracefully if axe/Playwright is unavailable.
- **Interactive Action Board page** (`/jobs/<id>/board`): an in-browser view of the Priority
  Engine output — grouped by action group, filterable by group/page-type/priority/URL, sortable,
  with a filtered-CSV download (served by `/api/jobs/<id>/priority`). Linked from the job page
  next to "Explore results".
- **Docker packaging**: a `Dockerfile` (on the official Playwright image, so Chromium/JS
  rendering/PDF work out of the box) + `docker-compose.yml` + `.dockerignore`. `docker compose
  up --build` runs the whole tool; outputs persist in `./webapp_jobs`; secrets stay out of the
  image (read from `.env` at runtime).
- **Web UI toggles for the new options** (no terminal needed): platform preset
  (Zid/Salla/Shopify/WooCommerce), adaptive throttle, and sitemap generation in the advanced
  crawl options; GSC URL Inspection (+ cap) in the GSC card; and CrUX History in the PageSpeed
  card. Wired through `/api/start` → `job_runner._build_job_config`; form values persist in
  localStorage like the rest of the form.
- **Priority Engine v2 + Action Board** (deterministic, no AI): a transparent multi-factor
  per-page priority score `severity × impact × ease × confidence`, where *impact* combines
  search demand (GSC) + business value (GA4) + **page importance** (page type + depth +
  internal links). Each page gets a `page_type` (home/category/product/blog/static), an
  `ease`/`owner` (content / SEO / developer / platform-support — platform-aware for
  Zid/Salla/Shopify), a relative `priority_band` (high/medium/low), and an `action_group`
  (Do now / Needs content / Needs developer / Needs platform / Do later / Low impact). New
  outputs `page_priority.csv` (with a full factor breakdown for transparency) and
  `action_board.csv`, a `priority` block in the JSON, and an **Action Board section in the
  expert report**. Works even without integrations (page importance + severity still rank).
- **Deep PageSpeed/Lighthouse tables** (from the raw report we already fetch, no extra API
  call): `pagespeed_audits.csv` (all ~150 audits), `pagespeed_network_requests.csv` (every
  request with size/status/protocol/priority/entity), `pagespeed_js_treemap.csv` (per-script
  bytes + computed unused %), and `pagespeed_failed_audits.csv` (only real failures —
  `scoreDisplayMode binary/numeric` and `score < 1`, with a `None`-safe filter). The big
  tables are excluded from the JSON archive (kept in CSV) to keep JSON light.
- **GSC insights** computed from data already fetched: `keyword_cannibalization.csv`
  (multiple pages competing for one query) and `internal_link_opportunities.csv` (pages with
  high search impressions but few internal inlinks, by joining GSC with the internal link
  score). No extra crawl or client involvement.
- **GSC URL Inspection** (optional, `integrations.gsc.url_inspection`, off by default): real
  per-URL index status/verdict/coverage via the URL Inspection API → `gsc_index_status.csv`,
  capped by `inspect_max_urls` to respect the daily quota.
- **CrUX History** (optional, `integrations.pagespeed.crux_history`, off by default): Core Web
  Vitals field-data trend over time (p75 per period) → `crux_history.csv`, using the existing
  PageSpeed key.
- **Sitemap generator** (`output.generate_sitemap`, off by default): clean `sitemap.xml` from
  indexable (200, self-canonical) pages, splitting into a sitemap index above 50,000 URLs.
- **Crawl comparison over time** (`analyzers.crawl_compare`): compare two audit runs of the
  same site → fixed / new / persisting issue types + page add/remove + totals delta.
- **Prioritized hints** on every SEO issue: `impact`, `effort`, `why_it_matters`,
  `how_to_fix`, and a `priority_score` (impact ÷ effort) — actionable client reporting.
- **Adaptive throttle** (`crawl.adaptive_throttle`, off by default): automatically slows the
  crawl on 429/5xx/slow responses and recovers as the site stabilizes.
- **E-commerce presets** (`site.platform_preset`: zid | salla | shopify | woocommerce): adds
  recommended exclude patterns (cart/checkout/account) without clearing yours; includes a
  platform detector.
- **Accessibility (axe-core) module** (`analyzers.accessibility`, optional): pure summarizer
  for axe results + a helper to run axe on a rendered Playwright page.
- **Auto-install of optional requirements** (`utils.auto_install`): when the tool needs an
  optional library it installs it automatically (notifying, no prompt), restricted to a known
  allowlist of the tool's optional deps; disable with `SCT_NO_AUTO_INSTALL=1`.
- Output files browser in the job page: a labelled, grouped list of **every** produced file
  (Reports / Excel / Archive / CSV data / XML) with human‑readable bilingual names and sizes.
  Each file downloads individually, **“Download all (ZIP)”** grabs everything in one click,
  and you can tick a subset and **“Download selected (ZIP)”**. New endpoints
  `/api/jobs/<id>/files`, `/download-file?rel=…`, and `/download-all[?only=…]` (all with
  path‑containment checks).
- AI advisor (optional, `integrations.ai`, off by default): provider-agnostic assistant
  (`requests`-only, no new dependency) that reads the audit summary + top opportunities and
  returns an executive summary plus prioritized, specific recommendations. Providers:
  **OpenAI, DeepSeek, OpenRouter, Hugging Face** (OpenAI-compatible `chat/completions`) and
  **Google Gemini** (`:generateContent`), plus a custom `openai_compatible` endpoint for
  local models (Ollama/LM Studio/gateways) via `base_url`+`model`. Pick the provider and
  enter the key from the UI advanced settings; the key is passed to the crawl process via
  the `AI_API_KEY` env var and never written to the job config or the repo. No PII is sent —
  only page URLs, issue types, and aggregate numbers. Output appears as an AI section in the
  report (client + expert) and as `ai_recommendations.csv` + a block in the JSON. Degrades
  gracefully when the key/library is missing or the call fails.
- Two report audiences (`report.audience`: `client` | `expert` | `both`): the **client**
  report is a short, plain-language summary with an overall health score/rating and the
  top issues (no deep technical tables); the **expert** report is the full technical
  document and now also includes dedicated Pagination, Hreflang, and Resource-inventory
  sections. `both` produces two files (`report_*_client.*` and `report_*_expert.*`).
  Selectable from the UI (start form and report-rebuild form) with separate download
  buttons. The report's redirect section is also fixed (the JSON now carries
  `redirect_data`, so redirects/pagination/resource-status render in the report).
- Pagination (`rel=next`/`rel=prev`): new `pagination_extractor` + `pagination_analyzer`
  detect paginated sequences and flag broken reciprocity (A.next=B but B.prev≠A),
  next/prev targets that are 4xx/5xx or noindex, and non-self canonicals on paginated
  pages → `pagination.csv` + `pagination_issues.csv`. New page columns
  (`pagination_next`/`pagination_prev`/`is_paginated`); enabled via
  `extraction.extract_pagination` (on by default) and the UI collection group.
- Per-resource HTTP status checking (optional, `extraction.check_resource_status`, off by
  default): reuses the external-link checker to fetch each unique page resource
  (CSS/JS/images/fonts/media/iframe) and reports its status → `resource_status.csv`.
  Toggle from the UI advanced options.
- Hreflang issues export: the existing reciprocity/return-link validation (non-reciprocal,
  points-to-404, points-to-noindex, invalid format, missing self/x-default, duplicates,
  lang mismatch) is now written to `hreflang_issues.csv` for download.
- Unified report combining Technical SEO + Search Visibility (GSC) + User Behavior (GA4),
  plus a **Priority Opportunities** section that cross-references technical issues with
  clicks/impressions/sessions to rank what to fix first. New GA4 connector
  (`integrations/ga4_api.py`, optional `google-analytics-data`), join + scoring engine
  (`reporting/`), and exports `gsc_pages.csv`, `gsc_queries.csv`, `ga4_landing_pages.csv`,
  `ga4_channels.csv`, `priority_opportunities.csv`. GSC/GA4 configurable from the UI.
- Resource Inventory: collect CSS/JS/images/fonts/media/iframes per page (type, internal/
  external, mixed content) → `resources.csv` + `resource_issues.csv` + summary; enabled via
  `extraction.extract_resources` and the UI collection group.
- Async JavaScript rendering (Playwright): modes `all`/`sample`/`on_empty_content`, raw↔rendered
  diff (links/content/title/canonical/console errors) → `js_diff.csv`; rendered HTML is used
  for extraction and link discovery. Gracefully skipped if Playwright is not installed.
- UI "Advanced settings": configure integrations (GSC, PageSpeed API key, Lighthouse
  folder, AWT), custom-extraction rules (visual add/remove editor), and analysis thresholds
  directly from the web interface (no manual YAML editing). Keys are stored only in the
  local per-job config.
- Security headers analyzer (HTTPS/HSTS/CSP/X-Frame-Options/X-Content-Type-Options/
  Referrer-Policy/Permissions-Policy/mixed content) → `security_issues.csv` + JSON; new DB
  columns persisted for the missing security headers.
- Custom Extraction (`custom_extraction` config): CSS selector (text/attr/html) and regex
  rules → `custom_extraction.csv` + JSON (sync and async crawlers).
- Redirect detail reports: `redirect_chains.csv`, `redirect_loops.csv`, `redirect_issues.csv`.
- Optional Lighthouse/PageSpeed JSON import (no keys/internet): reads a local folder →
  `lighthouse_import.csv` (performance/accessibility/best-practices/seo, 0–100).
- Visual results explorer (`/jobs/<id>/explore`): client-side filter/sort/search over pages
  (status, indexability, depth, content type, missing H1/meta/canonical/title) + filtered CSV.
- External tools guide docs (EN+AR) for Lighthouse/axe-core/OWASP ZAP/GSC + example READMEs.
- Crawl seed strategy `crawl.seed_strategy`: `homepage` (start page + link BFS),
  `sitemap` (legacy flood), `hybrid` (default: homepage+links first, sitemap as deferred
  seeds). Selectable in the UI.
- Web UI English/Arabic language toggle (i18n, persisted in localStorage).
- Clear completion status: `complete` / `partial` / `partial_max_pages` / `stopped` /
  `failed` (instead of always "done").
- "Excluded URLs" report (excluded_urls.csv + JSON) with reasons (robots/filters/max_depth/ssrf).
- Image stats now report unique-by-src counts alongside occurrences (avoids inflation).
- `analysis.url_flag_non_ascii` (default off): non-ASCII URLs are informational, not an
  issue (suits Arabic sites).
- `observability.slow_call_summary` (default on): slow calls are summarized at the end
  instead of one WARNING per call.
- "All pages" checkbox (max_pages = 0 = unlimited) and crawl-speed slider in the UI.
- Integrated local Web UI (FastAPI + HTMX + SSE): configure settings, set URL, choose
  mode, start/stop crawls, live progress monitoring, and report downloads (`webapp/`).
- Grouped collection checkboxes (select all/partial/all groups), output-format selection,
  and PDF/HTML report formatting options in the UI.
- Crawl-speed slider (gentle→max) mapping to delay/concurrency, with a server-side floor
  (min delay 0.1s, max concurrency 20) to protect sites.
- Live elapsed-time counter on the job page (ticks while running, freezes on stop/finish).
- Per-job self-contained logs under `webapp_jobs/<job_id>/logs/` and rotating log files
  honoring `max_log_size_mb`.
- Customizable HTML and PDF reports (Arabic/RTL via Playwright): `html`/`pdf` output
  formats and `exporters/html_exporter.py`, `pdf_exporter.py`, `report_builder.py`.
- Reliable async resume: crawl progress (visited + queue) persisted to SQLite and
  restored on re-run.
- SSRF protection (`is_safe_remote_url`) applied to crawl URLs, redirect targets, and
  sitemap/robots-declared URLs; new `crawl.allow_private_hosts` option.
- Glob support in `filters` patterns (in addition to substring matching).
- Configurable thin-content thresholds (`thin_content_critical_threshold`,
  `text_ratio_threshold`).
- Regression test suite covering the fixes below.

### Fixed
- **English translation gap closed**: 24 UI strings that were Arabic-only (fell back to inline
  HTML text when the user toggled to English) now have proper English translations in
  `i18n.js`. Audit shows both `ar` and `en` dicts now cover 365 keys, with **no key used in
  any template/JS missing from either language** (except 2 dynamic-prefix false positives —
  `band_` and `ph_` — that are concatenated at runtime). A small audit script is kept locally
  in `_review/` (gitignored) for re-running the check.

### Changed
- **Repo cleanup:** archived `AUDIT_NOTES.md` (closed since 2026-05-21; content fully covered
  by this CHANGELOG) is moved out of the repo into a local gitignored `_review/` folder. The
  test docstring that referenced it now points to the CHANGELOG.

### Fixed
- **Connection-test endpoints could hang the server** (`/api/test/gsc`, `/api/test/ga4`): they
  ran the client's `authenticate()` which, with OAuth client-secret credentials and no valid
  token, opened an interactive `run_local_server` browser-consent flow and **blocked the
  executor thread indefinitely** (the `analytics.readonly` OAuth URL + `CancelledError` on
  shutdown). The tests are now **non-interactive** (`authenticate(allow_interactive=False)` —
  consent only happens via the dedicated "Connect/Authorize" button) and **time-bounded** (a
  shared `_run_conn_test` wraps the executor call in `asyncio.wait_for`, returning a friendly
  timeout message instead of hanging). `GA4Client.authenticate` / `GSCClient.authenticate` now
  accept `allow_interactive`.
- Full‑application audit pass (correctness, security, performance) — applied across all parts:
  - **Duplicate detector**: title/meta‑description now coerced via `str(...)` before
    `.strip().lower()` so non‑string values from the DB (e.g. numeric titles) can’t crash
    the analysis.
  - **Internal‑link score (PageRank)**: repeated nav/footer links between the same two pages
    are now de‑duplicated to a single `(from, to)` edge before the power iteration, so the
    score is no longer artificially inflated by links that appear on every page (the
    docstring promised this dedup but it wasn’t implemented).
  - **Near‑duplicate (LSH)**: auto‑corrects the band count so the candidate guarantee
    actually holds (`bands > max_distance`, and `bits % bands == 0`) instead of silently
    missing similar pairs; asserts the invariant.
  - **SimHash**: skipped (emit empty fingerprint) for very short text (< 10 words), whose
    fingerprint is unstable and produced false near‑duplicate matches.
  - **PageSpeed API**: the API key is now passed via `params=` (never formatted into a URL
    string that could be logged), error bodies that aren’t valid JSON no longer raise, and
    transient failures (429/5xx/timeout) get a short exponential‑backoff retry.
  - **robots.txt**: downloaded with a streaming 2 MB size cap so a huge/compressed response
    can’t exhaust memory.
  - **Google OAuth** (`google_auth`): token filenames are scope‑aware and a saved token that
    doesn’t cover the requested scopes triggers re‑consent; the interactive browser flow is
    gated by `SCT_NONINTERACTIVE` (set for the background crawl process) so it can never hang
    a non‑interactive run waiting for consent.
  - **Resource status**: `status_code` coerced from string before the `>= 400` check, so
    broken resources stored as text are still counted.
  - **GSC pagination**: `rowLimit` clamped to `max(1, …)` to avoid a zero/negative limit on
    the final page.
  - **Web UI**: `/api/google/upload` rejects payloads > 64 KB (client‑secret files are tiny);
    `/api/test/ga4` checks `client_secret.json` exists (parity with the GSC test); the
    “Download all (ZIP)” build runs in a thread executor so large archives don’t block the
    event loop; XML export has a hard per‑file safety cap inside `XMLExporter`; and
    `build_report_from_json` skips files larger than 500 MB instead of loading them into RAM.
- Large‑crawl output blowup & post‑run hang (found on an unlimited 11,937‑page crawl that
  produced a **1.7 GB `complete_audit.json`** and **1.15 GB `links.xml`**):
  - `complete_audit.json` no longer embeds the huge raw arrays (links/images/headings — here
    ~990k/303k/225k rows) by default; those live in CSV/Excel/XML. The JSON keeps pages +
    all analyses + summaries. Set `output.json_full: true` to embed everything.
  - The HTML/PDF report is now built from in‑memory data instead of **re‑loading the
    multi‑GB JSON** (`json.load` of 1.7 GB was the “preparing reports forever” hang). The
    report never needed the raw arrays — only pages + analyses.
  - XML export is capped per dataset via `output.xml_max_rows` (default 50,000; 0 = no cap)
    so `links.xml`/`images.xml` can’t reach gigabytes, **and XML is now off by default**
    (it duplicates the CSV data — no extra information; add it back per‑run if you need it).
    Net effect on the 11,937‑page example: total output drops from ~3 GB to a few hundred
    MB, dominated by the genuine link‑graph CSV (`all_links.csv`) — no information lost.
  - The web UI’s **Explore** and **Report‑rebuild** endpoints now refuse to load an audit
    JSON larger than ~300 MB (returns a clear message pointing to the CSV) instead of
    hanging the server on legacy huge files.
- Deep audit round (security/perf/correctness):
  - **Security:** the AI advisor now validates `base_url` against the SSRF guard before
    sending the request (and the Bearer/API key) — internal/loopback/metadata endpoints are
    rejected unless `integrations.ai.allow_private` is set (for local models like Ollama).
    The **Gemini** key moved from the URL query string to the `x-goog-api-key` header (keys
    in URLs leak into proxy/server logs). The crawl **start URL** is now SSRF-checked in
    `configure_target_site` (this also covers the initial `robots.txt` fetch, which ran
    before the per-URL guard).
  - **Performance:** table columns are cached instead of running `PRAGMA table_info` ~4×
    per saved page; `redirect_analyzer` de-duplicates shared internal hops and dropped an
    O(n²) `hop not in list` fallback; per-page `import` of the custom/resource extractors
    moved to module top; `normalize_url`'s tracking-param set hoisted to a module constant.
  - **Correctness/log:** `status_codes` are now tallied **once per saved page** instead of
    on every redirect hop and retried attempt, so the crawl summary's status distribution
    matches the page count (no more 523-vs-512). Broken-link results (4xx/5xx/404-with-
    inlinks) are now logged. In `both` report mode the generic html/pdf download no longer
    arbitrarily resolves to a client/expert variant. AI response parsing hardened against
    empty/malformed completions.
- Post-crawl review (500-page audit): `images_no_alt.csv` / `images_no_dimensions.csv`
  were capped at 100 rows (the analyzer's report/JSON sample leaked into the CSV); the CSV
  exporter now builds the **full** lists from the raw images so the actionable files are
  complete. The crawl log now surfaces **transient fetch errors** (network/timeout retries)
  as a WARNING with the count — previously 43 retried errors were invisible and the UI
  diagnostics showed 0 warnings. The external-links summary now prints
  `OK / Blocked (401/403/429) / Broken` separately instead of folding blocked links into
  "Working". And `run.log` is no longer bloated by tqdm progress bars: the progress bar is
  disabled when running under the web UI (subprocess, `SCT_PROGRESS_FILE` set) or any
  non-TTY, so the per-job log stays clean (the UI uses `progress.json` for live progress).
- Code audit round 2 (deferred items): DB-backed crawler getters (`get_pages`/`get_links`/
  …) are now memoized per run — after a crawl the DB is stable, so they build the
  materialized list once and hand each caller a fresh shallow copy instead of re-running
  `SELECT *` + rebuilding dicts in every phase (analysis/export/integrations/report).
  Per-job log summary (`_summarize_run_log`) counts errors/warnings/critical by the actual
  log level (`| LEVEL |`) instead of substring-matching the words anywhere in the text (an
  INFO line mentioning "ERROR" no longer inflates the error count). Intermediate redirect
  responses in `HTTPClient` are now closed before the next hop (with `stream=True` an
  unconsumed redirect kept the connection open). Compare mode resets monitoring per site
  and writes each site's `metrics.json` into its own folder (multi-site runs no longer
  conflate counters/timings).
- Code audit round: `broken_links` 404-with-inlinks now uses a one-pass index + normalized
  matching (was O(n²) and missed normalized targets); SSRF guard added to `logo_url` before
  PDF rendering (headless browser fetched it) and to redirect targets in `HTTPClient` (sync
  path); PageSpeed API key passed via env, no longer written to the per-job config file;
  custom-extraction skips `str(soup)` unless a regex rule needs it; SSE stream no longer
  hangs for unknown jobs; `job_id` format validation + download path containment under the
  jobs dir; `from typing import Any` added to webapp/app.py.
- Manual stop produced no downloadable results on Windows: the UI sent `CTRL_BREAK_EVENT`
  (SIGBREAK) but the crawler only caught SIGINT/SIGTERM, so the process died abruptly
  before exporting. The crawler now also catches SIGBREAK; on manual stop it skips the
  slow external-link check and HTML/PDF report, exports the partial CSV/JSON/Excel, and
  exits cleanly so the download buttons appear (the report can be rebuilt afterwards).
- UI looked "stuck" after the crawl phase: the timer kept ticking with frozen counters
  during the (silent) post-crawl phases (external links, export). The crawler now emits
  phase progress (`analyzing` / `checking_external_links` / `exporting`) and a final
  `complete` / `partial_max_pages` status, so the monitor shows the live phase, the timer
  stops when the job actually finishes, and the results panel appears. Download buttons
  now carry an explicit "Download" label.
- Unlimited crawl (`max_pages=0`, the "All" option) broke every worker with
  `TypeError: bool() undefined when iterable == total == None`: `if self.progress_bar:`
  invoked tqdm's `__bool__` on a `total=None` bar. Now uses `is not None`. The crawl was
  actually fetching pages but progress never updated (stuck at "starting").
- External-link checker reported bot-blocked sites as broken: `401/403/429` (e.g. every
  twitter.com share link → 403) were counted as broken. Now classified as "blocked", not
  "broken" (real broken count dropped from 512 → 5 on a sample crawl).
- Crawl order ignored the homepage and link discovery: all sitemap URLs were enqueued
  before the start URL, so with a page limit the crawler only fetched sitemap pages
  (depth 0) and never crawled the homepage or followed links. Now the homepage + BFS link
  graph are crawled first, with sitemap URLs pulled as deferred seeds afterward.
- PDF generation failed inside the crawl's asyncio loop (`Playwright Sync API inside the
  asyncio loop`) — now runs in a worker thread.
- Report/Excel/JSON deliverables are named with site + date-time
  (`audit_<slug>_<ts>.xlsx`, `report_<slug>_<ts>.html/.pdf`).
- Every async fetch crashed with `TypeError: event() got multiple values for argument
  'status'` (pre-existing) — `event()` calls and `span()` reserved-attr collisions fixed
  and hardened, so 0-crawled/all-failed runs no longer happen.
- `aiohttp` failed to decode brotli (`Can not decode content-encoding: br`) — the crawler
  no longer advertises `br` in `Accept-Encoding` (uses gzip/deflate).
- Resume snapshot rewrote the full queue too often (heavy I/O) — larger interval and
  delta-only visited writes.
- Analyzers crashed on database-backed dict rows (default audit run) — now dict/object safe.
- Async crawler could hang at `queue.join()` when `max_pages` was reached with items still
  queued — termination reworked (no hang).
- Re-runs duplicated links/images/headings/schema/redirects — now delete-then-insert per page.
- Microdata Schema.org entries were never field-validated — now validated.
- `sitemap_diff` received only the last sitemap's URLs — now accumulated and persisted.
- Redirect handling: robots checked on redirect targets, unified sync/async semantics,
  chains ordered by following links, `internal_redirects` populated.
- Excel export no longer dropped silently on long strings or null status codes.
- CSV/Excel formula-injection neutralization for client-facing exports.
- `normalize_url` resolves `.`/`..` segments; `is_internal_url` strips only a leading `www.`.
- gzip sitemap decompression is now size-capped (decompression-bomb protection).
- Graceful Ctrl+C / SIGTERM for the async crawler (saves state).
- `format_duration` no longer renders `60s`; restricted DB JSON decoding to known columns;
  `defusedxml` confirmed in requirements; GSC token written with `0600`.

### Changed
- Added detailed observability and `metrics.json` output.
- Improved `--analyze-only` behavior for database-backed analysis.
- Open-source roadmap and project governance files.
- Corrected overstated audit claims in docs (23 issue types, not "29+").
