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

import asyncio
import json
import logging
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

ROOT = Path(__file__).resolve().parent.parent
# نتيح استيراد حزمة الزاحف (لإعادة بناء التقارير عند الطلب)
sys.path.insert(0, str(ROOT / "seo_crawler" / "seo_crawler"))

from webapp.job_runner import JobRunner  # noqa: E402

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

# v1.12.4/v1.12.5 REFACTOR-app-routers: pages/logs/connections/setup/analytics/downloads
from webapp.routers.pages import router as pages_router  # noqa: E402
from webapp.routers.logs import router as logs_router  # noqa: E402
from webapp.routers.connections import router as connections_router  # noqa: E402
from webapp.routers.setup import router as setup_router  # noqa: E402
from webapp.routers.analytics import router as analytics_router  # noqa: E402
from webapp.routers.downloads import router as downloads_router  # noqa: E402
app.include_router(pages_router)
app.include_router(logs_router)
app.include_router(connections_router)
app.include_router(setup_router)
app.include_router(analytics_router)
app.include_router(downloads_router)

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


@app.post("/api/start")
async def start(request: Request):
    # نمنع المهام المتوازية: مهمة زحف واحدة في كل وقت (تخفيفاً للضغط + وضوحاً)
    active = runner.active_job()
    if active:
        return JSONResponse(
            {"error": "مهمة زحف نشطة بالفعل. أوقفها أو انتظر انتهاءها.",
             "active_job": active},
            status_code=409,
        )

    form = await request.form()

    def _b(name: str, default: bool = False) -> bool:
        return str(form.get(name, str(default))).lower() in ("true", "1", "on", "yes")

    # === صيغ المخرجات المختارة ===
    # v1.04: كلّ التنسيقات الثقيلة (Excel/XML/HTML/PDF) صارت عند الطلب من صفحة المهمّة.
    # الزحف يُنتج CSV+JSON فقط (سريع جدّاً، مساحة قليلة). للحفاظ على التوافق العكسي،
    # نقبل overrides من الـform إن طُلبت صراحةً (مثلاً عبر API خارجي).
    formats = form.getlist("formats") or ["csv", "json"]
    make_pdf = "pdf" in formats

    # === ما يُجمَع (extraction) — قائمة المفاتيح المختارة ===
    extraction = form.getlist("extraction")

    # === أقسام تقرير PDF/HTML المختارة ===
    sections = form.getlist("sections") or None
    severity_filter = form.getlist("severity_filter") or None

    overrides = {
        "url": (form.get("url") or "").strip(),
        "mode": form.get("mode", "audit"),
        "max_pages": int(form.get("max_pages", 500) or 500),
        "max_depth": int(form.get("max_depth", 10) or 10),
        "delay_seconds": float(form.get("delay_seconds", 0.5) or 0.5),
        "concurrent_requests": int(form.get("concurrent_requests", 5) or 5),
        "respect_robots": _b("respect_robots", True),
        "seed_strategy": form.get("seed_strategy", "hybrid"),
        "no_resume": _b("no_resume", False),
        "skip_external": _b("skip_external", False),
        "integrations_only": _b("integrations_only", False),
        "ext_sample_per_host": _b("ext_sample_per_host", False),
        "ext_max_urls": int(form.get("ext_max_urls") or 0),
        "check_resource_status": _b("check_resource_status", False),
        # خيارات مشحونة حديثاً (تُعرض في الإعدادات المتقدمة)
        "platform_preset": (form.get("platform_preset") or "").strip(),
        "generate_sitemap": _b("generate_sitemap", False),
        "adaptive_throttle": _b("adaptive_throttle", False),
        # v1.05: انتحال User-Agent — يُحوَّل preset → سلسلة فعلية في job_runner عبر crawl.user_agent
        "ua_preset": (form.get("ua_preset") or "").strip().lower(),
        "ua_custom": (form.get("ua_custom") or "").strip(),
        "formats": formats,
        # extraction: إن لم يُختر شيء نترك الإعداد الافتراضي (الكل)
        "extraction": extraction if extraction else None,
        # خيارات التقرير
        "language": form.get("language", "ar"),
        "audience": form.get("audience", "expert"),
        "client_name": form.get("client_name", ""),
        "logo_url": form.get("logo_url", ""),
        "sections": sections,
        "severity_filter": severity_filter,
        "max_rows": int(form.get("max_rows", 100) or 100),
    }

    # === إعدادات متقدمة (اختيارية) من الواجهة ===
    def _int_or_none(name: str):
        v = (form.get(name) or "").strip()
        try:
            return int(v) if v != "" else None
        except ValueError:
            return None

    # التكاملات
    integrations: dict[str, Any] = {}
    if _b("gsc_enabled", False):
        gsc = {
            "enabled": True,
            "credentials_file": (form.get("gsc_credentials_file") or "").strip(),
            "site_url": (form.get("gsc_site_url") or "").strip(),
        }
        mb = _int_or_none("gsc_months_back")
        if mb:
            gsc["months_back"] = mb
        if _b("gsc_url_inspection", False):
            gsc["url_inspection"] = True
            im = _int_or_none("gsc_inspect_max_urls")
            if im:
                gsc["inspect_max_urls"] = im
        integrations["gsc"] = gsc
    if _b("ga4_enabled", False):
        ga4 = {
            "enabled": True,
            "property_id": (form.get("ga4_property_id") or "").strip(),
            "credentials_file": (form.get("ga4_credentials_file") or "").strip(),
        }
        dr = _int_or_none("ga4_date_range_days")
        if dr:
            ga4["date_range_days"] = dr
        integrations["ga4"] = ga4
    if _b("pagespeed_enabled", False):
        integrations["pagespeed"] = {
            "enabled": True,
            "api_key": (form.get("pagespeed_api_key") or "").strip(),
            "max_urls": _int_or_none("pagespeed_max_urls") or 0,
            "save_raw_json": _b("pagespeed_save_raw", False),
            "crux_history": _b("pagespeed_crux_history", False),
        }
    if _b("lighthouse_enabled", False):
        integrations["lighthouse"] = {
            "enabled": True,
            "folder": (form.get("lighthouse_folder") or "./external_data/lighthouse").strip(),
        }
    if _b("awt_enabled", False):
        integrations["awt"] = {
            "enabled": True,
            "csv_folder": (form.get("awt_csv_folder") or "./external_data/awt").strip(),
        }
    # v1.04: تكاملات الروابط الخلفيّة الحيّة (Ahrefs / Majestic) — مدفوعة، مطفأة افتراضياً
    if _b("backlinks_enabled", False):
        integrations["backlinks"] = {
            "enabled": True,
            "provider": (form.get("backlinks_provider") or "ahrefs").strip().lower(),
            "api_key": (form.get("backlinks_api_key") or "").strip(),
            "timeout": int(form.get("backlinks_timeout") or 30),
        }
    if _b("ai_enabled", False):
        ai = {
            "enabled": True,
            "provider": (form.get("ai_provider") or "openai").strip().lower(),
            "model": (form.get("ai_model") or "").strip(),
            "base_url": (form.get("ai_base_url") or "").strip(),
            "api_key": (form.get("ai_api_key") or "").strip(),
            "allow_private": _b("ai_allow_private", False),
        }
        mo = _int_or_none("ai_max_opportunities")
        if mo:
            ai["max_opportunities"] = mo
        integrations["ai"] = ai
    if integrations:
        overrides["integrations"] = integrations

    # الاستخراج المخصّص
    if _b("custom_enabled", False):
        rules_raw = (form.get("custom_rules_json") or "").strip()
        rules: list[dict[str, Any]] = []
        if rules_raw:
            try:
                parsed = json.loads(rules_raw)
                if isinstance(parsed, list):
                    rules = parsed
            except ValueError:
                rules = []
        overrides["custom_extraction"] = {"enabled": True, "rules": rules}

    # عتبات التحليل
    analysis: dict[str, Any] = {}
    for fld, key in [
        ("thin_content_threshold", "thin_content_threshold"),
        ("title_min_length", "title_min_length"),
        ("title_max_length", "title_max_length"),
        ("description_min_length", "description_min_length"),
        ("description_max_length", "description_max_length"),
    ]:
        v = _int_or_none(fld)
        if v is not None:
            analysis[key] = v
    analysis["url_flag_non_ascii"] = _b("url_flag_non_ascii", False)
    overrides["analysis"] = analysis

    job_id = runner.start(overrides)
    return JSONResponse({"job_id": job_id})


