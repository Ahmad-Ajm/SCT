"""
webapp/routers/setup.py — تثبيت متطلّبات اختياريّة + سبر التوفّر + خدمة docs.

نُقلت من webapp/app.py في v1.12.4.

Endpoints:
    POST /api/setup/{tool}        — يبدأ تثبيت أداة اختياريّة في الخلفية
    GET  /api/setup/{tool}/status — حالة التثبيت
    GET  /api/requirements        — سبر توفّر openpyxl/ga4/playwright
    GET  /docs/{name}             — يقدّم وثيقة Markdown كـHTML مبسَّط
"""

from __future__ import annotations

import asyncio
import logging
import re as _re
import sys
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

log = logging.getLogger("sct.webapp")

router = APIRouter()

# الجذر للوصول إلى docs/
ROOT = Path(__file__).resolve().parent.parent.parent

# تثبيت المتطلبات يعمل في الخلفية ثم نستفسر عن الحالة — لأنّ التثبيت قد يستغرق
# دقائق (تنزيل من الإنترنت) فيسقط اتصال fetch المتصفّح («Failed to fetch») إن انتظرناه.
_SETUP_CMDS = {
    "ga4_lib": [sys.executable, "-m", "pip", "install", "google-analytics-data"],
    "playwright": [sys.executable, "-m", "playwright", "install", "chromium"],
}
_setup_state: dict[str, dict[str, Any]] = {}
_setup_lock = threading.Lock()


def _run_setup_bg(tool: str) -> None:
    import subprocess
    cmd = _SETUP_CMDS[tool]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        ok = r.returncode == 0
        msg = (r.stdout if ok else (r.stderr or r.stdout or "")) or ""
    except Exception as e:  # noqa: BLE001
        log.exception("tool setup subprocess failed: %s", tool)
        ok, msg = False, f"{type(e).__name__}: {e}"
    with _setup_lock:
        _setup_state[tool] = {"running": False, "ok": ok, "message": msg[-600:]}


@router.post("/api/setup/{tool}")
async def setup_install(tool: str):
    """يبدأ تثبيت متطلّب في الخلفية ويعود فوراً (راجع الحالة عبر /api/setup/{tool}/status)."""
    if tool not in _SETUP_CMDS:
        return JSONResponse({"error": "أداة غير معروفة"}, status_code=404)
    with _setup_lock:
        cur = _setup_state.get(tool)
        if cur and cur.get("running"):
            return JSONResponse({"started": False, "running": True})
        _setup_state[tool] = {"running": True, "ok": None, "message": ""}
    threading.Thread(target=_run_setup_bg, args=(tool,), daemon=True).start()
    return JSONResponse({"started": True, "running": True})


@router.get("/api/setup/{tool}/status")
async def setup_status(tool: str):
    if tool not in _SETUP_CMDS:
        return JSONResponse({"error": "أداة غير معروفة"}, status_code=404)
    with _setup_lock:
        st = _setup_state.get(tool) or {"running": False, "ok": None, "message": ""}
    return JSONResponse(st)


# === v1.02: شريط جاهزية المتطلبات الاختيارية ===
_REQUIREMENTS_PROBES = {
    "excel": ("openpyxl", None),
    "ga4": ("google.analytics.data_v1beta", None),
    "pdf": ("playwright", "chromium_present"),
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
        if extra_check == "chromium_present":
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    info["present"] = bool(p.chromium.executable_path)
                    if not info["present"]:
                        info["note"] = "playwright OK but chromium not installed"
            except Exception:  # noqa: BLE001
                info["note"] = "chromium check failed"
        out[tool] = info
    return out


@router.get("/api/requirements")
async def get_requirements(refresh: int = 0):
    """v1.02: حالة المتطلبات الاختيارية للواجهة (Excel/GA4/PDF Chromium)."""
    global _requirements_cache
    if _requirements_cache is None or refresh:
        loop = asyncio.get_event_loop()
        _requirements_cache = await loop.run_in_executor(None, _probe_requirements)
    return JSONResponse({"items": _requirements_cache})


# === v1.02: خدمة وثائق المشروع كـMarkdown للواجهة ===
_DOCS_MAP = {
    "oauth_setup": ("OAUTH_SETUP.md", "إعداد OAuth و Google Cloud — SCT"),
    "ga4_property_id": ("GA4_PROPERTY_ID.md", "اكتشاف GA4 property_id — SCT"),
}


@router.get("/docs/{name}")
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
    s = _html_escape(s)
    s = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = _re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = _re.sub(r"\[(.+?)\]\(([^)]+)\)",
                r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    return s
