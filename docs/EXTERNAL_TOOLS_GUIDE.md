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

## 6) CrUX History (Core Web Vitals trend)

Optional — no extra install; uses the same PageSpeed API key. The **Chrome UX
Report (CrUX) History API** returns the *field* (real-user) Core Web Vitals for
your origin over time — LCP, INP, CLS at the p75 percentile — so you can see
whether performance is trending up or down, not just a single lab snapshot.

Enable it in the crawl form (Integrations → PageSpeed → **CrUX History**) or in
config:
```yaml
pagespeed:
  enabled: true
  api_key: "YOUR_PAGESPEED_KEY"
  crux_history: true
```
You must enable the **Chrome UX Report API** in the same Google Cloud project as
your PageSpeed key (APIs & Services → Enable APIs → "Chrome UX Report API").
If it isn't enabled you'll see a `403 ... blocked` line in the log and SCT skips
CrUX gracefully — the rest of the audit is unaffected. Output goes to the
PageSpeed/CrUX section of the report and the raw JSON under
`pagespeed_raw/` when `save_raw_json` is on.

Note: CrUX only has data for origins with enough real Chrome traffic; low-traffic
sites return "data not available", which is normal.

## Unified report

With GSC and/or GA4 enabled and `report.unified: true`, the HTML/PDF report adds:
Search Visibility (GSC), User Behavior (GA4), and a **Priority Opportunities** section that
joins technical issues with clicks/sessions to rank what to fix first
(see `priority_opportunities.csv`).

Bing Webmaster connector is not implemented yet (planned).

---

## Live backlinks API — Ahrefs / Majestic (v1.04, paid)

In addition to the free AWT CSV importer above (only covers sites you own/verify),
SCT ships a **live backlinks API** integration for the two main commercial providers.
Off by default. Paid keys required.

**When to use which:**
- **AWT CSV (free)**: site you own + verified in Ahrefs Webmaster. No API needed.
  Export from Ahrefs Webmaster UI → drop CSV into `external_data/awt/`.
- **Ahrefs live API (v1.04, paid)**: any site (yours, a client's, a competitor's).
  Requires Ahrefs **Standard** subscription or higher (Webmaster tier does **not**
  expose the public API).
- **Majestic live API (v1.04, paid)**: any site. Requires Majestic **OpenApp** key.

**Wire it up:**

In the SCT web UI, *Integrations & AI* tab:
1. Toggle **🔗 Backlinks (live API — Ahrefs/Majestic)**.
2. Pick the provider (Ahrefs or Majestic).
3. Paste your API key. The key is passed to the crawl subprocess via the
   `BACKLINKS_API_KEY` env var and **never written to disk** (same pattern as PageSpeed).

Or via `config.yaml`:

```yaml
integrations:
  backlinks:
    enabled: true
    provider: ahrefs    # or: majestic
    timeout: 30
```

And export `BACKLINKS_API_KEY=...` in your shell before running.

**What it pulls** (both providers, unified shape under `integrations.backlinks` in
`audit.json`):
- `summary`: domain-level metrics (DR/TrustFlow, total backlinks, referring domains)
- `top_referring_domains`: up to 50, sorted by domain rating / trust flow
- `top_anchors` (Ahrefs only): top 30 anchor texts

---

## AI advisor (optional narrative — any OpenAI-compatible provider)

SCT's prioritization is **deterministic** (the Priority Engine formula is pure
math). The AI advisor is a *separate, optional* layer that turns the audit into
plain-language narrative: an executive summary and a short list of prioritized
recommendations. It never changes the ranking — it only describes it.

**Providers supported** (anything speaking the OpenAI chat-completions API):
OpenAI, Google Gemini, DeepSeek, OpenRouter, Hugging Face, and **local models**
via Ollama / LM Studio on `127.0.0.1`. Pick "Local model" in the UI to keep
everything on your machine.

**Wire it up** — *Integrations & AI* tab → toggle **🤖 AI advisor**, choose the
provider, model, and (for local/custom) the base URL, then paste the key. Or via
config:
```yaml
integrations:
  ai:
    enabled: true
    provider: openai        # openai | gemini | deepseek | openrouter | huggingface | local
    model: "gpt-4o-mini"    # provider-specific model id
    base_url: ""            # required for local/custom OpenAI-compatible endpoints
```
The key is passed via the `AI_API_KEY` env var and **never written to disk**.

**Privacy.** Only URLs, issue types, and aggregate numbers are sent — no page
bodies, no PII. Query strings are stripped from URLs before sending (so
`?session=`, `?email=`, `?utm_*` never leave). For maximum privacy, use a local
model — nothing leaves `127.0.0.1`. If the provider returns a malformed or empty
response, SCT logs a warning and continues without AI text; the technical audit
is unaffected.

Output: an `ai_recommendations.csv` plus an AI section in the HTML/PDF report.

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