@app.get("/api/jobs/{job_id}/progress")
async def job_progress(job_id: str):
    return JSONResponse({"meta": runner.meta(job_id), "progress": runner.progress(job_id)})


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    """Server-Sent Events: بثّ تقدّم الزحف لحظياً."""

    async def event_stream():
        last = None
        ticks = 0
        while True:
            meta = runner.meta(job_id)
            progress = runner.progress(job_id)
            # مهمة مجهولة (لا meta) ⇒ لا نُبقي اتصالاً معلّقاً للأبد
            if not meta:
                yield 'event: end\ndata: {"error": "unknown job"}\n\n'
                break
            payload = json.dumps({"meta": meta, "progress": progress}, ensure_ascii=False)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            status = meta.get("status")
            if status in FINISHED_STATUSES and not runner.is_running(job_id):
                yield f"event: end\ndata: {payload}\n\n"
                break
            ticks += 1
            if ticks > 7200:  # حدّ أمان ساعتين
                break
            await asyncio.sleep(1.0)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/jobs/{job_id}/phase2")
async def job_phase2(job_id: str):
    """v1.08: يبدأ Phase 2 — يفحص الروابط المؤجَّلة (deferred) من Phase 1."""
    return JSONResponse(runner.start_phase2(job_id))


@app.get("/api/jobs/{job_id}/deferred")
async def job_deferred(job_id: str):
    """v1.08: يُرجع ملخّص الروابط المؤجَّلة (counts + samples) للوحة الواجهة.

    البيانات تأتي من audit JSON إن وُجد، وإلّا من output/csv/deferred_urls.csv كاحتياط."""
    import json as _json
    meta = runner.meta(job_id)
    json_path = (meta.get("result") or {}).get("json")
    if json_path and Path(json_path).exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                audit = _json.load(f)
            ds = audit.get("deferred_summary") or {}
            if ds.get("total"):
                return JSONResponse(ds)
        except (OSError, ValueError):
            pass
    # احتياط: نقرأ CSV مباشرة
    out = _job_output_dir(job_id)
    if not out:
        return JSONResponse({"total": 0, "by_kind": {}, "samples": {}})
    csv_path = out / "csv" / "deferred_urls.csv"
    if not csv_path.exists():
        return JSONResponse({"total": 0, "by_kind": {}, "samples": {}})
    import csv as _csv
    by_kind: dict[str, int] = {}
    samples: dict[str, list[str]] = {}
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            for row in _csv.DictReader(f):
                k = row.get("kind", "other") or "other"
                by_kind[k] = by_kind.get(k, 0) + 1
                if len(samples.setdefault(k, [])) < 10:
                    samples[k].append(row.get("url", ""))
    except OSError:
        pass
    return JSONResponse({
        "total": sum(by_kind.values()),
        "by_kind": by_kind,
        "samples": samples,
        "phase2_available": sum(by_kind.values()) > 0,
    })


