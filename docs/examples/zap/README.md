# OWASP ZAP example

SCT does not run active security scans. Use OWASP ZAP (free) for deep DAST.

Passive baseline scan (safe):
```bash
docker run -t ghcr.io/zaproxy/zaproxy zap-baseline.py -t https://example.com/ -J zap.json
```
Place `zap.json` in `external_data/zap/`. Native ZAP import will be added later; for now
the file is for your own review.

**Warning:** only scan sites you own or are explicitly authorized to test. Never run an
active scan against third-party sites.

SCT already reports basic header security in `security_issues.csv` (HTTPS, HSTS, CSP,
X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, mixed content).
