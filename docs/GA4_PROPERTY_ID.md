# How do I find my GA4 `property_id`?

> النسخة العربية: [`GA4_PROPERTY_ID_AR.md`](GA4_PROPERTY_ID_AR.md).

The `property_id` is the identifier of a Google Analytics 4 **Property** —
a 9-10 digit number (e.g. `123456789`). SCT needs it to fetch GA4 data.

## Method 1 — from the GA4 UI (fastest)

1. Open [Google Analytics](https://analytics.google.com/) and pick the
   Property from the top dropdown.
2. Click **⚙️ Admin** at the bottom of the left sidebar.
3. In the middle column ("Property") click **Property details** (or
   **Property settings**).
4. **Property ID** is shown at the top of the page — copy it.

> The number usually starts with `2`, `3`, `4`, or `5` and is 9-10 digits.

## Method 2 — from the SCT UI (easiest after connecting Google)

After connecting Google from the **🔌 Integrations & AI** tab in SCT:

1. In the **Google Analytics 4** card click **📋 Fetch GA4 properties**.
2. A dropdown appears with every Property you have access to.
3. Pick one — `property_id` is filled in automatically.

## Property ID vs Measurement ID

- **Property ID**: a ~9-10 digit number (`123456789`) — this is what SCT
  needs.
- **Measurement ID**: starts with `G-` (e.g. `G-XXXXXXXXXX`) — used in the
  `gtag` snippet on your website, **not** the value SCT asks for.

## Required permissions

To read Property data, your account needs at least the **Viewer** role on
the GA4 Property:

- Open GA4 → **⚙️ Admin** → **Property Access Management**.
- If you're not listed, ask the Property owner to add you (their email +
  role = Viewer is enough).
