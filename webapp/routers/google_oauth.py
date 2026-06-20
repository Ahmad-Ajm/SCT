"""
webapp/routers/google_oauth.py — Google OAuth flow (Search Console + Analytics 4).

نُقل من webapp/app.py في v1.12.6.

Endpoints:
    GET  /api/google/status          — حالة الاتّصال + فحص انتهاء الـtoken
    POST /api/google/upload          — رفع client_secret.json
    POST /api/google/authorize       — موافقة محلّيّة بمتصفّح (run_local_server)
    POST /api/google/disconnect      — حذف الـtokens (مع ?full=1 لحذف client_secret)
    GET  /api/google/gsc-sites       — قائمة مواقع GSC المتاحة
    GET  /api/google/ga4-properties  — قائمة properties GA4 المتاحة
    GET  /api/google/authorize-url   — رابط موافقة لاستعمال paste-code
    POST /api/google/authorize-code  — يستقبل الرمز/رابط callback وينهي التفويض

ملاحظة معماريّة: `_paste_flow` و `_probe_token_expired` يبقيان داخل هذا الـmodule.
state-ful module-level state بحكم تصميم تدفّق paste-code (يحفظ كائن Flow بين
الطلبين). v1.11 RUNBOOK يوثّق هذا السلوك.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from webapp.deps import _google_dir, _run_conn_test
from webapp.security import _atomic_write_text

log = logging.getLogger("sct.webapp")

router = APIRouter()

# نطاقات OAuth (قراءة فقط) لكلتا الخدمتين
_GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",   # Search Console
    "https://www.googleapis.com/auth/analytics.readonly",    # Analytics 4
]

# === مسار «لصق الرمز» — احتياط للأجهزة بلا متصفّح/الخوادم البعيدة ===
# نحتفظ بكائن Flow مؤقتاً بين طلبَي url وcode (SCT محلية لمستخدم واحد).
_paste_flow: dict[str, Any] = {}
_PASTE_REDIRECT = "http://127.0.0.1:1/"  # لا نستمع — المتصفّح يفشل لكن الرمز يظهر في URL


def _probe_token_expired(token_path: Path) -> bool:
    """v1.06: يفحص بسرعة ما إن كان token Google منتهي الصلاحية (يحاول refresh صامتاً).

    Google في وضع «Testing» يُلغي refresh_token كلّ 7 أيام، فيظهر للمستخدم خطأ
    `invalid_grant` فقط حين يبدأ الزحف ويفشل التكامل في منتصفه. هذا الفحص يكتشف
    الحالة مبكّراً ويُمكّن الواجهة من إظهار «التفويض منتهٍ» قبل بدء أيّ مهمّة."""
    if not token_path.exists():
        return False
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        return False
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), _GOOGLE_SCOPES)
    except (OSError, ValueError):
        return True  # ملف تالف ⇒ يُعامَل كمنتهٍ كي يُعيد المستخدم الربط
    if creds.valid:
        return False
    if not creds.expired or not creds.refresh_token:
        return True
    try:
        creds.refresh(Request())
        # v1.09-B6: كتابة atomic — refresh ينتج access_token جديد، ولا نريد
        # crash منتصف الكتابة أن يُتلف الـtoken بأكمله.
        _atomic_write_text(token_path, creds.to_json())
        return False
    except Exception:  # noqa: BLE001
        return True  # refresh فشل (غالباً invalid_grant) ⇒ منتهٍ


def _save_google_tokens(gd: Path, creds: Any) -> None:
    """يحفظ token موحّداً يغطّي GSC + GA4 (نفس موافقة /authorize).
    v1.09-B6: كتابة atomic (temp + os.replace) — crash لا يُتلف الـtoken."""
    for name in ("gsc_token.json", "ga4_token.json"):
        _atomic_write_text(gd / name, creds.to_json())


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


@router.get("/api/google/status")
async def google_status():
    """حالة الاتصال: هل لدينا client_secret + tokens + هل الـtokens صالحة؟

    v1.06: نُضيف فحص نشط (`expired`) لاكتشاف Token الذي ألغته Google (Testing
    mode بعد 7 أيام) قبل بدء أيّ مهمّة، بدل اكتشافه مع أوّل فشل تكامل."""
    gd = _google_dir()
    cs = gd / "client_secret.json"
    gsc = gd / "gsc_token.json"
    ga4 = gd / "ga4_token.json"
    # فحص الانتهاء يستدعي شبكة (refresh) — نُشغّله في executor كي لا يحجب الحلقة
    loop = asyncio.get_event_loop()
    expired = False
    if gsc.exists() or ga4.exists():
        try:
            checks = await asyncio.gather(
                loop.run_in_executor(None, _probe_token_expired, gsc),
                loop.run_in_executor(None, _probe_token_expired, ga4),
            )
            expired = any(checks)
        except Exception:  # noqa: BLE001
            expired = False
    return JSONResponse({
        "client_secret": str(cs) if cs.exists() else None,
        "gsc_token": str(gsc) if gsc.exists() else None,
        "ga4_token": str(ga4) if ga4.exists() else None,
        "connected": gsc.exists() and ga4.exists(),
        "expired": expired,
    })


@router.post("/api/google/upload")
async def google_upload(file: UploadFile = File(...)):
    """رفع ملف OAuth client secret (Desktop) من المتصفّح."""
    # v1.10-C1 (M-3): MIME validation — نقبل application/json و text/* فقط.
    # ملف Google OAuth client_secret دائماً JSON. أيّ شيء آخر مرفوض.
    ctype = (file.content_type or "").lower().split(";")[0].strip()
    if ctype not in ("application/json", "text/plain", "text/json",
                     "application/octet-stream", ""):
        return JSONResponse(
            {"error": f"MIME type غير مقبول: {ctype}. متوقّع application/json."},
            status_code=400,
        )
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


@router.post("/api/google/authorize")
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
        # v1.09-B6: كتابة atomic لكلا الـtokens
        for name in ("gsc_token.json", "ga4_token.json"):
            _atomic_write_text(gd / name, creds.to_json())
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
        log.exception("setup endpoint failed")
        return JSONResponse({"error": str(e)[:300]}, status_code=500)

    return JSONResponse({
        "ok": True,
        "client_secret": str(cs),
        "gsc_token": str(gd / "gsc_token.json"),
        "ga4_token": str(gd / "ga4_token.json"),
    })


@router.post("/api/google/disconnect")
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


@router.get("/api/google/gsc-sites")
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
            log.exception("GSC sites list failed")
            return {"sites": [], "error": str(e)[:300]}

    return JSONResponse(await _run_conn_test(_run))


@router.get("/api/google/ga4-properties")
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


@router.get("/api/google/authorize-url")
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
        log.exception("OAuth flow init failed")
        return JSONResponse({"error": str(e)[:300]}, status_code=500)


@router.post("/api/google/authorize-code")
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
        log.exception("OAuth code exchange failed")
        return JSONResponse({"error": str(e)[:300]}, status_code=500)
