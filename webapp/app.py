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

app = FastAPI(title="SCT — Simple Crawler Tool")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


# v1.09-B3: حماية CSRF — على أيّ POST، إن وُجد `Origin` ولم يُطابق مضيف الـapp،
# نرفض الطلب. هذا يحمي من صفحة خبيثة في متصفّحك تستطيع POST إلى /api/start أو
# /api/jobs/.../delete أو غيرها من endpoints تغيّر الحالة. localhost استثناء
# (CLI/Cookie pasted URL لا يُرسل Origin → نسمح بها لأنّها ليست cross-origin).
@app.middleware("http")
async def _csrf_origin_guard(request, call_next):
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return await call_next(request)
    origin = request.headers.get("origin") or ""
    if not origin:
        # cURL / fetch from localhost CLI لا يُرسل Origin — نسمح بها
        return await call_next(request)
    # نسمح فقط بـlocalhost (سواء بأيّ منفذ)
    try:
        from urllib.parse import urlparse
        host = (urlparse(origin).hostname or "").lower()
    except Exception:  # noqa: BLE001
        host = ""
    if host in ("127.0.0.1", "localhost", "::1"):
        return await call_next(request)
    return JSONResponse(
        {"error": "Cross-origin POST blocked (CSRF protection). "
                  "Open SCT via http://127.0.0.1:8000 in the same tab."},
        status_code=403,
    )


runner = JobRunner()

# حالات الانتهاء (لإغلاق بثّ SSE)
FINISHED_STATUSES = {"complete", "partial", "partial_max_pages", "done", "failed", "stopped"}

# مجموعات ما يُجمَع (extraction) — تُعرض كأقسام قابلة للطيّ في الواجهة
EXTRACTION_GROUPS = [
    {"id": "content", "label": "الميتا والمحتوى", "items": [
        {"key": "meta", "label": "الوسوم الوصفية (Title/Description/Robots)"},
        {"key": "headings", "label": "العناوين (H1–H6)"},
        {"key": "content", "label": "المحتوى وعدد الكلمات"},
        {"key": "canonical", "label": "Canonical"},
    ]},
    {"id": "links_media", "label": "الروابط والوسائط", "items": [
        {"key": "links", "label": "الروابط (داخلية/خارجية)"},
        {"key": "images", "label": "الصور و alt"},
    ]},
    {"id": "social", "label": "السوشال والبيانات المنظمة", "items": [
        {"key": "og", "label": "Open Graph / Twitter"},
        {"key": "hreflang", "label": "Hreflang"},
        {"key": "pagination", "label": "ترقيم الصفحات (rel=next/prev)"},
        {"key": "schema", "label": "Schema.org"},
    ]},
    {"id": "technical", "label": "التقني والأمان", "items": [
        {"key": "headers", "label": "ترويسات HTTP"},
        {"key": "mixed_content", "label": "المحتوى المختلط (Mixed Content)"},
        {"key": "resources", "label": "جرد الموارد (CSS/JS/خطوط/iframe)"},
    ]},
]

OUTPUT_FORMATS = [
    {"key": "html", "label": "HTML", "default": True},
    {"key": "pdf", "label": "PDF", "default": True},
    {"key": "excel", "label": "Excel", "default": True},
    {"key": "csv", "label": "CSV", "default": True},
    {"key": "json", "label": "JSON", "default": True},
    {"key": "xml", "label": "XML", "default": False},
]

SECTIONS = [
    {"key": "cover", "label": "الغلاف"},
    {"key": "summary", "label": "الملخص التنفيذي"},
    {"key": "issues", "label": "المشاكل حسب الأولوية"},
    {"key": "problem_pages", "label": "صفحات بمشاكل"},
    {"key": "redirects", "label": "التحويلات"},
    {"key": "schema", "label": "Schema.org"},
]
SEVERITIES = ["🔴 Critical", "🟠 High", "🟡 Medium", "🟢 Low"]

