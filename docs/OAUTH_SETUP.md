# OAuth & Google Cloud setup — SCT

> A 3-step guide for creating the OAuth client credentials that SCT uses to
> read Google Search Console, Google Analytics 4, and PageSpeed Insights.
> النسخة العربية: [`OAUTH_SETUP_AR.md`](OAUTH_SETUP_AR.md).

## Why OAuth?

SCT does not store your email or password. Instead it uses OAuth: you consent
once in your browser, then a "token" is stored locally and refreshes itself
automatically. The token is tied to the Google Cloud project **you** create —
no third party in the middle.

## The three steps

### 1. Create a project and enable the APIs

Open the [Google Cloud Console](https://console.cloud.google.com/), pick an
existing project or create a new one. Then from **APIs & Services → Library**
enable these three APIs:

- **Search Console API** — fetches GSC clicks / impressions.
- **Google Analytics Admin API** — lists your GA4 properties (powers the
  dropdown in the UI).
- **Google Analytics Data API** — pulls GA4 metrics (sessions, channels, …).

Enabling an API takes seconds — no credit card, no change in billing.

### 2. Configure the OAuth consent screen

From **APIs & Services → OAuth consent screen**:

- Pick **External** as the user type (works fine even if it's just you).
- Fill in the basics: app name, support email, developer email.
- Pick the scopes you'll request — the GA4 and GSC scope shortcuts are enough.
- On the **Test users** page add your own email (and your teammates) — while
  the app is in *Testing* mode only listed users can sign in. This is more
  than enough for personal / internal use.

> **Note:** in *Testing* mode refresh tokens expire every **7 days**, so you
> will re-consent weekly. For production without the "unverified app" warning
> you need OAuth verification from Google (the scopes are sensitive).

### 3. Create an OAuth Client ID

From **APIs & Services → Credentials → + CREATE CREDENTIALS → OAuth client ID**:

- Choose application type **Desktop app** (not Web).
- Give it a name (e.g. "SCT local").
- Click **CREATE**, then **DOWNLOAD JSON** — save the file on your machine.

## Wiring SCT to the JSON

In the SCT UI, open the **🔌 Integrations & AI** tab:

1. Click **📤 Upload file** and upload the `client_secret.json` you just
   downloaded.
2. Click **🔐 Sign in with my account (opens browser)** — your browser opens
   Google's consent screen. Pick the account that has GA4 / GSC access and
   approve.
3. The token is stored under `webapp_jobs/_google/` and is never committed
   to git.

## For headless machines (remote server, WSL, etc.)

Expand the **🔗 Browser can't open? Use "paste-the-code"** section in the
same tab:

1. Click **🔗 Get the consent URL** — it gives you a link.
2. Open the link in any browser (on a different machine if necessary).
3. After approving Google bounces you to a page whose URL contains
   `?code=...` — copy the value in full.
4. Paste it into the field and click **🔓 Complete authorization**.

## Troubleshooting

| Error | Likely cause | Fix |
|---|---|---|
| `not_connected` | Step 3 never completed | Click "Sign in with my account" |
| `auth_failed` | Refresh token expired (>7 days in Testing mode) | Re-consent |
| `not in test users` | Your account isn't on the OAuth Test-users list | Add it in the OAuth consent screen |
| `403 PERMISSION_DENIED` on GSC | Your account doesn't have access to this site in GSC | Ask the owner to add you as a User |
| `403` on GA4 | Your account doesn't have access to the Property | Add it from GA4 → Admin → Property Access Management |

## Security

- The `client_secret.json` and the two token files are stored under
  `webapp_jobs/_google/` on your machine only (with `0600` permissions on
  Unix).
- `webapp_jobs/` is listed in `.gitignore` — never pushed to the repository.
- PageSpeed / AI keys are passed to the crawler subprocess via environment
  variables — never written to disk.
