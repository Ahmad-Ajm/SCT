"""
webapp/routers/generate.py — توليد التنسيقات على الطلب (HTML/PDF/Excel/XML).

نُقل من webapp/app.py في v1.12.6.

Endpoints:
    POST /api/jobs/{job_id}/generate              — يبدأ التوليد في الخلفية
    GET  /api/jobs/{job_id}/generate/{fmt}/status — حالة التوليد

ملاحظة معماريّة: _gen_state و _gen_lock state-ful على مستوى الـmodule —
يبقى داخل هذا الـmodule (لا يُمرَّر للـrouter). كل مهمة لها dict منفصل
{fmt: {running, ok, message}} يُحدَّث عبر threading.Lock.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse

from webapp.constants import MAX_AUDIT_JSON_MB
from webapp.deps import runner

log = logging.getLogger("sct.webapp")

router = APIRouter()

# الزحف يُنتج دائماً CSV+JSON (سريعة ورخيصة)؛ HTML/PDF/Excel/XML تُطلَب من زرّ منفصل
# لكلّ تنسيق، مع شريط تقدّم خاص بها. هذا يختصر وقت/مساحة الجوب الرئيسي.
_GEN_VALID_FORMATS = {"html", "pdf", "excel", "xml"}
_gen_state: dict[str, dict[str, dict[str, Any]]] = {}   # {job_id: {fmt: {running, ok, message}}}
_gen_lock = threading.Lock()


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


@router.post("/api/jobs/{job_id}/generate")
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
    threading.Thread(
        target=_run_generate_bg, args=(job_id, fmt, options), daemon=True
    ).start()
    return JSONResponse({"started": True, "format": fmt})


@router.get("/api/jobs/{job_id}/generate/{fmt}/status")
async def jobs_generate_status(job_id: str, fmt: str):
    """يستفسر عن حالة توليد تنسيق واحد لمهمّة."""
    with _gen_lock:
        st = (_gen_state.get(job_id) or {}).get(fmt) or {
            "running": False, "ok": None, "message": "",
        }
    return JSONResponse(st)