# v1.05: انتحال User-Agent لكشف مشاكل خاصّة بـbots (Cloudflare/WAF challenges)
# الـUA الافتراضي «SEOCrawlerBot/1.0» (في crawler/http_client.py) يبقى عند `ua_preset=""`.
_UA_PRESETS = {
    "googlebot": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "googlebot-mobile": (
        "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.6099.118 Mobile Safari/537.36 "
        "(compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    ),
    "bingbot": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
}

# سقف حجم ملف audit JSON الذي نحمّله في الذاكرة (المستكشف/إعادة بناء التقرير).
# يمنع تعليق الخادم عند فتح أرشيف ضخم (مثل 1.7GB من زحف غير محدود قديم).
MAX_AUDIT_JSON_MB = 300

# تسميات معبّرة (عربي/إنجليزي) لملفات CSV المختصّة — تُعرض في لوحة النتائج.
CSV_LABELS: dict[str, dict[str, str]] = {
    "pages": {"ar": "كل الصفحات المزحوفة", "en": "All crawled pages"},
    "all_links": {"ar": "كل الروابط (شبكة الروابط)", "en": "All links (link graph)"},
    "inlinks": {"ar": "الروابط الواردة الداخلية", "en": "Internal inlinks"},
    "outlinks_external": {"ar": "الروابط الصادرة الخارجية", "en": "External outlinks"},
    "images": {"ar": "كل الصور", "en": "All images"},
    "images_no_alt": {"ar": "صور بلا نص بديل (alt)", "en": "Images missing alt text"},
    "images_no_dimensions": {"ar": "صور بلا أبعاد صريحة", "en": "Images missing dimensions"},
    "headings": {"ar": "العناوين H1–H6", "en": "Headings (H1–H6)"},
    "headers": {"ar": "ترويسات HTTP", "en": "HTTP response headers"},
    "schema": {"ar": "البيانات المنظّمة Schema.org", "en": "Schema.org structured data"},
    "redirects": {"ar": "التحويلات", "en": "Redirects"},
    "redirect_chains": {"ar": "سلاسل التحويل", "en": "Redirect chains"},
    "redirect_loops": {"ar": "حلقات التحويل", "en": "Redirect loops"},
    "redirect_issues": {"ar": "مشاكل التحويلات", "en": "Redirect issues"},
    "seo_issues": {"ar": "كل مشاكل SEO (حسب الأولوية)", "en": "All SEO issues (by priority)"},
    "duplicates": {"ar": "محتوى مكرّر (عناوين/أوصاف/H1)", "en": "Duplicate content (titles/desc/H1)"},
    "orphans": {"ar": "صفحات يتيمة", "en": "Orphan pages"},
    "low_link_pages": {"ar": "صفحات قليلة الروابط الداخلية", "en": "Pages with few internal links"},
    "thin_content": {"ar": "محتوى رقيق", "en": "Thin‑content pages"},
    "pages_4xx": {"ar": "صفحات أخطاء 4xx", "en": "4xx error pages"},
    "pages_5xx": {"ar": "صفحات أخطاء 5xx", "en": "5xx error pages"},
    "pages_404_with_inlinks": {"ar": "صفحات 404 بروابط واردة", "en": "404 pages with inlinks"},
    "url_issues": {"ar": "مشاكل الروابط (URL)", "en": "URL issues"},
    "canonical_issues": {"ar": "مشاكل Canonical", "en": "Canonical issues"},
    "security_issues": {"ar": "مشاكل ترويسات الأمان", "en": "Security header issues"},
    "pagination": {"ar": "ترقيم الصفحات (next/prev)", "en": "Pagination (next/prev)"},
    "pagination_issues": {"ar": "مشاكل ترقيم الصفحات", "en": "Pagination issues"},
    "hreflang_issues": {"ar": "مشاكل hreflang", "en": "Hreflang issues"},
    "resources": {"ar": "جرد الموارد", "en": "Resource inventory"},
    "resource_issues": {"ar": "مشاكل الموارد", "en": "Resource issues"},
    "resource_status": {"ar": "حالة HTTP للموارد", "en": "Resource HTTP status"},
    "excluded_urls": {"ar": "روابط مستبعَدة (مع السبب)", "en": "Excluded URLs (with reason)"},
    "priority_opportunities": {"ar": "أولويات الإصلاح", "en": "Priority opportunities"},
    "ai_recommendations": {"ar": "توصيات الذكاء الاصطناعي", "en": "AI recommendations"},
    "gsc_pages": {"ar": "GSC — صفحات", "en": "GSC — pages"},
    "gsc_queries": {"ar": "GSC — استعلامات", "en": "GSC — queries"},
    "ga4_landing_pages": {"ar": "GA4 — صفحات الهبوط", "en": "GA4 — landing pages"},
    "ga4_channels": {"ar": "GA4 — القنوات", "en": "GA4 — channels"},
    "lighthouse_import": {"ar": "استيراد Lighthouse", "en": "Lighthouse import"},
    "js_diff": {"ar": "فرق التصيير (خام↔مُصيَّر)", "en": "JS render diff (raw↔rendered)"},
    "custom_extraction": {"ar": "الاستخراج المخصّص", "en": "Custom extraction"},
}


def _label_for(rel: str, lang: str = "ar") -> str:
    """تسمية معبّرة لملف ناتج حسب مساره النسبي."""
    name = Path(rel).name
    stem = Path(name).stem
    low = name.lower()
    if rel.startswith("csv/") and stem in CSV_LABELS:
        return CSV_LABELS[stem][lang]
    if low.endswith(".json"):
        return "الأرشيف الكامل (JSON)" if lang == "ar" else "Full audit archive (JSON)"
    if low.endswith(".xlsx"):
        return "مصنّف Excel" if lang == "ar" else "Excel workbook"
    if "_client" in low and low.endswith(".html"):
        return "تقرير العميل (HTML)" if lang == "ar" else "Client report (HTML)"
    if "_client" in low and low.endswith(".pdf"):
        return "تقرير العميل (PDF)" if lang == "ar" else "Client report (PDF)"
    if "_expert" in low and low.endswith(".html"):
        return "تقرير الخبير (HTML)" if lang == "ar" else "Expert report (HTML)"
    if "_expert" in low and low.endswith(".pdf"):
        return "تقرير الخبير (PDF)" if lang == "ar" else "Expert report (PDF)"
    if low.endswith(".html"):
        return "التقرير (HTML)" if lang == "ar" else "Report (HTML)"
    if low.endswith(".pdf"):
        return "التقرير (PDF)" if lang == "ar" else "Report (PDF)"
    if rel.startswith("xml/"):
        return f"XML — {stem}"
    if rel.startswith("csv/"):
        return stem.replace("_", " ")
    return name


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "jobs": runner.list_jobs()[:15],
         "groups": EXTRACTION_GROUPS, "formats": OUTPUT_FORMATS,
         "sections": SECTIONS, "severities": SEVERITIES,
         "active_job": runner.active_job()},
    )


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


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_page(request: Request, job_id: str):
    meta = runner.meta(job_id)
    return templates.TemplateResponse(
        "job.html", {"request": request, "job_id": job_id, "meta": meta}
    )


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


@app.post("/api/jobs/{job_id}/report")
async def job_report(
    job_id: str,
    language: str = Form("ar"),
    client_name: str = Form(""),
    audience: str = Form("expert"),
    make_pdf: bool = Form(True),
):
    """إعادة بناء تقرير HTML/PDF بخيارات مخصّصة من نتائج مهمة منتهية."""
    meta = runner.meta(job_id)
    result = meta.get("result", {})
    json_path = result.get("json")
    if not json_path or not Path(json_path).exists():
        return JSONResponse({"error": "no audit json for this job"}, status_code=404)
    size_mb = Path(json_path).stat().st_size / (1024 * 1024)
    if size_mb > MAX_AUDIT_JSON_MB:
        return JSONResponse({
            "error": f"audit JSON too large ({size_mb:.0f} MB) to rebuild from; "
                     f"re-run the crawl with the current version (smaller JSON) "
                     f"or set a page limit",
        }, status_code=413)

    from exporters.report_builder import build_report_from_json

    out_dir = str(Path(json_path).parent)
    if audience not in ("client", "expert", "both"):
        audience = "expert"
    options = {"language": language, "client_name": client_name, "audience": audience}
    report = await asyncio.get_event_loop().run_in_executor(
        None, lambda: build_report_from_json(json_path, out_dir, options, make_pdf)
    )
    return JSONResponse(report)


