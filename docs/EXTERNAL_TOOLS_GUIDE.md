# SCT External Tools Guide

SCT focuses on crawling and internal analysis (pages, links, redirects, resources,
technical issues). For specialized areas (performance, accessibility, deep security) we
point you to strong free tools instead of rebuilding them, then import their output
alongside SCT reports. **No API keys are embedded in the codebase.**

## When to use which tool

| Need | Recommended tool | How SCT uses it |
|---|---|---|
| Performance (Core Web Vitals) | Lighthouse / PageSpeed | Import JSON → show scores |
| Accessibility (WCAG) | Lighthouse or axe-core | Import JSON (later) + basic internal checks |
| Deep security (DAST) | OWASP ZAP | Guidance + import (later); SCT checks basic headers |
| Search performance (clicks/impressions) | Google Search Console / Bing | Optional connector with your own keys |

---

## 1) Lighthouse / PageSpeed (performance)

SCT does not build a performance engine. Run Lighthouse locally and drop JSON files
for SCT to read.

```bash
npm install -g lighthouse
lighthouse https://example.com/ --output=json \
  --output-path=./external_data/lighthouse/home.json --quiet --chrome-flags="--headless"
```
Or use https://pagespeed.web.dev/ and save the JSON. Optional API key via `.env`:
```env
PAGESPEED_API_KEY=your-own-key
```

Import in SCT:
1. Put JSON files in `./external_data/lighthouse/`.
2. Enable in `config.yaml`:
   ```yaml
   integrations:
     lighthouse:
       enabled: true
       folder: "./external_data/lighthouse"
   ```
3. You'll get `lighthouse_import.csv` (performance/accessibility/best-practices/seo, 0–100).

---

## 2) Accessibility

SCT only does basics (images without alt, etc.). For full WCAG use Lighthouse's
accessibility category, or axe-core:
```bash
npm install -g @axe-core/cli
axe https://example.com/ --save ./external_data/axe/home.json
```
Dedicated axe import will be added later; for now use Lighthouse JSON.

---

## 3) Security

SCT automatically checks core headers (HTTPS, HSTS, CSP, X-Frame-Options,
X-Content-Type-Options, Referrer-Policy, Permissions-Policy, mixed content) — see
`security_issues.csv`.

For deep DAST scanning use **OWASP ZAP** (free):
```bash
docker run -t ghcr.io/zaproxy/zaproxy zap-baseline.py -t https://example.com/ -J zap.json
```
Place `zap.json` in `./external_data/zap/` (import to be added later).
**Warning:** never run an active scan on sites you are not authorized to test.

---

## 4) Google Search Console (search performance)

Optional connector with your own key — nothing is embedded in the repo.
1. Enable **Search Console API** in Google Cloud; create OAuth (Desktop) credentials JSON.
2. Point to it via `.env` and enable `integrations.gsc`:
```env
GSC_CREDENTIALS_FILE=credentials/gsc_credentials.json
```
Benefit: compare crawled pages against pages receiving impressions/clicks.

## 5) Google Analytics 4 (user behavior)

Optional connector — needs `pip install google-analytics-data`.
1. Enable **Google Analytics Data API**; create a **Service Account**, download its JSON,
   and add the service-account email as a viewer on your GA4 property.
2. Get the **Property ID** (number) from GA4 settings.
```env
GA4_CREDENTIALS_FILE=credentials/ga4_service_account.json
GA4_PROPERTY_ID=123456789
```
No PII is collected — only aggregate, page-level metrics.

## Unified report

With GSC and/or GA4 enabled and `report.unified: true`, the HTML/PDF report adds:
Search Visibility (GSC), User Behavior (GA4), and a **Priority Opportunities** section that
joins technical issues with clicks/sessions to rank what to fix first
(see `priority_opportunities.csv`).

Bing Webmaster connector is not implemented yet (planned).

---

## Where to put files

```
external_data/
├── lighthouse/   ← Lighthouse/PageSpeed JSON
├── axe/          ← axe-core reports (later)
├── zap/          ← OWASP ZAP reports (later)
└── awt/          ← Ahrefs Webmaster Tools export (CSV)
```
All of these are git-ignored.

## Principles
- No keys/credentials in code.
- Every integration is optional and disabled by default.
- SCT works fully without any external tool.