@app.post("/api/jobs/{job_id}/stop")
async def job_stop(job_id: str):
    ok = runner.stop(job_id)
    return JSONResponse({"stopped": ok})


@app.post("/api/jobs/{job_id}/kill")
async def job_kill(job_id: str):
    """قتل فوري بلا مهلة — لحالات العلوق في تكامل خارجي طويل (مثل PageSpeed)."""
    ok = runner.force_kill(job_id)
    return JSONResponse({"killed": ok})


@app.post("/api/jobs/{job_id}/delete")
async def job_delete(job_id: str):
    """يحذف مهمّة من القرص (اللوغ + المخرجات + الحالة). يرفض المهام قيد التشغيل."""
    res = runner.delete_job(job_id)
    status = 200 if res.get("ok") else 400
    return JSONResponse(res, status_code=status)


@app.post("/api/jobs/delete-all")
async def jobs_delete_all():
    """يحذف كل المهام السابقة من القرص باستثناء المهمة النشطة حالياً."""
    return JSONResponse(runner.delete_all_jobs())


# v1.12.5 REFACTOR-app-routers: download endpoints (report/download/view/files/
# download-file/download-all) -> webapp/routers/downloads.py.


# نطاقات OAuth (قراءة فقط) لكلتا الخدمتين
_GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",   # Search Console
    "https://www.googleapis.com/auth/analytics.readonly",    # Analytics 4
]