def _safe_under_jobs(path: str) -> Path | None:
    """يتأكّد أن الملف داخل مجلد المهام (دفاع عميق ضد قراءة ملفات عشوائية)."""
    from webapp.job_runner import JOBS_DIR
    try:
        rp = Path(path).resolve()
        rp.relative_to(JOBS_DIR.resolve())
        return rp if rp.exists() else None
    except (ValueError, OSError):
        return None


@app.get("/api/jobs/{job_id}/download/{kind}")
async def download(job_id: str, kind: str):
    # v1.09-B4: حماية path traversal — `job_id` يدخل tempfile prefix أدناه قبل أيّ
    # تحقّق آخر؛ بدون هذا، `..\foo` ينشئ ملفّاً خارج tempdir على Windows.
    from webapp.job_runner import _valid_job_id
    if not _valid_job_id(job_id):
        return JSONResponse({"error": "invalid job_id"}, status_code=400)
    # v1.04: kind=xml يجمع كلّ ملفّات مجلّد xml/ في ZIP واحد لأنّه عدّة ملفّات لا ملفّ واحد
    if kind == "xml":
        out = _job_output_dir(job_id)
        if not out:
            return JSONResponse({"error": "no output"}, status_code=404)
        xml_dir = out / "xml"
        if not xml_dir.exists():
            return JSONResponse({"error": "xml folder not built yet"}, status_code=404)
        tmp = tempfile.NamedTemporaryFile(prefix=f"sct_{job_id}_xml_", suffix=".zip", delete=False)
        tmp.close()
        def _build():
            with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for p in sorted(xml_dir.glob("*.xml")):
                    if p.is_file():
                        zf.write(p, arcname=f"xml/{p.name}")
        await asyncio.get_event_loop().run_in_executor(None, _build)
        return FileResponse(
            tmp.name, media_type="application/zip",
            filename=f"sct_{job_id}_xml.zip",
            background=BackgroundTask(lambda: os.path.exists(tmp.name) and os.unlink(tmp.name)),
        )

    meta = runner.meta(job_id)
    path = (meta.get("result", {}) or {}).get(kind)
    safe = _safe_under_jobs(path) if path else None
    if not safe:
        return JSONResponse({"error": "file not found"}, status_code=404)
    return FileResponse(str(safe), filename=safe.name)


@app.get("/api/jobs/{job_id}/view")
async def view_html(job_id: str):
    meta = runner.meta(job_id)
    path = (meta.get("result", {}) or {}).get("html")
    safe = _safe_under_jobs(path) if path else None
    if not safe:
        return JSONResponse({"error": "no html report"}, status_code=404)
    return FileResponse(str(safe), media_type="text/html")


def _job_output_dir(job_id: str) -> Path | None:
    """مجلد مخرجات المهمة بعد التحقّق من صيغة المعرّف."""
    from webapp.job_runner import JOBS_DIR, _valid_job_id
    if not _valid_job_id(job_id):
        return None
    out = (JOBS_DIR / job_id / "output").resolve()
    return out if out.exists() else None


def _safe_output_file(job_id: str, rel: str) -> Path | None:
    """يحوّل مساراً نسبياً إلى ملف داخل مجلد مخرجات المهمة بأمان (منع traversal)."""
    out = _job_output_dir(job_id)
    if not out:
        return None
    try:
        target = (out / rel).resolve()
        target.relative_to(out)            # يجب أن يبقى داخل output/
        return target if target.is_file() else None
    except (ValueError, OSError):
        return None


@app.get("/api/jobs/{job_id}/files")
async def job_files(job_id: str, lang: str = "ar"):
    """قائمة كل الملفات الناتجة مع تسمية معبّرة وحجم — للتنزيل المنفصل/الجماعي."""
    out = _job_output_dir(job_id)
    if not out:
        return JSONResponse({"files": [], "error": "no output"}, status_code=404)
    lang = "en" if str(lang).lower().startswith("en") else "ar"
    groups: dict[str, str] = {
        "report": "التقارير" if lang == "ar" else "Reports",
        "workbook": "Excel",
        "archive": "الأرشيف" if lang == "ar" else "Archive",
        "data": "بيانات CSV" if lang == "ar" else "CSV data",
        "xml": "XML",
    }
    files = []
    for p in sorted(out.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(out).as_posix()
        low = rel.lower()
        if low.endswith((".html", ".pdf")):
            group = "report"
        elif low.endswith(".xlsx"):
            group = "workbook"
        elif low.endswith(".json"):
            group = "archive"
        elif rel.startswith("xml/"):
            group = "xml"
        elif rel.startswith("csv/") or low.endswith(".csv"):
            group = "data"
        else:
            group = "data"
        files.append({
            "rel": rel,
            "label": _label_for(rel, lang),
            "size": p.stat().st_size,
            "group": group,
        })
    return JSONResponse({"files": files, "groups": groups})


@app.get("/api/jobs/{job_id}/download-file")
async def download_file(job_id: str, rel: str):
    """تنزيل ملف ناتج محدّد عبر مساره النسبي داخل مجلد المخرجات."""
    safe = _safe_output_file(job_id, rel)
    if not safe:
        return JSONResponse({"error": "file not found"}, status_code=404)
    return FileResponse(str(safe), filename=safe.name)


@app.get("/api/jobs/{job_id}/download-all")
async def download_all(job_id: str, only: str = ""):
    """تنزيل كل المخرجات (أو مجموعة مختارة عبر only=rel1,rel2) كملف ZIP واحد."""
    out = _job_output_dir(job_id)
    if not out:
        return JSONResponse({"error": "no output"}, status_code=404)

    wanted: set[str] | None = None
    if only.strip():
        wanted = set()
        for rel in only.split(","):
            safe = _safe_output_file(job_id, rel.strip())
            if safe:
                wanted.add(safe.relative_to(out).as_posix())
        if not wanted:
            return JSONResponse({"error": "no valid files selected"}, status_code=400)

    tmp = tempfile.NamedTemporaryFile(prefix=f"sct_{job_id}_", suffix=".zip", delete=False)
    tmp.close()

    def _build_zip() -> None:
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for p in sorted(out.rglob("*")):
                if not p.is_file():
                    continue
                rel = p.relative_to(out).as_posix()
                if wanted is not None and rel not in wanted:
                    continue
                zf.write(p, arcname=rel)

    try:
        # الضغط متزامن وقد يكون كبيراً — ننفّذه في خيط منفصل كي لا نجمّد حلقة الأحداث.
        await asyncio.get_event_loop().run_in_executor(None, _build_zip)
    except OSError:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        return JSONResponse({"error": "failed to build archive"}, status_code=500)

    return FileResponse(
        tmp.name,
        media_type="application/zip",
        filename=f"sct_{job_id}_outputs.zip",
        background=BackgroundTask(lambda: os.path.exists(tmp.name) and os.unlink(tmp.name)),
    )


# ============================================================
# === ربط Google (GA4 + GSC) من الواجهة بدلاً من سطر الأوامر
# ============================================================

# نطاقات OAuth (قراءة فقط) لكلتا الخدمتين
_GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",   # Search Console
    "https://www.googleapis.com/auth/analytics.readonly",    # Analytics 4
]


