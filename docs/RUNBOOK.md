# SCT Incident Runbook

> Operator-facing incident response for SCT (Simple Crawler Tool) v1.13. Each
> scenario follows a **Symptoms → Diagnosis → Fix** structure with concrete
> shell commands. Where useful, the expected log line you should see (the
> "screenshot of log") is shown verbatim so you can match against your own
> output.
>
> Companion docs: [README.md](../README.md) · [SECURITY.md](../SECURITY.md) ·
> [CHANGELOG.md](../CHANGELOG.md) · [docs/OAUTH_SETUP.md](OAUTH_SETUP.md) ·
> [docs/USER_GUIDE.md](USER_GUIDE.md).

---

## Table of contents

1. [Google OAuth `invalid_grant` (7-day Testing-mode expiry)](#1-google-oauth-invalid_grant-7-day-testing-mode-expiry)
2. [Local auth token missing or wrong permissions → 401 on every API call](#2-local-auth-token-missing-or-wrong-permissions--401-on-every-api-call)
3. [`/readyz` returns 503 (filesystem write-probe failing)](#3-readyz-returns-503-filesystem-write-probe-failing)
4. [Port 8000 already in use](#4-port-8000-already-in-use)
5. [Phase 2 button does nothing](#5-phase-2-button-does-nothing)
6. [`database is locked` after the v1.10 `busy_timeout` fix](#6-database-is-locked-after-the-v110-busy_timeout-fix)
7. [Disk full — cleaning `webapp_jobs/` safely](#7-disk-full--cleaning-webapp_jobs-safely)
8. [CSP / security-headers complaint from a downstream scanner](#8-csp--security-headers-complaint-from-a-downstream-scanner)

---

## 1. Google OAuth `invalid_grant` (7-day Testing-mode expiry)

### Symptoms

- A previously-working GSC or GA4 connector suddenly stops fetching data.
- Job log shows, mid-crawl or during the integrations phase:

  ```text
  google.auth.exceptions.RefreshError: ('invalid_grant: Token has been
  expired or revoked.', {'error': 'invalid_grant',
  'error_description': 'Token has been expired or revoked.'})
  ```

- The **Google** readiness chip on the main page is amber/red and shows
  `Google (منتهٍ — أعد التفويض)` / `Google (expired — re-consent)`.
- `GET /api/google/status` returns `{"expired": true, ...}` (this flag was
  added in v1.06 specifically so the failure is visible *before* the crawl
  starts, not 40 minutes in).

### Diagnosis

Google's OAuth consent screen has a **Testing** mode whose refresh tokens
are revoked every **7 days**. This is a Google policy, not an SCT bug —
removing it requires putting the OAuth client through Google's verification
process for sensitive scopes. SCT's `_probe_token_expired` helper actively
calls `creds.refresh(Request())` on each saved token at status time, so an
expired refresh token surfaces as an explicit `expired: true` rather than
a silent failure during the crawl.

Probe both tokens manually from the host:

```bash
# Linux / macOS / Git Bash
curl -s -H "Authorization: Bearer $(cat ~/.sct/local_token)" \
  http://127.0.0.1:8000/api/google/status | python -m json.tool
```

```powershell
# PowerShell
$token = Get-Content "$env:USERPROFILE\.sct\local_token"
Invoke-RestMethod -Headers @{ Authorization = "Bearer $token" } `
  http://127.0.0.1:8000/api/google/status
```

Expected payload on an expired token:

```json
{
  "configured": true,
  "has_token_gsc": true,
  "has_token_ga4": true,
  "expired": true,
  "client_secret_present": true
}
```

### Fix

1. Open the main page in the browser. The **Integrations** tab will show
   `وافق بحسابي` / `Authorize with my account` next to the expired chip.
2. Click it. Because v1.06 keeps the `client_secret` saved across re-consents,
   you only re-approve in the browser — you do **not** need to re-upload the
   `client_secret.json`.
3. After the browser flow completes, re-probe `/api/google/status`. You
   should now see `"expired": false`.
4. Restart the crawl (or, if mid-job, stop and start a fresh one — Google
   integration data fetched before the expiry is preserved in the job's
   `output/csv/`).

If `client_secret_present` is `false` in the status payload, follow
[docs/OAUTH_SETUP.md](OAUTH_SETUP.md) to upload the client secret first,
then re-consent.

---

## 2. Local auth token missing or wrong permissions → 401 on every API call

### Symptoms

- Every `curl` / scripted call returns:

  ```text
  HTTP/1.1 401 Unauthorized
  content-type: application/json

  {"error": "unauthorized"}
  ```

- The browser UI still works (it loads `/` which is exempt and the inline
  `fetch` patch injects the token automatically).
- Scripts that previously worked break after a fresh install, a `chmod`
  sweep, or copying the install to a new host.

### Diagnosis

v1.10 introduced a per-install auth token written to `~/.sct/local_token`
with mode `0600` on first server start. Every `/api/*` route (except
`/health` and `/readyz`) requires it via `Authorization: Bearer <token>`
or `?token=<token>`. Comparison is constant-time via `hmac.compare_digest`.

Confirm the file exists and is readable by the user running the server:

```bash
# Linux / macOS / Git Bash
ls -la ~/.sct/local_token
cat ~/.sct/local_token
```

```powershell
# PowerShell
Get-Item "$env:USERPROFILE\.sct\local_token" | Format-List
Get-Content "$env:USERPROFILE\.sct\local_token"
```

Expected on a healthy install:

```text
-rw------- 1 sct sct 64 Jun 20 09:12 /home/sct/.sct/local_token
```

Common bad states:

- File missing entirely (deleted, never created because server crashed at
  boot).
- File world-readable (`-rw-r--r--`) after a `chmod -R 644` sweep — not a
  401 cause by itself, but you should still tighten it.
- File owned by `root` after running the server once via `sudo` — the
  current user can't read it.
- Two SCT installs on the same host writing to the same `~/.sct/local_token`
  with different tokens (last one wins).

### Fix

Regenerate by simply deleting and restarting the server — it writes a fresh
token on next boot:

```bash
rm -f ~/.sct/local_token
chmod 700 ~/.sct
./start.sh           # or START.bat on Windows, START.ps1 on PowerShell
chmod 600 ~/.sct/local_token
cat ~/.sct/local_token   # copy into your script's Authorization header
```

```powershell
Remove-Item "$env:USERPROFILE\.sct\local_token" -Force
# server will recreate it on next boot
.\START.bat
icacls "$env:USERPROFILE\.sct\local_token" /inheritance:r /grant:r "${env:USERNAME}:F"
```

After regenerating, **every existing script needs the new token value** —
the old one will not work even from localhost.

If you need to keep the same token across restarts (e.g. baked into a
deployment automation script), back it up before deleting:

```bash
cp ~/.sct/local_token ~/.sct/local_token.bak
# regenerate, then if needed:
cp ~/.sct/local_token.bak ~/.sct/local_token
chmod 600 ~/.sct/local_token
```

---

## 3. `/readyz` returns 503 (filesystem write-probe failing)

### Symptoms

- `GET /readyz` returns:

  ```text
  HTTP/1.1 503 Service Unavailable
  content-type: application/json

  {"status": "not_ready", "error": "cannot write to webapp_jobs/"}
  ```

- `GET /health` still returns `{"status": "ok"}` (liveness is unaffected).
- Orchestrators (Kubernetes, Docker Swarm, docker-compose with healthcheck)
  mark the container as `unhealthy` and may restart it.
- New crawls fail to start; existing job folders may or may not be writable.

### Diagnosis

`/readyz` (added in v1.10 as B1.c) probes a small write to `webapp_jobs/`
on every call to confirm the app can actually serve work. The probe creates
and deletes a tiny temp file inside `webapp_jobs/`. Any of these failures
trips the 503:

- `webapp_jobs/` doesn't exist (deleted by a cleanup cron, never created
  on a fresh checkout).
- Permission denied (container running as `sct` user but the host-mounted
  volume is owned by `root`).
- Filesystem read-only (disk failure, btrfs in `ro` mode after an error,
  bind-mount with `:ro`).
- Disk full (`ENOSPC`) — see also [Scenario 7](#7-disk-full--cleaning-webapp_jobs-safely).
- Quota exceeded.

Inspect from the host:

```bash
# Linux / macOS / Git Bash — does the dir exist? Who owns it?
ls -la ./webapp_jobs/ | head
stat ./webapp_jobs/
# Can the current user actually write?
touch ./webapp_jobs/.readyz_manual_test && rm ./webapp_jobs/.readyz_manual_test \
  && echo "write OK" || echo "write FAILED"
# Free space + inodes
df -h ./webapp_jobs/
df -i ./webapp_jobs/
```

```powershell
# PowerShell
Get-Item .\webapp_jobs\ | Format-List
Get-Acl .\webapp_jobs\ | Format-List
New-Item -Path .\webapp_jobs\.readyz_manual_test -ItemType File -Force | Out-Null
Remove-Item .\webapp_jobs\.readyz_manual_test
Get-PSDrive C | Select-Object Used, Free
```

Expected log line in the server output when the probe fails:

```text
[ERROR] readyz: write probe failed: [Errno 13] Permission denied:
  'webapp_jobs/.readyz_probe_a1b2c3'
```

### Fix

Recreate the directory and fix ownership / mode:

```bash
# Bare metal / VM
mkdir -p ./webapp_jobs
chown -R "$(id -u):$(id -g)" ./webapp_jobs
chmod 755 ./webapp_jobs

# Docker — the image runs as the non-root `sct` user (v1.09 hardening)
docker compose down
sudo chown -R 1000:1000 ./webapp_jobs   # uid:gid of the sct user
docker compose up -d
```

```powershell
# PowerShell
New-Item -ItemType Directory -Path .\webapp_jobs -Force | Out-Null
icacls .\webapp_jobs /grant "${env:USERNAME}:(OI)(CI)F"
```

Re-probe:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/readyz
# expect: 200
```

If `/readyz` still returns 503 after the directory is writable, check the
server log for the underlying `OSError` and treat it as a filesystem-layer
incident (read-only mount, full disk, quota, hardware).

---

## 4. Port 8000 already in use

### Symptoms

- `START.bat` / `START.ps1` / `./start.sh` exits early with:

  ```text
  [ERROR] Address already in use: 127.0.0.1:8000
  uvicorn.error: [Errno 98] Address already in use
  ```

  (Errno is `48` on macOS, `10048` on Windows.)

- Browser hits `http://127.0.0.1:8000` and sees a stale older instance, a
  completely unrelated app (Jenkins, Jupyter, Airflow, another SCT), or just
  `Connection refused` after the launcher exits.

### Diagnosis

Identify the process holding the port. `STOP.bat` automates this on
Windows by calling `netstat -ano | findstr :8000` and then
`taskkill /PID <pid> /F`. The manual equivalents:

```bash
# Linux / macOS — lsof is the cleanest
lsof -iTCP:8000 -sTCP:LISTEN -P -n

# Same thing via ss (modern Linux, faster than lsof on busy hosts)
ss -lptn 'sport = :8000'

# fuser as a last resort
fuser -n tcp 8000
```

Expected output:

```text
COMMAND   PID  USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
python   42117 sct   12u  IPv4 0xabc      0t0  TCP  127.0.0.1:8000 (LISTEN)
```

```powershell
# PowerShell — netstat (works on all Windows versions)
netstat -ano | Select-String ":8000\s.*LISTENING"

# Or the cmdlet form
Get-NetTCPConnection -LocalPort 8000 -State Listen |
  Select-Object LocalAddress, LocalPort, OwningProcess
Get-Process -Id (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess
```

Resource Monitor (built into Windows) is an option for users who prefer a
GUI: Win + R → `resmon` → **Network** tab → **Listening Ports** → sort by
`Port`, look for `8000`, note the PID under `Image`.

### Fix

`STOP.bat` (Windows) does this automatically:

```text
:: STOP.bat (paraphrased)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000.*LISTENING') do (
    taskkill /PID %%a /F
)
```

Manual equivalents:

```bash
# Linux / macOS
kill $(lsof -t -iTCP:8000 -sTCP:LISTEN)
# escalate if it refuses to die
kill -9 $(lsof -t -iTCP:8000 -sTCP:LISTEN)
```

```powershell
# PowerShell
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess -Force
```

If the port is held by a process you don't want to kill (a real Jenkins,
a Jupyter you care about), run SCT on a different port:

```bash
python webapp/run.py --port 8765
```

```powershell
python webapp\run.py --port 8765
```

After SCT is up on the new port, also remember to update any saved curl
scripts and the browser bookmark.

---

## 5. Phase 2 button does nothing

### Symptoms

- After Phase 1 finishes, the amber **Discovered URLs not crawled in Phase 1**
  panel is visible but clicking **🔁 Run Phase 2 (crawl deferred)** silently
  fails or returns a non-2xx from `POST /api/jobs/<id>/phase2`.
- Possible API responses (all 400):

  ```json
  {"error": "deferred_csv_missing"}
  {"error": "active_job_running"}
  {"error": "config_missing"}
  {"error": "job_not_found"}
  ```

### Diagnosis

`start_phase2(job_id)` in `webapp/job_runner.py` validates four
preconditions before spawning the subprocess. Each one maps to a distinct
error reason:

| Reason | Meaning | Where to look |
|---|---|---|
| `job_not_found` | `webapp_jobs/<id>/` doesn't exist | Job was deleted, or the wrong id is passed |
| `config_missing` | `webapp_jobs/<id>/config.yaml` not written | Job didn't reach the post-Phase-1 export step (probably crashed) |
| `deferred_csv_missing` | `output/.../csv/deferred_urls.csv` not found | Either the classifier deferred nothing (good — Phase 2 has nothing to do), or v1.09's "search newest sibling output dir" couldn't find a hit |
| `active_job_running` | Another job process is alive | A reentrancy guard added in v1.09 (B12) — a placeholder `_procs[job_id] = None` is inserted under the lock the moment `start_phase2` enters |

Inspect:

```bash
# Find the deferred CSV the API is hunting for
ls -la webapp_jobs/<job_id>/output/*/csv/deferred_urls.csv 2>/dev/null
# Confirm the config was written
ls -la webapp_jobs/<job_id>/config.yaml
# Confirm no other job is mid-flight
curl -s -H "Authorization: Bearer $(cat ~/.sct/local_token)" \
  http://127.0.0.1:8000/api/jobs | python -m json.tool | grep -E '"status"|"id"'
```

```powershell
Get-ChildItem .\webapp_jobs\<job_id>\output\*\csv\deferred_urls.csv -ErrorAction SilentlyContinue
Get-Item .\webapp_jobs\<job_id>\config.yaml
```

Expected when Phase 2 is *correctly* a no-op (no URLs were deferred):

```text
deferred_urls.csv:   (zero bytes, or just the header row)
audit.json deferred_summary: {"pagination_deep": 0, "redirect_wrapper": 0, "filter_combination": 0}
```

### Fix

By cause:

- **`deferred_csv_missing` and nothing was deferred** — there is no Phase 2
  to run. This is normal for small sites or sites without paginated /
  filtered URLs. The UI panel only shows non-zero kinds; if all three are
  zero, just don't click the button.
- **`deferred_csv_missing` but the CSV is clearly there** — check
  `crawl.timestamped_folder` in the job's `config.yaml`. v1.09 fixed the
  "newest sibling output dir" search, but if the directory tree was hand-
  rearranged the search will miss. Move the CSV up one level if necessary
  (`mv webapp_jobs/<id>/output/<ts>/csv/deferred_urls.csv webapp_jobs/<id>/output/csv/`).
- **`active_job_running`** — look at the running PIDs:

  ```bash
  ps -ef | grep -E 'main\.py.*--phase2|main\.py.*--mode' | grep -v grep
  ```

  ```powershell
  Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match "main\.py" } |
    Select-Object ProcessId, CommandLine
  ```

  If the process is stuck, stop it via the UI (recommended) or kill the
  PID. The placeholder under `_procs[job_id]` will clear on the next API
  call.
- **`config_missing`** — Phase 1 didn't finish cleanly. Inspect the job log
  for the last error. Phase 2 requires Phase 1's `config.yaml` to inherit
  every setting (start URL, depth, integrations); without it we can't
  spawn a coherent subprocess. Re-run as a fresh Phase 1 job.

---

## 6. `database is locked` after the v1.10 `busy_timeout` fix

### Symptoms

- Crawl log shows:

  ```text
  sqlite3.OperationalError: database is locked
  ```

- v1.10 (C1.M-4) added `PRAGMA busy_timeout = 5000` on every connection,
  on top of the existing `sqlite3.connect(timeout=30.0, ...)`. That
  combination handles almost all contention. If you still see the error
  after upgrading, it falls into one of the narrow residual cases below.

### Diagnosis

The 5-second `busy_timeout` PRAGMA applies inside every nested write — but
SQLite will *still* surface `database is locked` when:

- **A single write transaction holds the lock longer than 5 seconds.** The
  most common culprit is a large analytical write (e.g. `VACUUM`, big
  `INSERT … SELECT …`, an indexed `UPDATE` over a multi-GB table).
- **An external process has the DB open exclusively.** `sqlite3` shell open
  with `BEGIN EXCLUSIVE`, a backup tool with a write lock, or DB Browser
  for SQLite with an unsaved edit in the editor.
- **The `sct.db` is on a network filesystem** (NFS, SMB, or a cloud-mounted
  drive). SQLite's locking semantics are *not* reliable on most network
  filesystems — the `busy_timeout` won't save you.
- **Two SCT processes pointing at the same DB file.** A common foot-gun
  when copying a `webapp_jobs/<id>/` while a job is running, then starting
  a second crawl that reads the copy with the wrong relative path.

Inspect:

```bash
# Who has the file open?
lsof webapp_jobs/<job_id>/output/state/sct.db

# Is it on a network mount?
df -T webapp_jobs/<job_id>/output/state/sct.db
mount | grep "$(stat -c '%m' webapp_jobs/<job_id>/output/state/sct.db)"

# Is journal_mode wal as expected? (recommended; reduces writer/reader contention)
sqlite3 webapp_jobs/<job_id>/output/state/sct.db "PRAGMA journal_mode;"
# expect: wal
```

```powershell
# Who has the file open? (needs Sysinternals handle.exe)
handle.exe webapp_jobs\<job_id>\output\state\sct.db
```

### Fix

By cause:

- **Long-running PRAGMA write or `VACUUM`.** Don't run `VACUUM` during a
  crawl. If a `VACUUM` is *required* (large DB, lots of churn), stop the
  job first, run it, then resume.
- **External DB tool holding a lock.** Close DB Browser for SQLite, exit
  any `sqlite3` shell with `.quit`, stop the backup tool. Re-run the
  failing operation.
- **Network filesystem.** Move `webapp_jobs/` onto a local disk. There is
  no reliable software-side workaround for this — it's an OS/FS-level
  limitation.
- **Two SCT processes on the same DB.** Identify them via `lsof` /
  `handle.exe` (see above) and stop the duplicate.
- **Hung writer.** Last resort, after confirming nothing else is using it:

  ```bash
  cd webapp_jobs/<job_id>/output/state
  ls -la sct.db*
  # If you see sct.db-wal and sct.db-shm, a writer crashed mid-transaction.
  # Re-open the DB to roll forward the WAL:
  sqlite3 sct.db "PRAGMA wal_checkpoint(TRUNCATE);"
  ```

- **If the DB is genuinely corrupt** (cosmic ray, hardware fault):

  ```bash
  sqlite3 sct.db "PRAGMA integrity_check;"
  # If output is not "ok", recover what you can:
  sqlite3 sct.db ".dump" > dump.sql
  mv sct.db sct.db.broken
  sqlite3 sct.db < dump.sql
  ```

---

## 7. Disk full — cleaning `webapp_jobs/` safely

### Symptoms

- New crawls fail with `[Errno 28] No space left on device` (`ENOSPC`).
- `/readyz` returns 503 — see [Scenario 3](#3-readyz-returns-503-filesystem-write-probe-failing).
- Logs show `OSError: [Errno 28]` from the SQLite writer, the CSV exporter,
  or the JSON exporter.
- A large fraction of disk is held by `webapp_jobs/<job_id>/output/*.csv`
  and per-job SQLite databases.

### Diagnosis

Each job folder under `webapp_jobs/<job_id>/` carries the full log, the
per-job SQLite state DB, all CSV/JSON exports, and (if generated) the
HTML/PDF/Excel report and the XML sitemap folder. Long-running production
installs accumulate dozens of GB across hundreds of jobs.

```bash
# Top space consumers under webapp_jobs/
du -sh webapp_jobs/* 2>/dev/null | sort -rh | head -20

# Total
du -sh webapp_jobs/

# Free space + inodes (very full disks usually hit inode limits first
# because of the many small CSVs per job)
df -h .
df -i .
```

```powershell
Get-ChildItem .\webapp_jobs -Directory |
  Select-Object Name, @{Name='SizeMB';Expression={
    [math]::Round((Get-ChildItem $_.FullName -Recurse -ErrorAction SilentlyContinue |
                   Measure-Object -Property Length -Sum).Sum / 1MB, 1)
  }} | Sort-Object SizeMB -Descending | Select-Object -First 20
```

### Fix

**Preferred — use the existing endpoint** (added in v1.01). This honors
the safety guards baked into the server: the currently-running job is
never deleted, invalid IDs are rejected, paths are resolved and confirmed
inside `webapp_jobs/` so deletion can't escape the directory.

```bash
# Delete ALL jobs except the active one (closest equivalent of "free up disk")
curl -X POST -H "Authorization: Bearer $(cat ~/.sct/local_token)" \
  http://127.0.0.1:8000/api/jobs/delete-all

# Or selectively delete one job
curl -X POST -H "Authorization: Bearer $(cat ~/.sct/local_token)" \
  http://127.0.0.1:8000/api/jobs/20260620_141500_abc123/delete
```

```powershell
$token = Get-Content "$env:USERPROFILE\.sct\local_token"
Invoke-RestMethod -Method Post -Headers @{ Authorization = "Bearer $token" } `
  http://127.0.0.1:8000/api/jobs/delete-all

Invoke-RestMethod -Method Post -Headers @{ Authorization = "Bearer $token" } `
  http://127.0.0.1:8000/api/jobs/20260620_141500_abc123/delete
```

The UI equivalents — **🧹 Delete all (except active)** and per-row
**🗑️ Delete** in the Recent jobs table — call exactly the same endpoints.

**Fallback — direct shell delete.** Use this only when the server isn't
reachable (e.g. you can't start it because the disk is too full to even
boot). **Never** delete the folder for a job whose subprocess is still
running; you will corrupt the SQLite WAL and leave the worker writing into
a deleted inode. Stop the server first.

```bash
# Stop the server (use STOP.bat on Windows, or kill the uvicorn PID)
./STOP.bat 2>/dev/null || pkill -f "webapp/run.py"

# Verify nothing is left holding a webapp_jobs file
lsof +D ./webapp_jobs 2>/dev/null

# Delete jobs older than 30 days
find ./webapp_jobs -mindepth 1 -maxdepth 1 -type d -mtime +30 -print -exec rm -rf {} +

# Or nuke everything
rm -rf ./webapp_jobs/*
```

```powershell
.\STOP.bat
Get-ChildItem .\webapp_jobs -Directory |
  Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
  Remove-Item -Recurse -Force
```

After cleanup, `mkdir -p webapp_jobs && chmod 755 webapp_jobs` if you blew
the directory away entirely, then restart the server.

---

## 8. CSP / security-headers complaint from a downstream scanner

### Symptoms

A vulnerability scanner (Nessus, Qualys, ZAP baseline, Burp, Mozilla
Observatory, securityheaders.com) flags SCT as missing or weak on one or
more of:

- `Content-Security-Policy`
- `Strict-Transport-Security` (HSTS)
- `X-Frame-Options` / `frame-ancestors`
- `Referrer-Policy`
- `Permissions-Policy`
- `Cross-Origin-*` isolation headers

### Diagnosis — what SCT is and isn't

**SCT is not a hardened public web app.** It's a single-user, local-only
audit tool whose UI is intended to run on `http://127.0.0.1:8000` for the
operator's own machine. The codebase intentionally trades public-web
hardening for local-developer ergonomics. Specifically:

- **It binds to localhost by default.** The token wall (Scenario 2) means
  that even on `0.0.0.0` an unauthenticated attacker cannot drive the API.
  The CSRF Origin guard (v1.09) rejects browser-cross-origin state-changing
  requests. Rate limiting (v1.10 B1.a) protects `/api/start` (10/hour) and
  the rest of `/api/*` (120/min).
- **It does not serve HTTPS itself.** That means no HSTS — there is no
  TLS layer for HSTS to assert. If you front SCT with a reverse proxy
  (nginx, Caddy, Traefik) for remote access, *that proxy* is the right
  place to set HSTS, full-strength CSP, and certificate pinning.
- **The HTML UI inlines CSS and JS** (templates under
  `webapp/templates/` and `webapp/static/`). A strict
  `default-src 'self'` CSP would break the `<script>` blocks in `index.html`,
  `job.html`, `graph.html`, `board.html`. The graph view also draws onto
  a `<canvas>` with a small inlined force-directed simulation.
- **It does set the auth token wall on every state-changing endpoint and on
  every `/api/*` read.** It does run a CSRF Origin guard. It does enforce
  rate limits. It does return correlation `X-Request-ID` headers on every
  response. It does whitelist SQL table names. It does run SSRF checks
  against `is_safe_remote_url` on every outbound URL including JS-rendering
  navigations and HEAD redirects.

So a scanner complaint about missing CSP/HSTS on
`http://127.0.0.1:8000` is a **scanner-vs-design mismatch**, not a
vulnerability — but the right response depends on whether you're deploying
SCT behind a proxy.

### Fix

**If SCT is local-only on `127.0.0.1`** (the default):

- Acknowledge the scanner finding as out-of-scope. Cite SECURITY.md and
  this runbook section. The threat model is "operator on their own
  laptop"; CSP buys nothing here because there's no third-party content
  surface and the token wall already blocks the attacker the CSP would
  be defending against.
- Confirm the actually-relevant guards are working:

  ```bash
  curl -i http://127.0.0.1:8000/health
  # expect: X-Request-ID: <12 chars>

  curl -i -X POST http://127.0.0.1:8000/api/start
  # expect: HTTP/1.1 401 Unauthorized

  curl -i -H "Origin: https://evil.example/" \
    -H "Authorization: Bearer $(cat ~/.sct/local_token)" \
    -X POST http://127.0.0.1:8000/api/jobs/delete-all
  # expect: HTTP/1.1 403 Forbidden  (CSRF origin guard)
  ```

**If you've exposed SCT behind a reverse proxy** (not the supported
deployment, but it happens):

- Put a real proxy in front (nginx, Caddy). Have it terminate TLS, set
  HSTS, set a CSP appropriate for the inlined scripts (typically
  `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src
  'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self';
  frame-ancestors 'none'`).
- Add `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Permissions-Policy: ()` at the proxy.
- Keep the SCT token wall on. Do not disable it because "the proxy handles
  auth now" — defense in depth is the whole point.
- Restrict the proxy to specific source IPs / your VPN; do not put SCT on
  the open internet. The crawler subprocess fans outbound and writes
  freely to `webapp_jobs/` — even with the token wall, exposing this to
  the public internet is not the threat model the code was designed for.

If a specific downstream audit policy requires SCT itself to emit these
headers (e.g. an internal compliance regime that forbids "any app without
CSP"), file the request in the project tracker — adding a fixed CSP /
HSTS / referrer policy to the FastAPI middleware is straightforward but
must be done carefully so the existing inlined `<script>` blocks
continue to load. It has been considered as a backlog item but is not
shipped as of v1.13.

---

## Appendix: useful one-liners

```bash
# What version is the running server?
curl -s http://127.0.0.1:8000/health
# (version is also in the page footer of `/` and in every audit.json _meta.version)

# Tail the live log for a specific job
tail -F webapp_jobs/<job_id>/job.log

# How many jobs do I have, and how much disk?
ls webapp_jobs/ | wc -l && du -sh webapp_jobs/

# Run the test suite to confirm a clean install
python -B -m unittest discover -s tests
# expect: 92/92 pass on v1.13
```

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Get-Content .\webapp_jobs\<job_id>\job.log -Wait -Tail 50
(Get-ChildItem .\webapp_jobs -Directory).Count
python -B -m unittest discover -s tests
```

For anything not covered here, check `CHANGELOG.md` for the relevant
version's release notes — most operator-visible behaviors are documented
inline with the fix that introduced them.
