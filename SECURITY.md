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