def _google_dir() -> Path:
    """مجلد آمن لحفظ ملف client_secret والـtokens (خارج Git)."""
    from webapp.job_runner import JOBS_DIR
    d = JOBS_DIR / "_google"
    d.mkdir(parents=True, exist_ok=True)
    return d


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


def _atomic_write_text(target: Path, text: str, *, mode: int = 0o600) -> None:
    """v1.09-B6: كتابة نصّ atomic (temp + os.replace) — يُستعمل لكلّ ملفّات
    الـtokens كي لا يُتلِفها Ctrl-C أو crash في منتصف الكتابة."""
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        os.chmod(tmp, mode)
    except (OSError, NotImplementedError):
        pass
    os.replace(tmp, target)


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
        return JSONResponse({"error": str(e)[:300]}, status_code=500)


# تثبيت المتطلبات يعمل في الخلفية ثم نستفسر عن الحالة — لأنّ التثبيت قد يستغرق
# دقائق (تنزيل من الإنترنت) فيسقط اتصال fetch المتصفّح («Failed to fetch») إن انتظرناه.
_SETUP_CMDS = {
    "ga4_lib": [sys.executable, "-m", "pip", "install", "google-analytics-data"],
    "playwright": [sys.executable, "-m", "playwright", "install", "chromium"],
}
_setup_state: dict[str, dict[str, Any]] = {}
_setup_lock = __import__("threading").Lock()


def _run_setup_bg(tool: str) -> None:
    import subprocess
    cmd = _SETUP_CMDS[tool]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        ok = r.returncode == 0
        msg = (r.stdout if ok else (r.stderr or r.stdout or "")) or ""
    except Exception as e:  # noqa: BLE001
        ok, msg = False, f"{type(e).__name__}: {e}"
    with _setup_lock:
        _setup_state[tool] = {"running": False, "ok": ok, "message": msg[-600:]}


async def _run_conn_test(fn, timeout: float = 45.0) -> dict:
    """يشغّل اختبار اتصال محجوب (شبكة) في خيط مع مهلة قصوى.

    اختبارات الاتصال غير تفاعلية (لا تفتح متصفّح OAuth) ومحدودة بمهلة، كي لا يتعلّق
    الطلب إلى ما لا نهاية (كان اختبار GA4 يفتح تدفّق OAuth ويتعلّق حتى إيقاف الخادم)."""
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(loop.run_in_executor(None, fn), timeout=timeout)
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"انتهت مهلة الاختبار ({int(timeout)}ث) — تحقّق من الشبكة/الصلاحيات."}


@app.post("/api/test/gsc")
async def test_gsc(site_url: str = Form("")):
    """اختبار اتصال GSC: يصادق ويسرد المواقع التي يملك الحساب صلاحيتها — يكشف فوراً
    إن كان موقع العميل متاحاً أم يحتاج منحه صلاحية."""
    gd = _google_dir()
    cs = gd / "client_secret.json"
    if not cs.exists():
        return JSONResponse({"ok": False, "error": "لم يُربط Google بعد (ارفع client_secret ثم «وافق»)."})

    def _run():
        from integrations.gsc_api import GSCClient
        c = GSCClient(credentials_path=str(cs), site_url=site_url or "https://example.com/")
        # غير تفاعلي: لا نفتح متصفّح موافقة هنا — التفويض يتم عبر زرّ «وافق» فقط
        if not c.authenticate(allow_interactive=False):
            return {"ok": False, "error": "لم يُكمَل التفويض بعد — اضغط «وافق بحسابي» أولاً."}
        try:
            resp = c.service.sites().list().execute()
            sites = [s.get("siteUrl", "") for s in resp.get("siteEntry", [])]
            return {"ok": True, "sites": sites}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:300]}

    res = await _run_conn_test(_run)
    if res.get("ok") and site_url:
        target = site_url.rstrip("/")
        res["site_accessible"] = any(
            (s or "").rstrip("/") == target or target in (s or "")
            for s in res.get("sites", [])
        )
    return JSONResponse(res)


@app.post("/api/test/ga4")
async def test_ga4(property_id: str = Form("")):
    """اختبار اتصال GA4: محاولة تقرير صغير على property_id."""
    if not property_id.strip():
        return JSONResponse({"ok": False, "error": "أدخل GA4 property_id."})
    gd = _google_dir()
    cs = gd / "client_secret.json"
    if not cs.exists():
        return JSONResponse({"ok": False, "error": "لم يُربط Google بعد (ارفع client_secret ثم «وافق»)."})

    def _run():
        from integrations.ga4_api import GA4Client
        c = GA4Client(property_id=property_id.strip(), credentials_file=str(cs))
        # غير تفاعلي: لا نفتح متصفّح موافقة هنا (كان يتعلّق الطلب) — التفويض عبر زرّ «وافق»
        if not c.authenticate(allow_interactive=False):
            return {"ok": False, "error": "لم يُكمَل التفويض بعد — اضغط «وافق بحسابي»، وتأكّد من "
                                          "تثبيت مكتبة GA4 وأن الحساب مُضاف للـProperty."}
        try:
            c._run(dimensions=["date"], metrics=["sessions"], limit=1)
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:300]}

    return JSONResponse(await _run_conn_test(_run))


