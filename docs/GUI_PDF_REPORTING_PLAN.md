# GUI, PDF Reporting, Scheduling, and JavaScript Rendering Plan

This document describes a practical implementation plan for turning SCT from a CLI-first SEO crawler into a user-friendly desktop/web application with scheduled, customizable PDF reporting.

## Product Goal

SCT should remain a reliable CLI tool, then gain a local GUI that helps non-technical users configure crawls, run audits, inspect issues, export reports, and schedule recurring reports. The GUI should not replace the core crawler; it should orchestrate it through a stable internal service layer.

## Recommended Architecture

### Backend

Use `FastAPI` as a local backend API.

It gives SCT a clean boundary between the crawler engine and future interfaces. The same API can serve a browser UI, a desktop wrapper, or external automation.

Core backend responsibilities:

- Manage projects and crawl configurations.
- Start, stop, pause, and resume crawl jobs.
- Stream live logs, progress, and metrics.
- Read SQLite crawl results.
- Generate CSV, JSON, HTML, and PDF reports.
- Manage report schedules.

### Frontend

Use `React + Vite + TypeScript` for the first full GUI.

This is more work than Streamlit, but it is a better long-term choice for dashboards, filtering, tables, charts, and report customization. It can later be packaged as a desktop app with Tauri or Electron.

Core frontend sections:

- Dashboard: recent projects, crawl health, latest reports.
- Project setup: URL, crawl limits, robots policy, output options.
- Crawl monitor: live progress, queue size, pages/sec, errors, status codes.
- Issues: filter by severity, category, affected URLs, recommendations.
- URL explorer: pages, links, images, headers, schema, canonical, hreflang.
- Compare mode: site vs site and run vs run.
- Report builder: choose sections, branding, language, and PDF style.
- Scheduler: recurring reports and saved report presets.

### Desktop Packaging

Phase 1 should run as:

```bash
python -m sct_server
```

Then open `http://127.0.0.1:8787`.

Phase 2 can package the app with Tauri or Electron. Tauri is lighter, but Electron has more mature cross-platform examples. Keep the backend Python process separate from the UI shell.

## Data Model

Add lightweight tables or JSON config files for GUI state:

- `projects`: project name, base URL, config path, created_at, updated_at.
- `crawl_runs`: run id, project id, mode, status, started_at, finished_at, output_dir, db_path.
- `report_templates`: template name, language, brand colors, enabled sections, logo path.
- `report_schedules`: project id, cron/interval, template id, output format, destination.
- `notifications`: optional email/webhook settings.

The crawler result database should stay focused on crawl data. GUI metadata can live in a separate `sct_app.db`.

## GUI Implementation Phases

### Phase 1: Backend API

Build a local FastAPI service.

Endpoints:

- `GET /health`
- `GET /projects`
- `POST /projects`
- `POST /runs`
- `GET /runs/{id}`
- `POST /runs/{id}/cancel`
- `GET /runs/{id}/metrics`
- `GET /runs/{id}/issues`
- `GET /runs/{id}/pages`
- `POST /reports`
- `GET /reports/{id}/download`

Importance: This unlocks both GUI and automation without rewriting crawler logic.

### Phase 2: Job Manager

Create a job runner that executes crawl workflows in background processes.

It should capture stdout/stderr, write structured status updates, and prevent two jobs from writing to the same database. Start with one active job, then add queueing.

Importance: A GUI must not freeze while crawling, and failed jobs need clear status.

### Phase 3: Read-Only GUI

Build a UI that reads completed crawl results.

Start with dashboards for existing `output/` and SQLite databases. Avoid job control until viewing and reporting are stable.

Importance: Fastest path to visible value with low risk.

### Phase 4: Run Controls

Add forms to start crawls from the GUI.

Expose only safe options first: URL, mode, max pages, concurrency, delay, output formats, robots policy, and external link checks.

Importance: This makes SCT usable for non-CLI users.

### Phase 5: Advanced Analysis UI

Add interactive tables and drilldowns.

Features:

- Issue filtering by severity/category.
- Affected URL samples.
- Page detail view.
- Links in/out view.
- Canonical and URL hygiene reports.
- Schema and hreflang views.

Importance: This is where the GUI becomes more valuable than raw CSV files.

## PDF Reporting

### Recommended PDF Pipeline

Use an HTML-to-PDF pipeline.

Recommended options:

1. `Playwright PDF`: best visual fidelity, uses Chromium print rendering.
2. `WeasyPrint`: clean Python integration, strong for static documents, but CSS support differs from Chromium.
3. `ReportLab`: very reliable for programmatic PDFs, but slower to design and less designer-friendly.

Recommendation: use **HTML templates + Playwright PDF** first.

Reason: SCT already plans Playwright for JavaScript rendering, and HTML templates are easier to customize for branded reports.

### Report Template System

Use Jinja2 templates:

```text
reports/
  templates/
    default_en/
      report.html.j2
      styles.css
      theme.json
    default_ar/
      report.html.j2
      styles.css
      theme.json
```

Each template should support:

