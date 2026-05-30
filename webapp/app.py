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

from fastapi import FastAPI, File, Form, Request, UploadFile
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


@app.post("/api/jobs/{job_id}/stop")
async def job_stop(job_id: str):
    ok = runner.stop(job_id)
    return JSONResponse({"stopped": ok})


@app.post("/api/jobs/{job_id}/kill")
async def job_kill(job_id: str):
    """قتل فوري بلا مهلة — لحالات العلوق في تكامل خارجي طويل (مثل PageSpeed)."""
    ok = runner.force_kill(job_id)
    return JSONResponse({"killed": ok})


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


@app.get("/api/google/status")
async def google_status():
    """حالة الاتصال: هل لدينا client_secret + tokens؟"""
    gd = _google_dir()
    cs = gd / "client_secret.json"
    gsc = gd / "gsc_token.json"
    ga4 = gd / "ga4_token.json"
    return JSONResponse({
        "client_secret": str(cs) if cs.exists() else None,
        "gsc_token": str(gsc) if gsc.exists() else None,
        "ga4_token": str(ga4) if ga4.exists() else None,
        "connected": gsc.exists() and ga4.exists(),
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
        for name in ("gsc_token.json", "ga4_token.json"):
            out = gd / name
            out.write_text(creds.to_json(), encoding="utf-8")
            try:
                os.chmod(out, 0o600)
            except (OSError, NotImplementedError):
                pass
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
    """يحفظ token موحّداً يغطّي GSC + GA4 (نفس موافقة /authorize)."""
    for name in ("gsc_token.json", "ga4_token.json"):
        out = gd / name
        out.write_text(creds.to_json(), encoding="utf-8")
        try:
            os.chmod(out, 0o600)
        except (OSError, NotImplementedError):
            pass


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