@app.post("/api/test/pagespeed")
async def test_pagespeed(api_key: str = Form("")):
    """اختبار مفتاح PageSpeed بفحص صفحة معروفة."""
    if not api_key.strip():
        return JSONResponse({"ok": False, "error": "أدخل مفتاح PageSpeed API."})

    def _run():
        from integrations.pagespeed_api import PageSpeedClient
        c = PageSpeedClient(api_key=api_key.strip(), timeout=60)
        r = c.audit("https://www.google.com/", strategy="mobile", categories=["performance"])
        return {"ok": False, "error": r["error"]} if r.get("error") else {"ok": True}

    return JSONResponse(await _run_conn_test(_run, timeout=75.0))


@app.post("/api/setup/{tool}")
async def setup_install(tool: str):
    """يبدأ تثبيت متطلّب في الخلفية ويعود فوراً (راجع الحالة عبر /api/setup/{tool}/status)."""
    if tool not in _SETUP_CMDS:
        return JSONResponse({"error": "أداة غير معروفة"}, status_code=404)
    with _setup_lock:
        cur = _setup_state.get(tool)
        if cur and cur.get("running"):
            return JSONResponse({"started": False, "running": True})
        _setup_state[tool] = {"running": True, "ok": None, "message": ""}
    import threading
    threading.Thread(target=_run_setup_bg, args=(tool,), daemon=True).start()
    return JSONResponse({"started": True, "running": True})


@app.get("/api/setup/{tool}/status")
async def setup_status(tool: str):
    if tool not in _SETUP_CMDS:
        return JSONResponse({"error": "أداة غير معروفة"}, status_code=404)
    with _setup_lock:
        st = _setup_state.get(tool) or {"running": False, "ok": None, "message": ""}
    return JSONResponse(st)


# === v1.02: شريط جاهزية المتطلبات الاختيارية ===
# نسبر التوفّر مرّة واحدة بعد الإقلاع ونُخزّن النتيجة. يُعاد السبر فقط عند طلب صريح أو بعد
# تثبيت ناجح كي لا نُدخل تأخيراً في كل تحميل صفحة (في بعض الأنظمة استيراد playwright
# بطيء — قد يأخذ ~300ms).
_REQUIREMENTS_PROBES = {
    "excel": ("openpyxl", None),                       # مكتبة Python
    "ga4": ("google.analytics.data_v1beta", None),     # مكتبة Python
    "pdf": ("playwright", "chromium_present"),         # Python + متصفّح Chromium مثبَّت
}
_requirements_cache: dict[str, dict[str, Any]] | None = None


def _probe_requirements() -> dict[str, dict[str, Any]]:
    """يُعيد قاموساً {tool: {present, version, note}} لكل متطلّب اختياري."""
    import importlib
    out: dict[str, dict[str, Any]] = {}
    for tool, (module_name, extra_check) in _REQUIREMENTS_PROBES.items():
        info: dict[str, Any] = {"present": False, "version": None, "note": ""}
        try:
            mod = importlib.import_module(module_name)
            info["present"] = True
            info["version"] = getattr(mod, "__version__", None) or ""
        except ImportError:
            out[tool] = info
            continue
        # فحص إضافي خاص بـ Playwright: متصفّح Chromium مثبَّت فعلاً؟
        if extra_check == "chromium_present":
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    info["present"] = bool(p.chromium.executable_path)
                    if not info["present"]:
                        info["note"] = "playwright OK but chromium not installed"
            except Exception:  # noqa: BLE001
                # حتى لو فشل الفحص العميق نُبقي info كما هو (المكتبة موجودة على الأقلّ)
                info["note"] = "chromium check failed"
        out[tool] = info
    return out


@app.get("/api/requirements")
async def get_requirements(refresh: int = 0):
    """v1.02: حالة المتطلبات الاختيارية للواجهة (Excel/GA4/PDF Chromium)."""
    global _requirements_cache
    if _requirements_cache is None or refresh:
        loop = asyncio.get_event_loop()
        _requirements_cache = await loop.run_in_executor(None, _probe_requirements)
    return JSONResponse({"items": _requirements_cache})


# === v1.02: خدمة وثائق المشروع كـMarkdown للواجهة (روابط «دليل…») ===
_DOCS_MAP = {
    "oauth_setup": ("OAUTH_SETUP.md", "إعداد OAuth و Google Cloud — SCT"),
    "ga4_property_id": ("GA4_PROPERTY_ID.md", "اكتشاف GA4 property_id — SCT"),
}


@app.get("/docs/{name}")
async def serve_doc(name: str):
    """يخدم ملفّاً من مجلّد docs/ كـHTML مُبسَّط (للروابط من واجهة البرنامج)."""
    entry = _DOCS_MAP.get(name)
    if not entry:
        return JSONResponse({"error": "doc not found"}, status_code=404)
    fname, title = entry
    fpath = ROOT / "docs" / fname
    if not fpath.exists():
        return JSONResponse({"error": "doc file missing on disk"}, status_code=404)
    try:
        md = fpath.read_text(encoding="utf-8")
    except OSError:
        return JSONResponse({"error": "read error"}, status_code=500)
    # تحويل Markdown مبسَّط جدّاً (بلا تبعيات): ندعم # و## و```code``` و**bold** والروابط.
    body = _md_to_html(md)
    html = f"""<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="utf-8">
<title>{title}</title>
<style>body{{max-width:800px;margin:30px auto;padding:0 20px;font-family:Segoe UI,Tahoma,Arial,sans-serif;line-height:1.7;color:#1f2937;background:#f9fafb}}
h1,h2,h3{{color:#1F4E79}}h1{{border-bottom:2px solid #1F4E79;padding-bottom:8px}}
pre{{background:#111827;color:#f9fafb;padding:14px;border-radius:8px;overflow:auto;direction:ltr;text-align:left;font-size:.88rem}}
code{{background:#e2e8f0;padding:1px 6px;border-radius:4px;font-size:.9em;direction:ltr;display:inline-block}}
a{{color:#1F4E79}}ol,ul{{padding-inline-start:22px}}</style>
</head><body>{body}</body></html>"""
    return HTMLResponse(html)


