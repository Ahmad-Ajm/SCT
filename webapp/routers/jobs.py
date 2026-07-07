"""
webapp/routers/jobs.py — دورة حياة المهام (start/stop/kill/delete + phase2 + SSE).

نُقل من webapp/app.py في v1.12.6 (آخر router في REFACTOR-app-routers).

Endpoints:
    POST /api/start                          — يبدأ مهمة زحف جديدة
    GET  /api/jobs/{job_id}/progress         — حالة + تقدّم
    GET  /api/jobs/{job_id}/events           — بثّ SSE للتقدّم اللحظي
    POST /api/jobs/{job_id}/phase2           — يبدأ Phase 2 للروابط المؤجَّلة
    GET  /api/jobs/{job_id}/deferred         — ملخّص الروابط المؤجَّلة
    POST /api/jobs/{job_id}/stop             — إيقاف بمهلة
    POST /api/jobs/{job_id}/kill             — قتل فوري
    POST /api/jobs/{job_id}/delete           — حذف من القرص
    POST /api/jobs/delete-all                — حذف الكلّ ما عدا النشط
"""

from __future__ import annotations

import asyncio
import csv as _csv
import json
import json as _json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from webapp.deps import FINISHED_STATUSES, _job_output_dir, runner

router = APIRouter()


@router.post("/api/start")
async def start(request: Request):
    """يبدأ مهمة زحف جديدة. يقرأ الـoverrides من form-data ويُمرّرها إلى JobRunner."""
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

    def _int_or_none(name: str):
        v = (form.get(name) or "").strip()
        try:
            return int(v) if v != "" else None
        except ValueError:
            return None

    # v1.13.15 (A1-1): wrappers آمنة تحمي من ValueError عند إدخال غير رقميّ
    # في الـform — كان السلوك السابق HTTP 500 unhandled exception.
    def _safe_int(name: str, default: int) -> int:
        try:
            raw = form.get(name, "")
            return int(raw) if raw not in (None, "") else default
        except (ValueError, TypeError):
            return default

    def _safe_float(name: str, default: float) -> float:
        try:
            raw = form.get(name, "")
            return float(raw) if raw not in (None, "") else default
        except (ValueError, TypeError):
            return default

    # === صيغ المخرجات المختارة ===
    # v1.04: كلّ التنسيقات الثقيلة (Excel/XML/HTML/PDF) صارت عند الطلب من صفحة المهمّة.
    # الزحف يُنتج CSV+JSON فقط (سريع جدّاً، مساحة قليلة). للحفاظ على التوافق العكسي،
    # نقبل overrides من الـform إن طُلبت صراحةً (مثلاً عبر API خارجي).
    formats = form.getlist("formats") or ["csv", "json"]

    # === ما يُجمَع (extraction) — قائمة المفاتيح المختارة ===
    extraction = form.getlist("extraction")

    # === أقسام تقرير PDF/HTML المختارة ===
    sections = form.getlist("sections") or None
    severity_filter = form.getlist("severity_filter") or None

    overrides = {
        "url": (form.get("url") or "").strip(),
        "mode": form.get("mode", "audit"),
        "max_pages": _safe_int("max_pages", 500),
        "max_depth": _safe_int("max_depth", 10),
        "delay_seconds": _safe_float("delay_seconds", 0.5),
        "concurrent_requests": _safe_int("concurrent_requests", 5),
        "respect_robots": _b("respect_robots", True),
        "seed_strategy": form.get("seed_strategy", "hybrid"),
        "no_resume": _b("no_resume", False),
        "skip_external": _b("skip_external", False),
        "integrations_only": _b("integrations_only", False),
        "ext_sample_per_host": _b("ext_sample_per_host", False),
        "ext_max_urls": _safe_int("ext_max_urls", 0),
        "check_resource_status": _b("check_resource_status", False),
        # خيارات مشحونة حديثاً (تُعرض في الإعدادات المتقدمة)
        "platform_preset": (form.get("platform_preset") or "").strip(),
        "generate_sitemap": _b("generate_sitemap", False),
        "adaptive_throttle": _b("adaptive_throttle", False),
        # v1.13.18: تصيير JS + فحص الوصولية (كانا مخفيّين عن الـUI حتى v1.13.17)
        "js_render": _b("js_render", False),
        "js_max_pages": _safe_int("js_max_pages", 100),
        "accessibility_check": _b("accessibility_check", False),
        "accessibility_max_pages": _safe_int("accessibility_max_pages", 50),
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
        "max_rows": _safe_int("max_rows", 100),
    }

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
            "timeout": _safe_int("backlinks_timeout", 30),
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


@router.get("/api/jobs/{job_id}/progress")
async def job_progress(job_id: str):
    return JSONResponse({"meta": runner.meta(job_id), "progress": runner.progress(job_id)})


@router.get("/api/jobs/{job_id}/events")
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


@router.post("/api/jobs/{job_id}/phase2")
async def job_phase2(job_id: str):
    """v1.08: يبدأ Phase 2 — يفحص الروابط المؤجَّلة (deferred) من Phase 1."""
    return JSONResponse(runner.start_phase2(job_id))


@router.get("/api/jobs/{job_id}/deferred")
async def job_deferred(job_id: str):
    """v1.08: يُرجع ملخّص الروابط المؤجَّلة (counts + samples) للوحة الواجهة.

    البيانات تأتي من audit JSON إن وُجد، وإلّا من output/csv/deferred_urls.csv كاحتياط."""
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


@router.post("/api/jobs/{job_id}/stop")
async def job_stop(job_id: str):
    ok = runner.stop(job_id)
    return JSONResponse({"stopped": ok})


@router.post("/api/jobs/{job_id}/kill")
async def job_kill(job_id: str):
    """قتل فوري بلا مهلة — لحالات العلوق في تكامل خارجي طويل (مثل PageSpeed)."""
    ok = runner.force_kill(job_id)
    return JSONResponse({"killed": ok})


@router.post("/api/jobs/{job_id}/delete")
async def job_delete(job_id: str):
    """يحذف مهمّة من القرص (اللوغ + المخرجات + الحالة). يرفض المهام قيد التشغيل."""
    res = runner.delete_job(job_id)
    status = 200 if res.get("ok") else 400
    return JSONResponse(res, status_code=status)


@router.post("/api/jobs/delete-all")
async def jobs_delete_all():
    """يحذف كل المهام السابقة من القرص باستثناء المهمة النشطة حالياً."""
    return JSONResponse(runner.delete_all_jobs())
