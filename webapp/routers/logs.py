"""
webapp/routers/logs.py — تحليل ملفّات سجلّ الخادم (Apache/Nginx).

نُقلت من webapp/app.py في v1.12.4.

Endpoints:
    POST /api/logs/analyze         — تحليل log مستقلّ (CLF/Combined)
    POST /api/jobs/{job_id}/log-board — ضمّ log مع audit JSON لتصنيف Googlebot crawl
"""

from __future__ import annotations

import json as _json
import logging
from pathlib import Path

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse

from webapp.constants import MAX_AUDIT_JSON_MB
from webapp.deps import runner

log = logging.getLogger("sct.webapp")

router = APIRouter()

# سقف رفع ملف اللوغ (يُقرأ كاملاً للذاكرة بعد الـupload — الـstreaming بداخل التحليل)
_MAX_LOG_UPLOAD_MB = 500

# v1.13.26 (L7-BUG-1): حجم الدفعة لقراءة الرفع على أجزاء محدودة.
_LOG_READ_CHUNK = 8 * 1024 * 1024  # 8MB


async def _read_capped(file: UploadFile, cap_bytes: int) -> bytes | None:
    """v1.13.26 (L7-BUG-1): يقرأ الملف المرفوع على دفعات ويُجهض فور تجاوز السقف.

    سابقاً كان الكود يفعل `raw = await file.read()` (يبتلع الجسم كاملاً للذاكرة)
    ثم `.decode()` (~2x) و`.splitlines()` (~3x) قبل فحص len(raw)>الحدّ — فرفع 2GB
    يُسقط الخادم بـOOM قبل أن يعمل السقف. الآن نراكم حتى الحدّ فقط ونُجهض بلا فكّ
    ترميز. يُرجع None إذا تجاوز الحجم الحدّ (يُترجَم لـ413 عند المتّصل)."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_LOG_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > cap_bytes:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/api/logs/analyze")
async def logs_analyze(file: UploadFile = File(...), bot_only: int = 1):
    """يستقبل ملف log (CLF/Combined) ويُرجع ملخّص زحف البوتات + قائمة per-URL."""
    # v1.13.26 (L7-BUG-1): قراءة على دفعات محدودة مع إجهاض مبكّر — نطبّق سقف الحجم
    # قبل أن يبتلع الجسم كاملاً الذاكرة (كان raw=await file.read() ثم decode/splitlines
    # قبل الفحص يُسقط الخادم بـOOM على ملف 2GB).
    raw = await _read_capped(file, _MAX_LOG_UPLOAD_MB * 1024 * 1024)
    if raw is None:
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
        log.exception("log analyzer failed")
        return JSONResponse({"error": str(e)[:300]}, status_code=500)


@router.post("/api/jobs/{job_id}/log-board")
async def jobs_log_board(job_id: str, file: UploadFile = File(...), bot_only: int = 1):
    """v1.04: يستقبل ملفّ سجلّ خادم ويضمّه مع نتائج الزحف الحاليّة لإظهار:
    - ميزانية Google المهدورة (404/5xx يزحفها كثيراً)
    - صفحات عالية القيمة بمشاكل (Google يهتمّ بها + لها أخطاء)
    - صفحات يتيمة يكتشفها Google ولم يكتشفها زاحفنا
    - أولويّات معاد ترجيحها بتكرار Google
    """
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

    # v1.13.26 (L7-BUG-1): قراءة على دفعات محدودة مع إجهاض مبكّر (كما /logs/analyze).
    raw = await _read_capped(file, _MAX_LOG_UPLOAD_MB * 1024 * 1024)
    if raw is None:
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
        log.exception("log+audit join failed")
        return JSONResponse({"error": str(e)[:300]}, status_code=500)
