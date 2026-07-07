"""
webapp/routers/pages.py — صفحات HTML (Jinja2 templates).

نُقلت من webapp/app.py في v1.12.4 (REFACTOR-app-routers الخطوة الرابعة).

الـ7 routes هنا:
    GET /
    GET /jobs/{job_id}
    GET /jobs/{job_id}/explore
    GET /jobs/{job_id}/board
    GET /jobs/{job_id}/compare
    GET /jobs/{job_id}/graph
    GET /logs
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from webapp.constants import (
    EXTRACTION_GROUPS,
    OUTPUT_FORMATS,
    SECTIONS,
    SEVERITIES,
)
from webapp.deps import runner, templates
from webapp.job_runner import JOBS_DIR, _valid_job_id
from webapp.security import tpl_ctx

router = APIRouter()


# v1.13.22: كل صفحات /jobs/{job_id}/* تحوّل المعرّفات غير الصالحة إلى redirect
# للصفحة الرئيسيّة بدل عرض صفحة مهمّة فارغة أبديّة (الـUI السابق كان يعرضها
# "يعمل" للأبد لأنّ effectiveStatus fallback = 'running'). لو المستخدم دخل من
# رابط قديم (مثل /jobs/_google) أو bookmark لمهمّة محذوفة، يُعاد فوراً للصفحة
# الرئيسيّة حيث توجد قائمة المهام الفعليّة.
def _validate_or_redirect(job_id: str) -> RedirectResponse | None:
    if not _valid_job_id(job_id):
        return RedirectResponse(url="/", status_code=302)
    if not (JOBS_DIR / job_id).exists():
        return RedirectResponse(url="/", status_code=302)
    return None


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        tpl_ctx({"request": request, "jobs": runner.list_jobs()[:15],
                 "groups": EXTRACTION_GROUPS, "formats": OUTPUT_FORMATS,
                 "sections": SECTIONS, "severities": SEVERITIES,
                 "active_job": runner.active_job()}),
    )


# v1.13.19: /jobs و /jobs/ كانا يُعيدان 404 (لا يوجد route). المستخدم قد يكتب
# الرابط بغير job_id بحثاً عن قائمة، أو يقصّ آخر جزء من URL. نُحوّله للصفحة
# الرئيسيّة التي تحوي "المهام الأخيرة" فعلياً.
@router.get("/jobs", include_in_schema=False)
@router.get("/jobs/", include_in_schema=False)
async def jobs_redirect():
    return RedirectResponse(url="/", status_code=302)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_page(request: Request, job_id: str):
    redirect = _validate_or_redirect(job_id)
    if redirect:
        return redirect
    meta = runner.meta(job_id)
    return templates.TemplateResponse(
        "job.html", tpl_ctx({"request": request, "job_id": job_id, "meta": meta})
    )


@router.get("/jobs/{job_id}/explore", response_class=HTMLResponse)
async def explore_page(request: Request, job_id: str):
    redirect = _validate_or_redirect(job_id)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "explore.html", tpl_ctx({"request": request, "job_id": job_id})
    )


@router.get("/jobs/{job_id}/board", response_class=HTMLResponse)
async def board_page(request: Request, job_id: str):
    """لوحة العمل التفاعلية (Action Board) — تعرض أولويات الإصلاح مجمّعةً وقابلةً للتصفية."""
    redirect = _validate_or_redirect(job_id)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "board.html", tpl_ctx({"request": request, "job_id": job_id})
    )


@router.get("/jobs/{job_id}/compare", response_class=HTMLResponse)
async def compare_page(request: Request, job_id: str):
    """صفحة مقارنة زمنية: تختار مهمّة أخرى وتعرض المُصلَح/الجديد/الباقي."""
    redirect = _validate_or_redirect(job_id)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "compare.html", tpl_ctx({"request": request, "job_id": job_id})
    )


@router.get("/jobs/{job_id}/graph", response_class=HTMLResponse)
async def graph_page(request: Request, job_id: str):
    """v1.04: صفحة تصوير الزحف — شجرة URL + توزيع العمق/الحالة + رسم بياني للروابط
    على المواقع الصغيرة (<500 صفحة)."""
    redirect = _validate_or_redirect(job_id)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "graph.html", tpl_ctx({"request": request, "job_id": job_id})
    )


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    """صفحة تحليل ملفات سجلّ الخادم (Apache/Nginx) لاستخراج زحف Googlebot."""
    return templates.TemplateResponse("logs.html", tpl_ctx({"request": request}))
