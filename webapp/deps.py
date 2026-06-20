"""
webapp/deps.py — singletons + path helpers مشتركة بين كلّ routers.

نُقلت من webapp/app.py في v1.12.4 (REFACTOR-app-routers الخطوة الثالثة).

محتوى:
- `runner`           — JobRunner singleton (يُحرَّس بـ_run_lock داخلياً).
- `templates`        — Jinja2Templates singleton.
- `FINISHED_STATUSES`— حالات إغلاق بثّ SSE.
- `_safe_under_jobs` — مسار ضمن JOBS_DIR (defense-in-depth ضدّ path traversal).
- `_job_output_dir`  — output dir لـjob_id بعد فحص صيغة المعرّف.
- `_safe_output_file`— ملف ضمن output/ بعد فحص traversal.

كلّ router يستورد من هنا — يمنع cycle لأنّ deps.py لا يستورد من أيّ router.
deps.py يستورد من webapp.security (لـtpl_ctx + LOCAL_TOKEN) — هذا الاتجاه الوحيد المسموح.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

from fastapi.templating import Jinja2Templates

from webapp.job_runner import JobRunner

# Singletons — يُحمَّلان مرّة واحدة عند استيراد الـmodule.
runner = JobRunner()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# حالات الانتهاء (لإغلاق بثّ SSE)
FINISHED_STATUSES = {"complete", "partial", "partial_max_pages", "done", "failed", "stopped"}


def _safe_under_jobs(path: str) -> Path | None:
    """يتأكّد أن الملف داخل مجلد المهام (دفاع عميق ضد قراءة ملفات عشوائية)."""
    from webapp.job_runner import JOBS_DIR
    try:
        rp = Path(path).resolve()
        rp.relative_to(JOBS_DIR.resolve())
        return rp if rp.exists() else None
    except (ValueError, OSError):
        return None


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


def _google_dir() -> Path:
    """مجلد آمن لحفظ ملف client_secret والـtokens (خارج Git).
    يُستعمل من routers/google_oauth.py و routers/connections.py."""
    from webapp.job_runner import JOBS_DIR
    d = JOBS_DIR / "_google"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _run_conn_test(fn: Callable[[], dict[str, Any]], timeout: float = 45.0) -> dict:
    """يشغّل اختبار اتصال محجوب (شبكة) في خيط مع مهلة قصوى.

    اختبارات الاتصال غير تفاعلية (لا تفتح متصفّح OAuth) ومحدودة بمهلة، كي لا يتعلّق
    الطلب إلى ما لا نهاية (كان اختبار GA4 يفتح تدفّق OAuth ويتعلّق حتى إيقاف الخادم)."""
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(loop.run_in_executor(None, fn), timeout=timeout)
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"انتهت مهلة الاختبار ({int(timeout)}ث) — تحقّق من الشبكة/الصلاحيات."}