- Logo.
- Brand color.
- Accent color.
- Font family.
- Language: English/Arabic.
- RTL/LTR direction.
- Cover page.
- Executive summary.
- Issue severity summary.
- Technical issues.
- On-page issues.
- Content issues.
- Performance hints.
- URL and canonical issues.
- Appendix with affected URLs.

### PDF Customization

Users should be able to customize:

- Report title.
- Client/project name.
- Logo.
- Brand colors.
- Language.
- Included sections.
- Severity threshold.
- Maximum URLs per issue.
- Include/exclude screenshots.
- Include/exclude raw metrics.
- Page size: A4/Letter.
- Header/footer text.

Store these settings in `report_templates` and allow export/import as JSON.

### PDF Generation API

Add:

- `POST /report-templates`
- `GET /report-templates`
- `POST /reports/generate`
- `GET /reports/{id}`
- `GET /reports/{id}/download`

Report generation should be asynchronous because large reports may take time.

## Report Scheduling

### Scheduler Engine

Use `APScheduler` for local scheduling.

It is simpler than Celery and works well for local/desktop use. Celery only becomes necessary if SCT grows into a multi-user server product.

Schedule types:

- One-time.
- Daily.
- Weekly.
- Monthly.
- Custom cron expression.

### Scheduled Workflow

A scheduled report should:

1. Load project config.
2. Run crawl or analyze existing DB depending on schedule settings.
3. Generate CSV/JSON/PDF.
4. Save outputs to a timestamped folder.
5. Write a schedule execution log.
6. Optionally send email/webhook notification.

### Delivery Options

Phase 1:

- Save locally.

Phase 2:

- Email via SMTP.
- Webhook.
- Upload to Google Drive or S3-compatible storage.

### Safety Controls

Scheduled jobs must include:

- Maximum pages limit.
- Concurrency limit.
- Robots policy.
- Timeout.
- Failure notification.
- Lock to prevent overlapping runs for the same project.

## JavaScript Rendering Difficulty Assessment

### Current State

SCT already has a `JSRenderer` using Playwright, but it is currently sync-oriented and integrated mainly with the synchronous crawler path.

The async crawler is the main high-performance path, and it does not yet have mature JavaScript rendering integration.

### Difficulty Rating

Overall difficulty: **High**.

Estimated effort for a solid implementation: **2 to 4 weeks** for a careful first production-quality version, assuming one experienced developer.

### Why It Is Difficult

JavaScript rendering is not just “open Chromium and get HTML”.

Hard parts:

- Running browsers concurrently without exhausting CPU/RAM.
- Deciding when a page is truly ready: `load`, `domcontentloaded`, `networkidle`, custom waits.
- Handling infinite network activity from analytics, chat widgets, pixels, and ads.
- Blocking unnecessary resources without breaking content.
- Comparing raw HTML vs rendered HTML.
- Keeping cookies/session/context isolated.
- Capturing console errors, failed resources, screenshots, and final DOM.
- Avoiding false positives from lazy-loaded content.
- Making rendering optional and bounded by page limits.
- Making it work inside scheduled jobs and CI-like environments.

### Recommended Implementation Strategy

Do not enable JavaScript rendering globally by default.

Implement it as a selective rendering layer:

- Render only URLs that match configured patterns.
- Render only first N pages.
- Render only pages where raw HTML appears thin or missing key elements.
- Render templates/page types: home, product, category, article.
- Add `rendered_raw_diff` outputs.

### JavaScript Rendering Milestones

1. Async Playwright pool with 1-3 browser contexts.
2. Configurable resource blocking: images, fonts, analytics, ads.
3. Rendered DOM extraction.
4. Raw vs rendered comparison for title, meta description, H1, canonical, links, word count, schema.
5. Console and network error capture.
6. Optional screenshots.
7. Rendered metrics in JSON/CSV/PDF reports.

### Recommendation

Build GUI and report foundations first, then improve JavaScript rendering.

Reason: the GUI and PDF reporting can use existing crawl data immediately. JavaScript rendering is valuable, but it can slow the crawler dramatically and create many edge cases if added too early.

## Suggested Technical Stack

- Backend API: FastAPI.
- Job scheduling: APScheduler.
- Frontend: React + Vite + TypeScript.
- UI library: TanStack Table, Recharts, Radix UI, Tailwind or plain CSS variables.
- PDF templates: Jinja2 + Playwright PDF.
- Local DB: SQLite.
- Desktop wrapper later: Tauri or Electron.

## Minimum Viable GUI

The MVP should include:

- Project creation.
- Start crawl.
- Progress monitor.
- Completed run list.
- Issues table.
- Pages table.
- Export CSV/JSON/PDF.
- One default PDF template.

Do not start with:

- Multi-user authentication.
- Cloud deployment.
- Complex role permissions.
- Full drag-and-drop report builder.
- Global JavaScript rendering.

## Definition of Done

The GUI/reporting system is ready for public release when:

- A user can configure and run a crawl without editing YAML.
- A user can see progress and errors live.
- A completed run can be explored in the browser.
- PDF reports can be generated in English and Arabic.
- A scheduled weekly report can run locally.
- Failed schedules produce clear logs.
- Tests cover report generation and schedule execution.
