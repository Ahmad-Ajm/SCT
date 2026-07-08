"""
exporters/report_builder.py
============================
يبني تقرير HTML (واختيارياً PDF) من بيانات التدقيق.

يُستخدم من الـ CLI ومن الواجهة المرئية على حد سواء.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from exporters.html_exporter import HTMLReportExporter
from exporters.pdf_exporter import PDFReportExporter
from utils.logger import get_logger

log = get_logger(__name__)


def _default_stem() -> str:
    # v1.13.26 (L7-BUG-2): نضيف لاحقة uuid قصيرة لجذر الاسم كي لا تتصادم
    # عمليّتا بناء تقرير متزامنتان تقعان في نفس الثانية (الطابع الزمني بدقّة
    # الثانية وحده غير كافٍ فيدهس أحدهما ملفّات الآخر). نُبقي بادئة "report_"
    # كي تبقى أنماط الـglob (report_*) لدى المستدعي قادرة على إيجاد الملفّ.
    from datetime import datetime
    from uuid import uuid4
    return "report_" + datetime.now().strftime("%Y-%m-%d_%H%M%S") + "_" + uuid4().hex[:8]


def build_report(
    audit: dict[str, Any],
    out_dir: str,
    options: dict[str, Any] | None = None,
    make_pdf: bool = True,
    name_stem: str | None = None,
    progress_callback: Callable[..., None] | None = None,
) -> dict[str, str]:
    """بناء تقرير HTML (+PDF) من قاموس التدقيق.

    Args:
        name_stem: جذر اسم الملف (بدون امتداد). إن لم يُمرَّر يُولَّد بطابع زمني.

    Returns:
        dict: {"html": path, "pdf": path|""}
    """
    options = options or {}
    # حماية SSRF: شعار التقرير يُحمَّل داخل متصفح headless عند توليد PDF،
    # فنرفض أي logo_url غير http(s) عام (مثل file:// أو عناوين داخلية/ميتاداتا).
    logo = str(options.get("logo_url", "") or "").strip()
    if logo:
        from utils.helpers import is_safe_remote_url
        safe, reason = is_safe_remote_url(logo)
        if not safe:
            log.warning(f"تجاهل logo_url غير الآمن ({reason}): {logo}")
            options = {**options, "logo_url": ""}
    stem = name_stem or _default_stem()

    audience = str(options.get("audience", "expert") or "expert").lower()

    # «both» يُنتج تقريرين منفصلين: مختصر للعميل وتفصيلي للخبير.
    if audience == "both":
        result: dict[str, str] = {}
        for aud in ("client", "expert"):
            sub = build_report(
                audit, out_dir, {**options, "audience": aud},
                make_pdf, f"{stem}_{aud}", progress_callback,
            )
            result[f"html_{aud}"] = sub.get("html", "")
            result[f"pdf_{aud}"] = sub.get("pdf", "")
        # نُبقي مفاتيح html/pdf الأساسية (الخبير) للتوافق مع المستدعين القدامى
        result["html"] = result.get("html_expert", "")
        result["pdf"] = result.get("pdf_expert", "")
        return result

    result = {}
    if progress_callback:
        progress_callback("building_html", report_stage="html", report_percent=35)
    html_path = HTMLReportExporter(out_dir, f"{stem}.html").export(audit, options)
    result["html"] = html_path or ""

    if make_pdf and html_path:
        if progress_callback:
            progress_callback("building_pdf", report_stage="pdf", report_percent=70)
        pdf_path = PDFReportExporter(out_dir, f"{stem}.pdf").export_from_html_file(html_path)
        result["pdf"] = pdf_path or ""
    else:
        result["pdf"] = ""

    if progress_callback:
        progress_callback("report_ready", report_stage="done", report_percent=100)

    return result


def build_report_from_json(
    json_path: str,
    out_dir: str,
    options: dict[str, Any] | None = None,
    make_pdf: bool = True,
    name_stem: str | None = None,
    progress_callback: Callable[..., None] | None = None,
    max_mb: int = 500,
) -> dict[str, str]:
    """تحميل ملف التدقيق JSON وبناء التقرير منه."""
    path = Path(json_path)
    if not path.exists():
        log.error(f"ملف التدقيق غير موجود: {json_path}")
        return {"html": "", "pdf": ""}
    # حارس حجم: ملف JSON ضخم (غيغابايت) قد يستنزف الذاكرة عند json.load.
    try:
        size_mb = path.stat().st_size / (1024 * 1024)
        if max_mb and size_mb > max_mb:
            log.error(
                f"ملف التدقيق {size_mb:.0f}MB يتجاوز الحدّ {max_mb}MB — تخطّي بناء التقرير. "
                f"فعّل output.json_full=false لتصغير المخرجات."
            )
            return {"html": "", "pdf": ""}
    except OSError:
        pass
    if progress_callback:
        progress_callback("building_report_data", report_stage="loading_json", report_percent=10)
    with open(path, "r", encoding="utf-8") as f:
        audit = json.load(f)
    return build_report(audit, out_dir, options, make_pdf, name_stem, progress_callback)