def _probe_token_expired(token_path: Path) -> bool:
    """v1.06: يفحص بسرعة ما إن كان token Google منتهي الصلاحية (يحاول refresh صامتاً).

    Google في وضع «Testing» يُلغي refresh_token كلّ 7 أيام، فيظهر للمستخدم خطأ
    `invalid_grant` فقط حين يبدأ الزحف ويفشل التكامل في منتصفه. هذا الفحص يكتشف
    الحالة مبكّراً ويُمكّن الواجهة من إظهار «التفويض منتهٍ» قبل بدء أيّ مهمّة."""
    if not token_path.exists():
        return False
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        return False
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), _GOOGLE_SCOPES)
    except (OSError, ValueError):
        return True  # ملف تالف ⇒ يُعامَل كمنتهٍ كي يُعيد المستخدم الربط
    if creds.valid:
        return False
    if not creds.expired or not creds.refresh_token:
        return True
    try:
        creds.refresh(Request())
        # v1.09-B6: كتابة atomic — refresh ينتج access_token جديد، ولا نريد
        # crash منتصف الكتابة أن يُتلف الـtoken بأكمله.
        _atomic_write_text(token_path, creds.to_json())
        return False
    except Exception:  # noqa: BLE001
        return True  # refresh فشل (غالباً invalid_grant) ⇒ منتهٍ


@app.get("/api/google/status")
async def google_status():
    """حالة الاتصال: هل لدينا client_secret + tokens + هل الـtokens صالحة؟

    v1.06: نُضيف فحص نشط (`expired`) لاكتشاف Token الذي ألغته Google (Testing
    mode بعد 7 أيام) قبل بدء أيّ مهمّة، بدل اكتشافه مع أوّل فشل تكامل."""
    gd = _google_dir()
    cs = gd / "client_secret.json"
    gsc = gd / "gsc_token.json"
    ga4 = gd / "ga4_token.json"
    # فحص الانتهاء يستدعي شبكة (refresh) — نُشغّله في executor كي لا يحجب الحلقة
    loop = asyncio.get_event_loop()
    expired = False
    if gsc.exists() or ga4.exists():
        try:
            checks = await asyncio.gather(
                loop.run_in_executor(None, _probe_token_expired, gsc),
                loop.run_in_executor(None, _probe_token_expired, ga4),
            )
            expired = any(checks)
        except Exception:  # noqa: BLE001
            expired = False
    return JSONResponse({
        "client_secret": str(cs) if cs.exists() else None,
        "gsc_token": str(gsc) if gsc.exists() else None,
        "ga4_token": str(ga4) if ga4.exists() else None,
        "connected": gsc.exists() and ga4.exists(),
        "expired": expired,
    })


