"""
webapp/routers/downloads.py — report rebuild + file downloads + ZIP packaging.

نُقلت من webapp/app.py في v1.12.5.

Endpoints:
    POST /api/jobs/{job_id}/report          — يعيد بناء HTML/PDF بخيارات مخصّصة
    GET  /api/jobs/{job_id}/download/{kind} — تنزيل ملف رئيسي (json/excel/html/pdf/xml-zip)
    GET  /api/jobs/{job_id}/view            — عرض HTML report inline
    GET  /api/jobs/{job_id}/files           — قائمة كلّ الملفّات الناتجة
    GET  /api/jobs/{job_id}/download-file   — تنزيل ملفّ ناتج محدّد
    GET  /api/jobs/{job_id}/download-all    — تنزيل الكلّ (أو only=...) كـZIP
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Form
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from webapp.constants import MAX_AUDIT_JSON_MB, label_for
from webapp.deps import (
    _job_output_dir,
    _safe_output_file,
    _safe_under_jobs,
    runner,
)

router = APIRouter()


@router.post("/api/jobs/{job_id}/report")
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


@router.get("/api/jobs/{job_id}/download/{kind}")
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


@router.get("/api/jobs/{job_id}/view")
async def view_html(job_id: str):
    meta = runner.meta(job_id)
    path = (meta.get("result", {}) or {}).get("html")
    safe = _safe_under_jobs(path) if path else None
    if not safe:
        return JSONResponse({"error": "no html report"}, status_code=404)
    return FileResponse(str(safe), media_type="text/html")


@router.get("/api/jobs/{job_id}/files")
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
            "label": label_for(rel, lang),
            "size": p.stat().st_size,
            "group": group,
        })
    return JSONResponse({"files": files, "groups": groups})


@router.get("/api/jobs/{job_id}/download-file")
async def download_file(job_id: str, rel: str):
    """تنزيل ملف ناتج محدّد عبر مساره النسبي داخل مجلد المخرجات."""
    safe = _safe_output_file(job_id, rel)
    if not safe:
        return JSONResponse({"error": "file not found"}, status_code=404)
    return FileResponse(str(safe), filename=safe.name)


@router.get("/api/jobs/{job_id}/download-all")
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
