"""
webapp/security.py — auth token + 4 middlewares + 2 exception handlers.

نُقلت من webapp/app.py في v1.12.3 (REFACTOR-app-routers الخطوة الثانية).

ترتيب middlewares في FastAPI: آخر مُسجَّل = أوّل مُنفَّذ. الترتيب الذي يحافظ على
سلوك v1.10:
  1. _local_auth_guard       (سُجّل أوّلاً → ينفّذ أخيراً)
  2. _correlation_id_middleware
  3. _rate_limit_middleware
  4. _csrf_origin_guard      (سُجّل أخيراً → ينفّذ أوّلاً)

أي طلب: CSRF → Rate Limit → Correlation ID → Auth → handler.

نستعمل دالّة register_middlewares(app) لتُحافظ على هذا الترتيب صراحةً عند الـsplit.
"""

from __future__ import annotations

import logging
import os
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("sct.webapp")


# ============================================================
# v1.10-A1: auth token محلّي على كلّ /api/* + كلّ POST/PUT/DELETE.
# يُولَّد عند أوّل startup ويُحفَظ في ~/.sct/local_token بصلاحيّات 0600.
# ============================================================
def _load_or_create_token() -> str:
    """ينشئ token محلّياً إن لم يوجد. يُخزَّن بـ0600. مَن يمسك الـtoken يدير الأداة."""
    from secrets import token_urlsafe
    home = Path.home() / ".sct"
    home.mkdir(mode=0o700, exist_ok=True)
    tp = home / "local_token"
    if tp.exists():
        try:
            existing = tp.read_text(encoding="utf-8").strip()
            if existing and len(existing) >= 32:
                return existing
        except OSError:
            pass
    new = token_urlsafe(32)
    try:
        tp.write_text(new, encoding="utf-8")
        try:
            os.chmod(tp, 0o600)
        except (OSError, NotImplementedError):
            pass
    except OSError:
        # إن تعذّر الحفظ (rare)، نستعمل token جلسة فقط — يفقد عند إعادة التشغيل
        pass
    return new


# الـtoken يُحمَّل مرّة واحدة عند استيراد الـmodule.
LOCAL_TOKEN = _load_or_create_token()

# مسارات معفاة (يمكن GET-ها بلا auth: صفحات HTML + static + health/readyz)
AUTH_EXEMPT_PREFIXES = ("/static/", "/health", "/readyz")
AUTH_EXEMPT_EXACT = {"/favicon.ico"}


def _extract_token(request) -> str:
    """يقرأ token من Bearer header أو query param."""
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.query_params.get("token") or "").strip()