@app.post("/api/google/upload")
async def google_upload(file: UploadFile = File(...)):
    """رفع ملف OAuth client secret (Desktop) من المتصفّح."""
    # v1.10-C1 (M-3): MIME validation — نقبل application/json و text/* فقط.
    # ملف Google OAuth client_secret دائماً JSON. أيّ شيء آخر مرفوض.
    ctype = (file.content_type or "").lower().split(";")[0].strip()
    if ctype not in ("application/json", "text/plain", "text/json",
                     "application/octet-stream", ""):
        return JSONResponse(
            {"error": f"MIME type غير مقبول: {ctype}. متوقّع application/json."},
            status_code=400,
        )
    # ملف client secret صغير جداً (بضع كيلوبايت). نحدّ الحجم لمنع استنزاف الذاكرة.
    raw = await file.read()
    if len(raw) > 64 * 1024:
        return JSONResponse(
            {"error": "الملف أكبر من المتوقّع لملف client secret (الحدّ 64KB)."},
            status_code=400,
        )
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        return JSONResponse({"error": "ملف JSON غير صالح"}, status_code=400)
    if not isinstance(data, dict) or not ("installed" in data or "web" in data):
        return JSONResponse(
            {"error": "هذا ليس ملف OAuth client secret (يجب أن يحوي 'installed' أو 'web'). "
                      "أنشئه من: Google Cloud → Credentials → OAuth client ID → Desktop app."},
            status_code=400,
        )
    target = _google_dir() / "client_secret.json"
    target.write_bytes(raw)
    try:
        os.chmod(target, 0o600)
    except (OSError, NotImplementedError):
        pass
    return JSONResponse({"ok": True, "path": str(target)})


@app.post("/api/google/authorize")
async def google_authorize():
    """يفتح متصفّحاً للموافقة بحساب المستخدم ويحفظ token محلياً (مرّة واحدة)."""
    gd = _google_dir()
    cs = gd / "client_secret.json"
    if not cs.exists():
        return JSONResponse(
            {"error": "ارفع client_secret.json أولاً عبر زر «📤 رفع الملف»."},
            status_code=400,
        )

    def _run():
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(cs), _GOOGLE_SCOPES)
        creds = flow.run_local_server(port=0)  # يفتح المتصفح ويستقبل callback
        # v1.09-B6: كتابة atomic لكلا الـtokens
        for name in ("gsc_token.json", "ga4_token.json"):
            _atomic_write_text(gd / name, creds.to_json())
        return True

    try:
        await asyncio.get_event_loop().run_in_executor(None, _run)
    except ImportError:
        return JSONResponse(
            {"error": "ثبّت أولاً: pip install google-auth-oauthlib google-api-python-client "
                      "google-analytics-data"},
            status_code=500,
        )
    except Exception as e:
        log.exception("setup endpoint failed")
        return JSONResponse({"error": str(e)[:300]}, status_code=500)

    return JSONResponse({
        "ok": True,
        "client_secret": str(cs),
        "gsc_token": str(gd / "gsc_token.json"),
        "ga4_token": str(gd / "ga4_token.json"),
    })


@app.post("/api/google/disconnect")
async def google_disconnect(full: int = 0):
    """يحذف الـtokens المحفوظة. مع `?full=1` يحذف أيضاً client_secret (لتغييره)."""
    gd = _google_dir()
    names = ["gsc_token.json", "ga4_token.json"]
    if int(full or 0):
        names.append("client_secret.json")
    removed = []
    for name in names:
        p = gd / name
        if p.exists():
            try:
                p.unlink()
                removed.append(name)
            except OSError:
                pass
    return JSONResponse({"ok": True, "removed": removed})


@app.get("/api/google/gsc-sites")
async def google_gsc_sites():
    """قائمة مواقع GSC المتاحة للحساب الموثَّق — لتعبئة قائمة منسدلة في الواجهة."""
    gd = _google_dir()
    cs = gd / "client_secret.json"
    if not cs.exists() or not (gd / "gsc_token.json").exists():
        return JSONResponse({"sites": [], "error": "not_connected"})

    def _run():
        from integrations.gsc_api import GSCClient, parse_gsc_sites
        c = GSCClient(credentials_path=str(cs), site_url="https://example.com/")
        if not c.authenticate(allow_interactive=False):
            return {"sites": [], "error": "auth_failed"}
        try:
            return {"sites": parse_gsc_sites(c.service.sites().list().execute())}
        except Exception as e:  # noqa: BLE001
            log.exception("GSC sites list failed")
            return {"sites": [], "error": str(e)[:300]}

    return JSONResponse(await _run_conn_test(_run))


