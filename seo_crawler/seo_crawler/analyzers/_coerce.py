"""
analyzers/_coerce.py
====================
v1.09-B2: مساعدات تحويل آمن للأنواع.

السبب التاريخي: DB rows + JSON imports يخزّنون `status_code` أحياناً كـstr
وأحياناً int وأحياناً None. كثير من analyzers يكتب `400 <= status < 500`
أو `int(row["status_code"])` بدون حماية، فيرمي TypeError أو ValueError وقت
التشغيل ويُسقط التقرير بأكمله. هذا الموديول يقدّم تحويلاً واحداً صحيحاً.
"""
from __future__ import annotations
from typing import Any


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """قراءة آمنة لكلا dict (DB row) و object (dataclass/SimpleNamespace)."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def status_of(obj: Any) -> int:
    """status_code كرقم صحيح. None/str/مشوّش ⇒ 0 (لا exception)."""
    raw = _get(obj, "status_code", 0)
    if raw is None:
        return 0
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    try:
        # نتحمّل '"301 Moved"' و' "  200 " ' وما شابه
        return int(str(raw).split()[0])
    except (ValueError, IndexError, AttributeError):
        return 0


def is_2xx(obj: Any) -> bool:
    s = status_of(obj)
    return 200 <= s < 300


def is_3xx(obj: Any) -> bool:
    s = status_of(obj)
    return 300 <= s < 400


def is_4xx(obj: Any) -> bool:
    s = status_of(obj)
    return 400 <= s < 500


def is_5xx(obj: Any) -> bool:
    s = status_of(obj)
    return 500 <= s < 600


def int_or_zero(value: Any) -> int:
    """قراءة آمنة لأيّ قيمة كـint — لا يرمي ValueError."""
    if value is None:
        return 0
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    try:
        return int(str(value).split()[0])
    except (ValueError, IndexError, AttributeError):
        return 0