def _constant_time_eq(a: str, b: str) -> bool:
    """v1.10-A1: مقارنة ثابتة الزمن — يمنع timing attacks."""
    import hmac
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _atomic_write_text(target: Path, text: str, *, mode: int = 0o600) -> None:
    """v1.09-B6: كتابة atomic مع صلاحيّات محدّدة — temp + os.replace.
    يضمن إمّا الملف القديم سليم أو الجديد سليم؛ لا يُترك أبداً نصف ملف."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        os.chmod(tmp, mode)
    except (OSError, NotImplementedError):
        pass
    os.replace(tmp, target)


async def local_auth_guard(request, call_next):
    """v1.10-A1: يفرض token على كلّ POST/PUT/DELETE + كلّ /api/*."""
    path = request.url.path or "/"
    if path in AUTH_EXEMPT_EXACT or any(path.startswith(p) for p in AUTH_EXEMPT_PREFIXES):
        return await call_next(request)
    # GET على HTML pages (الجذر + /jobs/*): يمر بدون auth — الـtoken يُحقَن في الـsession.
    if request.method == "GET" and not path.startswith("/api"):
        return await call_next(request)
    provided = _extract_token(request)
    if not provided or not _constant_time_eq(provided, LOCAL_TOKEN):
        return JSONResponse(
            {"error": "unauthorized",
             "hint": "Provide your SCT local token via Authorization: Bearer <token> "
                     f"or ?token=<token>. Token file: ~/.sct/local_token"},
            status_code=401,
        )
    return await call_next(request)


async def correlation_id_middleware(request, call_next):
    """v1.10-B1: كلّ طلب يحصل على UUIDv4 يظهر في كلّ log line يخصّ هذا الطلب."""
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    request.state.request_id = rid
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


# v1.10-B1: rate limiting خفيف — token-bucket مبسَّط، in-memory.
_RATE_BUCKETS: dict[str, tuple[float, int]] = {}
_RATE_LOCK = __import__("threading").Lock()


def _check_rate(ip: str, key: str, max_per_minute: int) -> bool:
    """يُرجع True إن سُمح، False إن تُجاوز."""
    now = time.time()
    bk = f"{ip}|{key}"
    with _RATE_LOCK:
        last, count = _RATE_BUCKETS.get(bk, (now, 0))
        if now - last < 60.0:
            count += 1
            _RATE_BUCKETS[bk] = (last, count)
            return count <= max_per_minute
        _RATE_BUCKETS[bk] = (now, 1)
        return True


async def rate_limit_middleware(request, call_next):
    """v1.10-B1: 120/دقيقة عام لـ/api/*، 10/ساعة على /api/start."""
    path = request.url.path or "/"
    if path.startswith("/static/") or path in ("/health", "/readyz"):
        return await call_next(request)
    ip = (request.client.host if request.client else "?")
    if path == "/api/start" and request.method == "POST":
        if not _check_rate(ip, "start", max_per_minute=10):
            return JSONResponse({"error": "rate_limited", "scope": "start"},
                                status_code=429)
    elif path.startswith("/api/"):
        if not _check_rate(ip, "api", max_per_minute=120):
            return JSONResponse({"error": "rate_limited", "scope": "api"},
                                status_code=429)
    return await call_next(request)


async def csrf_origin_guard(request, call_next):
    """v1.09-B3: على أيّ POST/PUT/DELETE/PATCH، إن وُجد Origin ولم يكن localhost — رفض."""
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return await call_next(request)
    origin = request.headers.get("origin") or ""
    if not origin:
        return await call_next(request)
    try:
        from urllib.parse import urlparse
        host = (urlparse(origin).hostname or "").lower()
    except Exception:  # noqa: BLE001
        host = ""
    if host in ("127.0.0.1", "localhost", "::1"):
        return await call_next(request)
    return JSONResponse(
        {"error": "Cross-origin POST blocked (CSRF protection). "
                  "Open SCT via http://127.0.0.1:8000 in the same tab."},
        status_code=403,
    )


# ============================================================
# v1.10-A3: Global exception handlers.
# ============================================================
async def unhandled_exception_handler(request, exc):
    """يمسك أيّ استثناء غير معالَج ⇒ يسجّل + يردّ generic 500."""
    rid = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:12]
    log.error(
        f"[req={rid}] unhandled {type(exc).__name__} on {request.method} "
        f"{request.url.path}\n{traceback.format_exc()}"
    )
    return JSONResponse(
        {"error": "internal_error", "request_id": rid,
         "hint": "Server log holds the traceback. Search by request_id."},
        status_code=500,
    )


async def http_exception_handler(request, exc):
    """HTTPException-derived: نُبقي status_code الأصلي + رسالة قصيرة آمنة."""
    rid = getattr(request.state, "request_id", None) or ""
    payload = {"error": exc.detail if isinstance(exc.detail, str) else "http_error"}
    if rid:
        payload["request_id"] = rid
    return JSONResponse(payload, status_code=exc.status_code)


# ============================================================
# Registration entry points (يستدعيها app.py عند startup).
# ============================================================
def register_middlewares(app) -> None:
    """يُسجّل الـmiddlewares بالترتيب الصحيح.
    آخر مُسجَّل = أوّل مُنفَّذ. الترتيب المطلوب للسلوك (CSRF → Rate Limit →
    Correlation ID → Auth → handler):
      1. local_auth_guard       (يُسجَّل أوّلاً → ينفّذ أخيراً)
      2. correlation_id_middleware
      3. rate_limit_middleware
      4. csrf_origin_guard      (يُسجَّل أخيراً → ينفّذ أوّلاً)
    """
    app.middleware("http")(local_auth_guard)
    app.middleware("http")(correlation_id_middleware)
    app.middleware("http")(rate_limit_middleware)
    app.middleware("http")(csrf_origin_guard)


def register_exception_handlers(app) -> None:
    """يُسجّل exception handlers بعد إنشاء الـapp."""
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)


def tpl_ctx(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """السياق المُشترَك لكلّ TemplateResponse — يحقن sct_token تلقائياً."""
    ctx = {"sct_token": LOCAL_TOKEN}
    if extra:
        ctx.update(extra)
    return ctx