@app.get("/api/google/ga4-properties")
async def google_ga4_properties():
    """قائمة خصائص GA4 المتاحة للحساب الموثَّق."""
    gd = _google_dir()
    cs = gd / "client_secret.json"
    if not cs.exists() or not (gd / "ga4_token.json").exists():
        return JSONResponse({"properties": [], "error": "not_connected"})

    def _run():
        from integrations.ga4_api import list_ga4_properties
        return {"properties": list_ga4_properties(str(cs), allow_interactive=False)}

    return JSONResponse(await _run_conn_test(_run))


# === مسار «لصق الرمز» — احتياط للأجهزة بلا متصفّح/الخوادم البعيدة ===
# نحتفظ بكائن Flow مؤقتاً بين طلبَي url وcode (SCT محلية لمستخدم واحد).
_paste_flow: dict[str, Any] = {}
_PASTE_REDIRECT = "http://127.0.0.1:1/"  # لا نستمع — المتصفّح يفشل لكن الرمز يظهر في URL


def _save_google_tokens(gd: Path, creds: Any) -> None:
    """يحفظ token موحّداً يغطّي GSC + GA4 (نفس موافقة /authorize).
    v1.09-B6: كتابة atomic (temp + os.replace) — crash لا يُتلف الـtoken."""
    for name in ("gsc_token.json", "ga4_token.json"):
        _atomic_write_text(gd / name, creds.to_json())


def _extract_oauth_code(pasted: str) -> str:
    """يستخرج معامل `code` سواء أُدخِل كرمز خام أو كرابط callback كامل."""
    s = (pasted or "").strip()
    if not s:
        return ""
    if "code=" in s:
        from urllib.parse import urlparse, parse_qs
        try:
            qs = parse_qs(urlparse(s).query or s.split("?", 1)[-1])
            v = qs.get("code") or []
            if v:
                return v[0]
        except (ValueError, IndexError):
            pass
    return s


@app.get("/api/google/authorize-url")
async def google_authorize_url():
    """يعيد رابط موافقة Google لاستعماله مع لصق الرمز يدوياً (بلا متصفّح محلي)."""
    gd = _google_dir()
    cs = gd / "client_secret.json"
    if not cs.exists():
        return JSONResponse({"error": "ارفع client_secret.json أولاً."}, status_code=400)
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        return JSONResponse(
            {"error": "ثبّت: pip install google-auth-oauthlib"}, status_code=500)
    try:
        flow = Flow.from_client_secrets_file(str(cs), scopes=_GOOGLE_SCOPES)
        flow.redirect_uri = _PASTE_REDIRECT
        auth_url, _state = flow.authorization_url(
            access_type="offline", include_granted_scopes="true", prompt="consent")
        _paste_flow["flow"] = flow
        return JSONResponse({"auth_url": auth_url, "redirect_uri": _PASTE_REDIRECT})
    except Exception as e:  # noqa: BLE001
        log.exception("OAuth flow init failed")
        return JSONResponse({"error": str(e)[:300]}, status_code=500)


@app.post("/api/google/authorize-code")
async def google_authorize_code(code: str = Form("")):
    """يكمل التفويض بعد لصق المستخدم للرمز/رابط callback من المتصفّح."""
    extracted = _extract_oauth_code(code)
    if not extracted:
        return JSONResponse({"error": "ألصق الرمز أو رابط callback كاملاً."}, status_code=400)
    flow = _paste_flow.get("flow")
    if flow is None:
        return JSONResponse(
            {"error": "ابدأ من «احصل على رابط الموافقة» أولاً."}, status_code=400)
    try:
        flow.fetch_token(code=extracted)
        _save_google_tokens(_google_dir(), flow.credentials)
        _paste_flow.pop("flow", None)
        gd = _google_dir()
        return JSONResponse({
            "ok": True,
            "gsc_token": str(gd / "gsc_token.json"),
            "ga4_token": str(gd / "ga4_token.json"),
        })
    except Exception as e:  # noqa: BLE001
        log.exception("OAuth code exchange failed")
        return JSONResponse({"error": str(e)[:300]}, status_code=500)


# v1.12.4 REFACTOR-app-routers: setup + requirements + docs نُقلت إلى
#   webapp/routers/setup.py (POST/GET /api/setup/{tool}, GET /api/requirements,
#                            GET /docs/{name})

