"""
webapp/app.py
=============
واجهة SCT المرئية المتكاملة (FastAPI + HTMX + SSE).

الميزات:
- تخصيص الإعدادات (URL، mode، حدود الزحف، خيارات التقرير/PDF).
- بدء/إيقاف الزحف ومتابعة التقدّم مباشرة (SSE).
- استعراض النتائج وتنزيل تقارير HTML/PDF/JSON/Excel.

التشغيل:
    python webapp/run.py
ثم افتح: http://127.0.0.1:8000
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
# نتيح استيراد حزمة الزاحف (لإعادة بناء التقارير عند الطلب)
sys.path.insert(0, str(ROOT / "seo_crawler" / "seo_crawler"))

log = logging.getLogger("sct.webapp")

app = FastAPI(title="SCT — Simple Crawler Tool")
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

# v1.12.4 REFACTOR-app-routers: runner/templates/path helpers نُقلت إلى webapp/deps.py
from webapp.deps import (  # noqa: E402
    FINISHED_STATUSES,
    _google_dir,
    _job_output_dir,
    _run_conn_test,
    _safe_output_file,
    _safe_under_jobs,
    runner,
    templates,
)


# ============================================================
# v1.12.3 REFACTOR-app-routers: auth + middlewares + exception handlers
# نُقلت إلى webapp/security.py.
# ============================================================
from webapp.security import (  # noqa: E402,F401
    LOCAL_TOKEN as _LOCAL_TOKEN,
    _atomic_write_text,
    _check_rate,
    _constant_time_eq,
    _extract_token,
    register_exception_handlers,
    register_middlewares,
    tpl_ctx as _tpl_ctx,
)
register_middlewares(app)
register_exception_handlers(app)

# v1.12.4–v1.12.6 REFACTOR-app-routers: 9 routers (REFACTOR-app-routers مكتمل)
from webapp.routers.pages import router as pages_router  # noqa: E402
from webapp.routers.jobs import router as jobs_router  # noqa: E402
from webapp.routers.logs import router as logs_router  # noqa: E402
from webapp.routers.connections import router as connections_router  # noqa: E402
from webapp.routers.setup import router as setup_router  # noqa: E402
from webapp.routers.analytics import router as analytics_router  # noqa: E402
from webapp.routers.downloads import router as downloads_router  # noqa: E402
from webapp.routers.generate import router as generate_router  # noqa: E402
from webapp.routers.google_oauth import router as google_oauth_router  # noqa: E402
app.include_router(pages_router)
app.include_router(jobs_router)
app.include_router(logs_router)
app.include_router(connections_router)
app.include_router(setup_router)
app.include_router(analytics_router)
app.include_router(downloads_router)
app.include_router(generate_router)
app.include_router(google_oauth_router)

# مجموعات ما يُجمَع (extraction) — تُعرض كأقسام قابلة للطيّ في الواجهة
# v1.12.3 REFACTOR-app-routers: ثوابت + label_for نُقلت إلى webapp/constants.py
from webapp.constants import (  # noqa: E402,F401
    CSV_LABELS,
    EXTRACTION_GROUPS,
    MAX_AUDIT_JSON_MB,
    OUTPUT_FORMATS,
    SECTIONS,
    SEVERITIES,
    UA_PRESETS as _UA_PRESETS,
    label_for as _label_for,
)


@app.get("/health")
async def health():
    """v1.10-B1: liveness — يُفيد orchestrators (Docker compose, K8s) أنّ الـapp يردّ."""
    return JSONResponse({"status": "ok"})


@app.get("/readyz")
async def readyz():
    """v1.10-B1: readiness — يفحص قابليّة الكتابة + DB access. يردّ 503 إن غير جاهز."""
    from webapp.job_runner import JOBS_DIR
    try:
        # فحص فعلي للكتابة في jobs dir
        probe = JOBS_DIR / ".healthcheck"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return JSONResponse({"status": "ready"})
    except OSError as e:
        return JSONResponse({"status": "not_ready", "reason": str(e)[:120]}, status_code=503)


# v1.12.6 REFACTOR-app-routers: job lifecycle endpoints (start/progress/events/
# phase2/deferred/stop/kill/delete/delete-all) -> webapp/routers/jobs.py.

# v1.12.5 REFACTOR-app-routers: download endpoints (report/download/view/files/
# download-file/download-all) -> webapp/routers/downloads.py.


# v1.12.6 REFACTOR-app-routers: Google OAuth endpoints + _paste_flow state
# نُقلت إلى webapp/routers/google_oauth.py.
# Backward-compat: tests reach for webapp.app._probe_token_expired and
# webapp.app._extract_oauth_code — نُعيد تصديرهما هنا.
from webapp.routers.google_oauth import (  # noqa: E402,F401
    _extract_oauth_code,
    _probe_token_expired,
)

# v1.12.4 REFACTOR-app-routers: setup + requirements + docs نُقلت إلى
#   webapp/routers/setup.py (POST/GET /api/setup/{tool}, GET /api/requirements,
#                            GET /docs/{name})

# v1.12.6 REFACTOR-app-routers: generate endpoints -> webapp/routers/generate.py

# v1.12.5 REFACTOR-app-routers: analytics endpoints + _build_graph_payload نُقلت
# إلى webapp/routers/analytics.py.

