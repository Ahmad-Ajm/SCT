"""
webapp/routers/connections.py — اختبارات اتّصال للتكاملات (GSC/GA4/PageSpeed).

نُقلت من webapp/app.py في v1.12.4.

Endpoints:
    POST /api/test/gsc       — يصادق ويسرد المواقع التي يملك الحساب صلاحيّتها
    POST /api/test/ga4       — تقرير صغير على property_id
    POST /api/test/pagespeed — يفحص رابطاً معروفاً بمفتاح API
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse

from webapp.deps import _google_dir, _run_conn_test

log = logging.getLogger("sct.webapp")

router = APIRouter()


@router.post("/api/test/gsc")
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
            log.exception("GSC sites().list test failed")
            return {"ok": False, "error": str(e)[:300]}

    res = await _run_conn_test(_run)
    if res.get("ok") and site_url:
        target = site_url.rstrip("/")
        res["site_accessible"] = any(
            (s or "").rstrip("/") == target or target in (s or "")
            for s in res.get("sites", [])
        )
    return JSONResponse(res)


@router.post("/api/test/ga4")
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
            log.exception("GA4 test run failed")
            return {"ok": False, "error": str(e)[:300]}

    return JSONResponse(await _run_conn_test(_run))


@router.post("/api/test/pagespeed")
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
