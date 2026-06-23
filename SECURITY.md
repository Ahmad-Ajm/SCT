# Security Policy

## Reporting a Vulnerability

Please **do not** open a public issue for security-sensitive findings. Use one of:

1. **GitHub Private Security Advisory** (preferred) — go to the repository's
   **Security → Advisories → Report a vulnerability** tab. This routes
   straight to the maintainer in a private channel that survives even if
   the repo issue tracker is open to the public.
2. **Email the maintainer** at the address listed in the `Cargo.toml`/PyPI
   metadata or on the maintainer's GitHub profile (`Ahmad-Ajm`).

Include:

- A clear description of the issue.
- Steps to reproduce (a minimal proof-of-concept is gold).
- Potential impact (what an attacker gains, against what threat model).
- Any suggested mitigation if you have one.

You should expect an acknowledgement within a few days. Coordinated
disclosure: please give the maintainer a reasonable window (≥ 14 days for
local-impact issues, ≥ 30 days for anything that can escape the
operator's machine) before public disclosure.

## Scope

Security-sensitive areas include SSRF-like URL handling, unsafe file writes, credential leaks, unsafe XML parsing, and crawler behavior that can unintentionally overload a target site.

## Notes on specific behaviors

- **Secrets** (PageSpeed/AI/Google keys) are read from a local `.env` or per-job config (both gitignored) and passed to the crawl subprocess via environment variables only — never written to the committed config or to disk artifacts.
- **No PII** is collected from GA4 or sent to the AI provider — only page URLs, issue types, and aggregate numbers.
- **Auto-install of optional requirements** (`utils/auto_install.py`) runs `pip install` for missing libraries, but is restricted to a fixed **allowlist** of the tool's own optional dependencies (no arbitrary package names), installs locally for the current interpreter, and can be disabled with `SCT_NO_AUTO_INSTALL=1`.
- **Optional integrations** (GSC, GA4, PageSpeed, CrUX, URL Inspection, AI advisor) are all off by default; outbound fetches go through the SSRF guard and size caps where applicable.
- **OAuth** in the background crawl is non-interactive (`SCT_NONINTERACTIVE`) so it can never block waiting for a browser consent.

## v1.04+ surfaces (documented for transparency)

- **Live backlinks egress (v1.04)** — Ahrefs v3 and Majestic OpenApp. Off by
  default. Keys pass via `BACKLINKS_API_KEY` env var, never written to disk.
  Ahrefs uses `Authorization: Bearer …` header. Majestic, by API design, only
  accepts the key as a query parameter; the code path scrupulously avoids
  logging `response.url` to prevent it leaking into proxy/middleware logs.
- **Google OAuth token rewrite (v1.06)** — when an expired access token is
  refreshed silently, the new token replaces the existing `gsc_token.json` /
  `ga4_token.json`. v1.09 writes atomically via temp file + `os.replace` so
  a crash mid-write can never corrupt the token (which previously forced a
  re-consent).
- **Phase 2 deferred-CSV seed (v1.08)** — user-editable CSV becomes a crawler
  seed list. v1.09 runs every CSV URL through `is_safe_remote_url` before
  enqueueing to close the SSRF window.
- **Cross-origin POST (v1.09)** — the webapp now enforces an `Origin` header
  check on all state-changing endpoints. If a request carries an `Origin`
  that is not `127.0.0.1`/`localhost`/`::1`, the request is rejected with
  403. CLI/server-to-server callers (no `Origin` header) are unaffected.
- **subprocess argv hardening (v1.09)** — `mode` is whitelisted to
  `{audit, competitor, compare}` before being passed to `main.py`; `url` is
  validated as http(s) and forbidden from starting with `--` to prevent
  argument injection.
- **SSRF fixes (v1.09)** — `is_safe_remote_url` now also rejects
  IPv4-mapped IPv6 (`::ffff:127.0.0.1`) and fails closed on DNS resolution
  errors (previously failed open). The JS renderer and the `head()` redirect
  path now consult the same guard.
- **PII strip for AI (v1.09)** — `build_audit_summary_for_ai` strips the
  query string from URLs in `top_opportunities` before sending to the
  third-party LLM, removing `?session=`, `?email=`, `?utm_*`, etc.

## v1.10 and later surfaces (web UI hardening)

The web UI gained its own threat model when v1.10 made it the default way
to run SCT. The following controls ship as part of `webapp/security.py`
+ `webapp/job_runner.py`:

- **Local auth token (v1.10-A1)** — a per-install token is generated on
  first server start and stored at `~/.sct/local_token` with mode `0600`.
  Every `/api/*` route requires it via `Authorization: Bearer <token>` or
  `?token=<token>` (added in v1.13.2 so SSE/EventSource and `<a href>`
  downloads work without a fetch monkey-patch). `/health`, `/readyz`,
  `/static/*`, and HTML page routes (`/`, `/jobs/{id}`) are exempt.
  Comparison is constant-time via `hmac.compare_digest`. Without this
  any process with network access to `127.0.0.1:8000` could drive the
  API; with it, a stolen token is the only realistic local-network
  privesc path, and a token rotation is `rm ~/.sct/local_token && restart`.
- **CSRF Origin guard (v1.09 / hardened in v1.10)** — every state-changing
  request whose `Origin` header is set and is not `127.0.0.1`/`localhost`/`::1`
  is rejected with 403. Callers without an `Origin` header (curl,
  server-to-server) are unaffected. Combined with the auth token this is
  defense in depth against a browser visiting a hostile page that tries to
  hit the local API.
- **Rate limiting (v1.10-B1a)** — in-memory token-bucket per `(client_ip,
  scope)`. `/api/start` is limited to 10 requests per minute; all other
  `/api/*` to 120/min. Static and health endpoints are exempt. Exceeding
  returns `429 {"error": "rate_limited", ...}`. The intent is not
  load-shedding but a circuit-breaker against a runaway script.
- **Correlation IDs (v1.10-B1b)** — every request gets a 12-char UUID,
  exposed both as `request.state.request_id` to handlers and as
  `X-Request-ID` on the response. The global exception handler logs
  `[req=<id>] unhandled <Type> on <method> <path>\n<traceback>` so a
  500-returning user-facing `request_id` lets the operator find the
  exact stack trace in the server log.
- **Global exception handler (v1.10-A3)** — before v1.10 roughly 30
  `try/except` sites returned `{"error": str(e)[:300]}` to the client,
  leaking file paths, table names, and occasionally repr-state. Now a
  single `@app.exception_handler(Exception)` returns
  `{"error": "internal_error", "request_id": "..."}` and writes the
  traceback to the server log only.
- **SQL identifier whitelist (v1.10-A2)** — four f-string interpolation
  sites in `storage/database.py` previously embedded table names directly
  (the values were compile-time constants but the pattern was dangerous).
  Now `_ALLOWED_TABLES` frozenset + `_safe_table()` + `_IDENT_RE` /
  `_DEFN_RE` regex gates filter every identifier before it touches a
  query.
- **Atomic token writes (v1.09-B6 / v1.10)** — Google OAuth tokens and
  the local auth token are written via `_atomic_write_text` (temp + fsync
  + `os.replace`) so a crash mid-write cannot corrupt them. Token files
  inherit `mode=0o600` on the temp before the rename.
- **MIME validation on uploads (v1.10-C1)** — `/api/google/upload` accepts
  only `application/json` (with a small list of other JSON-compatible
  MIMEs); other content types are rejected with 400.
- **`/readyz` filesystem write-probe (v1.10-B1c)** — the readiness probe
  actually writes a tiny file under `webapp_jobs/` and deletes it,
  returning 503 if it can't. The intent is that orchestrators (compose
  healthcheck, K8s) restart the container if the volume goes read-only.
- **SCT_AUTO_INSTALL opt-in (v1.12 DEP-12)** — `utils/auto_install.py`
  used to be enabled by default with an allowlist. v1.12 inverted the
  policy: optional dependencies log a clear error naming the package
  and the exact `pip install …` command unless the operator explicitly
  sets `SCT_AUTO_INSTALL=1`. Reasons documented inline: defeats
  `requirements.txt` pinning, dev/prod skew under non-root container,
  typosquat surface.

## Threat model in one paragraph

SCT is designed for a single operator running it on their own machine.
The token wall, CSRF guard, and rate limits exist to prevent another
process on the same machine (Docker bridge, LAN host, browser visiting a
hostile page) from driving the API — not to be a production-grade public
web app. The operational expectation is that the host is the operator's
laptop or a single-user VM. If you intend to expose SCT to additional
users put it behind a reverse proxy that you configure for TLS, HSTS,
CSP, and source-IP restriction; do **not** rely on SCT's defaults for
public exposure. See `docs/RUNBOOK.md` §8 for the full discussion.
