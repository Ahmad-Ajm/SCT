# Security Policy

## Reporting a Vulnerability

Please do not open public issues for security-sensitive findings. Report the issue privately to the project maintainer, including:

- A clear description of the issue.
- Steps to reproduce.
- Potential impact.
- Any suggested mitigation.

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