# === v1.02: توليد التقارير عند الطلب — بدل توليد الكل أثناء الزحف ===
# الزحف يُنتج دائماً CSV+JSON (سريعة ورخيصة)؛ HTML/PDF/Excel/XML تُطلَب من زرّ منفصل
# لكلّ تنسيق، مع شريط تقدّم خاص بها. هذا يختصر وقت/مساحة الجوب الرئيسي.
# v1.02: HTML/PDF عند الطلب. v1.04: أُضيف Excel + XML — يُعاد بناؤهما من audit JSON +
# ملفّات CSV الحاضرة دائماً في مجلّد المخرجات. هكذا يستطيع المستخدم تشغيل زحف خفيف
# بـCSV+JSON فقط، ثم يُولِّد التنسيقات الأثقل عند الحاجة (يختصر وقتاً ومساحة).
_GEN_VALID_FORMATS = {"html", "pdf", "excel", "xml"}
_gen_state: dict[str, dict[str, dict[str, Any]]] = {}   # {job_id: {fmt: {running, ok, message}}}
_gen_lock = __import__("threading").Lock()


def _run_generate_bg(job_id: str, fmt: str, options: dict[str, Any]) -> None:
    """ينفّذ توليد تنسيق واحد في الخلفية لمهمّة منتهية."""
    import importlib
    err = ""
    ok = False
    try:
        meta = runner.meta(job_id)
        json_path = (meta.get("result") or {}).get("json")
        if not json_path or not Path(json_path).exists():
            raise RuntimeError("no audit JSON for this job")
        size_mb = Path(json_path).stat().st_size / (1024 * 1024)
        if size_mb > MAX_AUDIT_JSON_MB:
            raise RuntimeError(f"audit JSON too large ({size_mb:.0f} MB)")

        out_dir = str(Path(json_path).parent)
        if fmt in ("html", "pdf"):
            mod = importlib.import_module("exporters.report_builder")
            make_pdf = (fmt == "pdf")
            mod.build_report_from_json(json_path, out_dir, options, make_pdf)
        elif fmt == "excel":
            _regen_excel_from_outputs(Path(out_dir), Path(json_path))
        elif fmt == "xml":
            _regen_xml_from_outputs(Path(out_dir), Path(json_path))
        else:
            raise RuntimeError(f"unknown format: {fmt}")
        ok = True
        # تحديث meta.result كي تظهر روابط التنزيل الجديدة
        meta = runner.meta(job_id)
        new_result = runner._discover_result(Path(out_dir).parent, meta.get("mode", "audit"))
        meta["result"] = new_result
        runner._write_meta(Path(out_dir).parent, meta)
    except Exception as e:  # noqa: BLE001
        log.exception("report regeneration failed")
        err = f"{type(e).__name__}: {str(e)[:300]}"

    with _gen_lock:
        _gen_state.setdefault(job_id, {})[fmt] = {
            "running": False, "ok": ok, "message": err,
        }


def _load_csv_rows(p: Path) -> list[dict[str, Any]]:
    """يقرأ ملفّ CSV ويُرجعه كقائمة قواميس (فارغ إن لم يوجد)."""
    if not p.exists():
        return []
    import csv as _csv
    rows: list[dict[str, Any]] = []
    try:
        with open(p, "r", encoding="utf-8", newline="") as f:
            for row in _csv.DictReader(f):
                rows.append(dict(row))
    except OSError:
        return []
    return rows