def _md_to_html(md: str) -> str:
    """محوّل Markdown بسيط بلا تبعيات (يكفي لوثائقنا القصيرة)."""
    import re as _re
    out: list[str] = []
    in_code = False
    code_buf: list[str] = []
    for line in md.splitlines():
        if line.startswith("```"):
            if in_code:
                out.append("<pre><code>" + "\n".join(code_buf) + "</code></pre>")
                code_buf = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_buf.append(_html_escape(line))
            continue
        if line.startswith("### "):
            out.append("<h3>" + _inline_md(line[4:]) + "</h3>")
        elif line.startswith("## "):
            out.append("<h2>" + _inline_md(line[3:]) + "</h2>")
        elif line.startswith("# "):
            out.append("<h1>" + _inline_md(line[2:]) + "</h1>")
        elif _re.match(r"^\s*[-*]\s+", line):
            text = _re.sub(r"^\s*[-*]\s+", "", line)
            if out and out[-1] == "</ul>":
                out.pop()
                out.append("<li>" + _inline_md(text) + "</li></ul>")
            elif out and out[-1].endswith("</li></ul>"):
                out[-1] = out[-1][:-5] + "<li>" + _inline_md(text) + "</li></ul>"
            else:
                out.append("<ul><li>" + _inline_md(text) + "</li></ul>")
        elif _re.match(r"^\s*\d+\.\s+", line):
            text = _re.sub(r"^\s*\d+\.\s+", "", line)
            if out and out[-1].endswith("</li></ol>"):
                out[-1] = out[-1][:-5] + "<li>" + _inline_md(text) + "</li></ol>"
            else:
                out.append("<ol><li>" + _inline_md(text) + "</li></ol>")
        elif line.strip() == "":
            out.append("")
        else:
            out.append("<p>" + _inline_md(line) + "</p>")
    return "\n".join(out)


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _inline_md(s: str) -> str:
    """دعم **bold**، `code`، [text](url)."""
    import re as _re
    s = _html_escape(s)
    s = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = _re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = _re.sub(r"\[(.+?)\]\(([^)]+)\)",
                r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    return s


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


# --- مستكشف النتائج: تصفية/فرز/بحث (الخطة #2) ---
_PAGE_FIELDS = [
    "url", "status_code", "is_indexable", "depth", "content_type", "title",
    "title_length", "meta_description_length", "h1_count", "canonical",
    "word_count", "internal_links_count", "external_links_count",
]


@app.get("/jobs/{job_id}/explore", response_class=HTMLResponse)
async def explore_page(request: Request, job_id: str):
    return templates.TemplateResponse(
        "explore.html", {"request": request, "job_id": job_id}
    )


@app.get("/api/jobs/{job_id}/pages")
async def job_pages(job_id: str):
    """إرجاع صفوف الصفحات (حقول مختارة) للتصفية في المتصفح."""
    import json as _json
    meta = runner.meta(job_id)
    json_path = meta.get("result", {}).get("json")
    if not json_path or not Path(json_path).exists():
        return JSONResponse({"pages": [], "error": "no audit json"}, status_code=404)
    size_mb = Path(json_path).stat().st_size / (1024 * 1024)
    if size_mb > MAX_AUDIT_JSON_MB:
        return JSONResponse({
            "pages": [],
            "error": f"audit JSON too large ({size_mb:.0f} MB) to load in the explorer; "
                     f"open output/csv/pages.csv instead",
        }, status_code=413)
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            audit = _json.load(f)
    except (OSError, ValueError):
        return JSONResponse({"pages": [], "error": "read error"}, status_code=500)
    rows = []
    for p in audit.get("pages", []):
        rows.append({k: p.get(k) for k in _PAGE_FIELDS})
    return JSONResponse({"pages": rows, "count": len(rows)})


@app.get("/jobs/{job_id}/board", response_class=HTMLResponse)
async def board_page(request: Request, job_id: str):
    """لوحة العمل التفاعلية (Action Board) — تعرض أولويات الإصلاح مجمّعةً وقابلةً للتصفية."""
    return templates.TemplateResponse(
        "board.html", {"request": request, "job_id": job_id}
    )


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    """صفحة تحليل ملفات سجلّ الخادم (Apache/Nginx) لاستخراج زحف Googlebot."""
    return templates.TemplateResponse("logs.html", {"request": request})


# سقف رفع ملف اللوغ (يُقرأ كاملاً للذاكرة بعد الـupload — الـstreaming بداخل التحليل)
_MAX_LOG_UPLOAD_MB = 500


@app.post("/api/logs/analyze")
async def logs_analyze(file: UploadFile = File(...), bot_only: int = 1):
    """يستقبل ملف log (CLF/Combined) ويُرجع ملخّص زحف البوتات + قائمة per-URL."""
    # نقرأ كاملاً (FastAPI/Starlette لا يدعم streaming قراءة سهلاً من UploadFile)؛
    # نطبّق سقف الحجم حتى لا تستنزف الذاكرة على ملفات هائلة.
    raw = await file.read()
    if len(raw) > _MAX_LOG_UPLOAD_MB * 1024 * 1024:
        return JSONResponse(
            {"error": f"الملف أكبر من الحدّ ({_MAX_LOG_UPLOAD_MB}MB) — قسّمه أو رفع الحدّ."},
            status_code=413,
        )
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "تعذّر فكّ ترميز الملف"}, status_code=400)
    try:
        from analyzers.log_analyzer import analyze_log
        res = analyze_log(text.splitlines(), bot_only=bool(bot_only))
        return JSONResponse(res)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)[:300]}, status_code=500)