def _regen_excel_from_outputs(out_dir: Path, json_path: Path) -> None:
    """v1.04: يُعيد بناء Excel من audit JSON + ملفّات CSV الموجودة. CSV هو المصدر
    الأوثق للمصفوفات الكبيرة (links/images/headings) لأنّ JSON قد يحذفها لتوفير الحجم."""
    from utils.auto_install import ensure_package
    ensure_package("openpyxl")
    from exporters.excel_exporter import ExcelExporter

    with open(json_path, "r", encoding="utf-8") as f:
        audit = json.load(f)

    csv_dir = out_dir / "csv"
    pages = audit.get("pages") or _load_csv_rows(csv_dir / "pages.csv")
    links = audit.get("links") or _load_csv_rows(csv_dir / "all_links.csv")
    images = audit.get("images") or _load_csv_rows(csv_dir / "images.csv")
    headings = audit.get("headings") or _load_csv_rows(csv_dir / "headings.csv")
    schema = audit.get("schema") or _load_csv_rows(csv_dir / "schema.csv")
    redirects = audit.get("redirects") or _load_csv_rows(csv_dir / "redirects.csv")
    headers = _load_csv_rows(csv_dir / "headers.csv")

    site_url = (audit.get("site_config") or {}).get("start_url", "")
    excel_name = f"audit_{json_path.stem.replace('audit_', '')}.xlsx"

    ExcelExporter(str(out_dir), excel_name).export(
        pages=pages, links=links, images=images, headings=headings,
        schema=schema, redirects=redirects, headers=headers,
        seo_issues=audit.get("seo_issues", {}),
        duplicate_data=audit.get("duplicate_data", {}),
        orphan_data=audit.get("orphan_data", {}),
        thin_content_data=audit.get("thin_content_data", {}),
        broken_data=audit.get("broken_data", {}),
        images_analysis=audit.get("images_analysis", {}),
        crawl_stats=None,
        site_url=site_url,
    )


def _regen_xml_from_outputs(out_dir: Path, json_path: Path) -> None:
    """v1.04: يُعيد بناء ملفّات XML من audit JSON + CSV (نفس فكرة Excel)."""
    from exporters.xml_exporter import XMLExporter

    with open(json_path, "r", encoding="utf-8") as f:
        audit = json.load(f)

    csv_dir = out_dir / "csv"
    pages = audit.get("pages") or _load_csv_rows(csv_dir / "pages.csv")
    links = audit.get("links") or _load_csv_rows(csv_dir / "all_links.csv")
    images = audit.get("images") or _load_csv_rows(csv_dir / "images.csv")
    schema = audit.get("schema") or _load_csv_rows(csv_dir / "schema.csv")

    XMLExporter(str(out_dir / "xml")).export_all(
        pages=pages, links=links, images=images, schema=schema,
        seo_issues=audit.get("seo_issues", {}),
    )


@app.post("/api/jobs/{job_id}/generate")
async def jobs_generate(
    job_id: str,
    format: str = Form(...),
    language: str = Form("ar"),
    client_name: str = Form(""),
    audience: str = Form("expert"),
    logo_url: str = Form(""),
    max_rows: int = Form(100),
):
    """يُولّد تنسيقاً واحداً (html/pdf/excel/xml) عند الطلب من صفحة المهمّة."""
    fmt = (format or "").lower().strip()
    if fmt not in _GEN_VALID_FORMATS:
        return JSONResponse({"error": "invalid format"}, status_code=400)
    if not runner.meta(job_id):
        return JSONResponse({"error": "job not found"}, status_code=404)
    with _gen_lock:
        cur = (_gen_state.get(job_id) or {}).get(fmt)
        if cur and cur.get("running"):
            return JSONResponse({"started": False, "running": True})
        _gen_state.setdefault(job_id, {})[fmt] = {
            "running": True, "ok": None, "message": "",
        }
    options = {
        "language": language, "audience": audience, "client_name": client_name,
        "logo_url": logo_url, "max_rows": max_rows,
    }
    import threading
    threading.Thread(
        target=_run_generate_bg, args=(job_id, fmt, options), daemon=True
    ).start()
    return JSONResponse({"started": True, "format": fmt})


@app.get("/api/jobs/{job_id}/generate/{fmt}/status")
async def jobs_generate_status(job_id: str, fmt: str):
    """يستفسر عن حالة توليد تنسيق واحد لمهمّة."""
    with _gen_lock:
        st = (_gen_state.get(job_id) or {}).get(fmt) or {
            "running": False, "ok": None, "message": "",
        }
    return JSONResponse(st)

# v1.12.5 REFACTOR-app-routers: analytics endpoints + _build_graph_payload نُقلت
# إلى webapp/routers/analytics.py.