@app.post("/api/jobs/{job_id}/log-board")
async def jobs_log_board(job_id: str, file: UploadFile = File(...), bot_only: int = 1):
    """v1.04: يستقبل ملفّ سجلّ خادم ويضمّه مع نتائج الزحف الحاليّة لإظهار:
    - ميزانية Google المهدورة (404/5xx يزحفها كثيراً)
    - صفحات عالية القيمة بمشاكل (Google يهتمّ بها + لها أخطاء)
    - صفحات يتيمة يكتشفها Google ولم يكتشفها زاحفنا
    - أولويّات معاد ترجيحها بتكرار Google
    """
    import json as _json
    meta = runner.meta(job_id)
    json_path = (meta.get("result") or {}).get("json")
    if not json_path or not Path(json_path).exists():
        return JSONResponse({"error": "no audit json for this job"}, status_code=404)

    # v1.09-B4: حماية ذاكرة — قبل قراءة audit JSON نتحقّق من الحجم. كان مفقوداً
    # في هذا الـendpoint فقط (الباقي يفحص). 1.7GB JSON يُسقط الخادم بـOOM.
    size_mb = Path(json_path).stat().st_size / (1024 * 1024)
    if size_mb > MAX_AUDIT_JSON_MB:
        return JSONResponse({
            "error": f"audit JSON too large ({size_mb:.0f} MB) — re-run the crawl "
                     f"with output.json_full=false to keep it light",
        }, status_code=413)

    raw = await file.read()
    if len(raw) > _MAX_LOG_UPLOAD_MB * 1024 * 1024:
        return JSONResponse(
            {"error": f"الملف أكبر من الحدّ ({_MAX_LOG_UPLOAD_MB}MB)"},
            status_code=413,
        )
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "تعذّر فكّ الترميز"}, status_code=400)

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            audit = _json.load(f)
    except (OSError, ValueError):
        return JSONResponse({"error": "audit JSON unreadable"}, status_code=500)

    try:
        from analyzers.log_analyzer import analyze_log, join_log_with_audit
        log_res = analyze_log(text.splitlines(), bot_only=bool(bot_only))
        joined = join_log_with_audit(log_res.get("per_url", []), audit)
        # نُمرّر ملخّص اللوغ نفسه (لعرضه في البطاقات العلويّة)
        joined["log_summary"] = log_res.get("summary", {})
        return JSONResponse(joined)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)[:300]}, status_code=500)


@app.get("/api/jobs/list")
async def jobs_list_with_audit():
    """قائمة المهام السابقة التي لديها audit JSON — لاختيار «المقارنة مع»."""
    out = []
    for m in runner.list_jobs() or []:
        if not isinstance(m, dict):
            continue
        jid = m.get("job_id") or ""
        json_path = ((m.get("result") or {}) or {}).get("json") or ""
        if not jid or not json_path or not Path(json_path).exists():
            continue
        out.append({
            "job_id": jid,
            "url": m.get("url", ""),
            "mode": m.get("mode", ""),
            "started_at": m.get("started_at", ""),
            "status": m.get("status", ""),
        })
    return JSONResponse({"jobs": out, "count": len(out)})


@app.get("/jobs/{job_id}/compare", response_class=HTMLResponse)
async def compare_page(request: Request, job_id: str):
    """صفحة مقارنة زمنية: تختار مهمّة أخرى وتعرض المُصلَح/الجديد/الباقي."""
    return templates.TemplateResponse(
        "compare.html", {"request": request, "job_id": job_id}
    )


@app.get("/api/jobs/{job_id}/compare")
async def jobs_compare(
    job_id: str,
    with_: str = Query("", alias="with"),
):
    """مقارنة زمنية بين زحفتين لنفس الموقع (compare_crawls)."""
    other = (with_ or "").strip()
    if not other:
        return JSONResponse({"error": "missing 'with' job id"}, status_code=400)
    meta_a = runner.meta(job_id)
    meta_b = runner.meta(other)
    if not meta_a or not meta_b:
        return JSONResponse({"error": "job not found"}, status_code=404)
    path_a = (meta_a.get("result") or {}).get("json")
    path_b = (meta_b.get("result") or {}).get("json")
    if not path_a or not Path(path_a).exists() or not path_b or not Path(path_b).exists():
        return JSONResponse({"error": "audit json missing for one of the jobs"},
                            status_code=404)
    # حارس الحجم: لا نحمّل ملفات ضخمة
    for p in (path_a, path_b):
        size_mb = Path(p).stat().st_size / (1024 * 1024)
        if size_mb > MAX_AUDIT_JSON_MB:
            return JSONResponse({
                "error": f"audit JSON too large ({size_mb:.0f} MB) — set "
                         f"output.json_full=false to keep it light",
            }, status_code=413)
    try:
        from analyzers.crawl_compare import compare_audit_files
        res = compare_audit_files(path_a, path_b)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)[:300]}, status_code=500)
    res["old"] = {"job_id": job_id, "url": meta_a.get("url", "")}
    res["new"] = {"job_id": other, "url": meta_b.get("url", "")}
    return JSONResponse(res)


@app.get("/api/jobs/{job_id}/url-detail")
async def job_url_detail(job_id: str, url: str = ""):
    """تفاصيل شاملة لرابط واحد (الزحف + GSC + GA4 + PageSpeed + الأولوية + الوصولية)."""
    import json as _json
    if not url.strip():
        return JSONResponse({"error": "missing url"}, status_code=400)
    meta = runner.meta(job_id)
    json_path = meta.get("result", {}).get("json")
    if not json_path or not Path(json_path).exists():
        return JSONResponse({"error": "no audit json"}, status_code=404)
    size_mb = Path(json_path).stat().st_size / (1024 * 1024)
    if size_mb > MAX_AUDIT_JSON_MB:
        return JSONResponse({
            "error": f"audit JSON too large ({size_mb:.0f} MB); open output/csv/pages.csv instead",
        }, status_code=413)
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            audit = _json.load(f)
    except (OSError, ValueError):
        return JSONResponse({"error": "read error"}, status_code=500)
    from reporting.url_detail import build_url_detail
    return JSONResponse(build_url_detail(audit, url.strip()))


@app.get("/jobs/{job_id}/graph", response_class=HTMLResponse)
async def graph_page(request: Request, job_id: str):
    """v1.04: صفحة تصوير الزحف — شجرة URL + توزيع العمق/الحالة + رسم بياني للروابط
    على المواقع الصغيرة (<500 صفحة)."""
    return templates.TemplateResponse(
        "graph.html", {"request": request, "job_id": job_id}
    )


@app.get("/api/jobs/{job_id}/graph")
async def jobs_graph(job_id: str):
    """يبني تمثيل شجريّ + توزيعات + قائمة جوار للروابط الداخلية من audit JSON."""
    import json as _json
    meta = runner.meta(job_id)
    json_path = (meta.get("result") or {}).get("json")
    if not json_path or not Path(json_path).exists():
        return JSONResponse({"error": "no audit json"}, status_code=404)
    size_mb = Path(json_path).stat().st_size / (1024 * 1024)
    if size_mb > MAX_AUDIT_JSON_MB:
        return JSONResponse({
            "error": f"audit JSON too large ({size_mb:.0f} MB); use pages.csv instead",
        }, status_code=413)
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            audit = _json.load(f)
    except (OSError, ValueError):
        return JSONResponse({"error": "read error"}, status_code=500)
    return JSONResponse(_build_graph_payload(audit))


def _build_graph_payload(audit: dict[str, Any]) -> dict[str, Any]:
    """v1.04: يحوّل audit JSON إلى:
    - tree: شجرة URL هرميّة من مسارات pages (الأنفع للمستخدم العام)
    - by_depth / by_status: توزيع للرسم البياني
    - graph: nodes+edges للروابط الداخلية (يُحدّ على 500 عقدة للحفاظ على أداء المتصفّح)
    """
    from urllib.parse import urlparse
    pages = audit.get("pages") or []
    links = audit.get("links") or []
    site_url = (audit.get("site_config") or {}).get("start_url", "")
    domain = urlparse(site_url).netloc or ""

    # --- توزيعات depth + status ---
    from collections import Counter
    by_depth = Counter()
    by_status = Counter()
    for p in pages:
        d = p.get("depth") if isinstance(p, dict) else getattr(p, "depth", None)
        s = p.get("status_code") if isinstance(p, dict) else getattr(p, "status_code", None)
        if d is not None:
            by_depth[int(d)] += 1
        if s is not None:
            by_status[str(s)] += 1

    # --- شجرة URL هرميّة (path segments) ---
    # كلّ عقدة: {"name": segment, "count": pages_under, "status": worst_status, "children": {...}}
    root: dict[str, Any] = {"name": "/", "count": 0, "status": None, "children": {}}
    for p in pages:
        url = p.get("url") if isinstance(p, dict) else getattr(p, "url", "")
        status = p.get("status_code") if isinstance(p, dict) else getattr(p, "status_code", None)
        parsed = urlparse(url)
        segments = [s for s in parsed.path.split("/") if s]
        cur = root
        cur["count"] += 1
        for seg in segments:
            children = cur["children"]
            if seg not in children:
                children[seg] = {"name": seg, "count": 0, "status": None, "children": {}}
            cur = children[seg]
            cur["count"] += 1
            # نُسجّل الحالة الأسوأ في الفرع (404 يُحجب الفرع كأحمر)
            if status:
                cur_st = cur["status"]
                if not cur_st or (isinstance(status, int) and status >= 400 and
                                  (not isinstance(cur_st, int) or status > cur_st)):
                    cur["status"] = status
        # ورقة: نضع الـURL الكامل عند نهاية المسار
        cur["url"] = url
        cur["status"] = status

    def _to_array(node):
        children = node.pop("children", {}) or {}
        node["children"] = sorted(
            (_to_array(c) for c in children.values()),
            key=lambda x: (-x["count"], x["name"]),
        )
        return node
    tree = _to_array(root)

    # --- قائمة جوار للروابط الداخلية (محدودة للحفاظ على أداء المتصفّح) ---
    MAX_GRAPH_NODES = 500
    nodes_idx: dict[str, int] = {}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, int]] = []
    truncated = False

    def _ensure_node(url: str, status=None, depth=None) -> int:
        if url in nodes_idx:
            return nodes_idx[url]
        if len(nodes) >= MAX_GRAPH_NODES:
            return -1
        nodes_idx[url] = len(nodes)
        nodes.append({
            "id": len(nodes),
            "url": url,
            "label": (urlparse(url).path or "/")[:40],
            "status": status,
            "depth": depth,
        })
        return nodes_idx[url]

    # نُضيف صفحات الزحف أوّلاً (الأولوية للأكثر إنلِنكاً)
    for p in pages[:MAX_GRAPH_NODES]:
        url = p.get("url") if isinstance(p, dict) else getattr(p, "url", "")
        if url:
            _ensure_node(
                url,
                p.get("status_code") if isinstance(p, dict) else getattr(p, "status_code", None),
                p.get("depth") if isinstance(p, dict) else getattr(p, "depth", None),
            )
    if len(pages) > MAX_GRAPH_NODES:
        truncated = True

    for link in (links or [])[:5000]:
        if not isinstance(link, dict):
            continue
        if link.get("is_internal") in (False, "False", "false", 0, "0"):
            continue
        src = link.get("from_url") or link.get("source_url")
        dst = link.get("to_url") or link.get("target_url")
        if not src or not dst:
            continue
        si = nodes_idx.get(src)
        di = nodes_idx.get(dst)
        if si is None or di is None:
            continue
        edges.append({"s": si, "t": di})

    return {
        "domain": domain,
        "total_pages": len(pages),
        "by_depth": dict(sorted(by_depth.items())),
        "by_status": dict(sorted(by_status.items())),
        "tree": tree,
        "graph": {
            "nodes": nodes,
            "edges": edges,
            "truncated": truncated,
            "max_nodes": MAX_GRAPH_NODES,
        },
    }


@app.get("/api/jobs/{job_id}/priority")
async def job_priority(job_id: str):
    """إرجاع بيانات محرّك الأولويات (الصفحات + ملخّص لوحة العمل) للعرض في المتصفح."""
    import json as _json
    meta = runner.meta(job_id)
    json_path = meta.get("result", {}).get("json")
    if not json_path or not Path(json_path).exists():
        return JSONResponse({"pages": [], "error": "no audit json"}, status_code=404)
    size_mb = Path(json_path).stat().st_size / (1024 * 1024)
    if size_mb > MAX_AUDIT_JSON_MB:
        return JSONResponse({
            "pages": [],
            "error": f"audit JSON too large ({size_mb:.0f} MB); "
                     f"open output/csv/page_priority.csv instead",
        }, status_code=413)
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            audit = _json.load(f)
    except (OSError, ValueError):
        return JSONResponse({"pages": [], "error": "read error"}, status_code=500)
    prio = audit.get("priority", {}) or {}
    pages = prio.get("pages", []) or []
    return JSONResponse({
        "pages": pages,
        "summary": prio.get("summary", {}) or {},
        "count": len(pages),
    })
