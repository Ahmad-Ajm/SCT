"""
services/progress_service.py — كتابة ملف التقدّم للواجهة المرئية.

نُقل من main.py في v1.12 (Tier 0 leaf — لا يستورد من أيّ service آخر).
emit_phase هو الـhelper الأكثر تشاركاً (يُستدعى من 7+ مواقع: crawl_service,
external_check_service, integrations_service PageSpeed callback,
export_service report builder, integrations_only_service, main_async).
"""

from __future__ import annotations

import json
import os
from typing import Any

from utils.logger import get_logger

log = get_logger(__name__)


def emit_phase(crawler: Any, status: str, **extra: Any) -> None:
    """كتابة حالة المرحلة الحالية لملف التقدّم (للواجهة المرئية).

    ندمج مع آخر ملف تقدّم حتى لا نخسر عدادات مثل الطابور أو الروابط
    المفحوصة عند الانتقال بين المراحل.
    """
    pf = os.environ.get("SCT_PROGRESS_FILE")
    if not pf:
        return
    st = getattr(crawler, "stats", None)
    data: dict[str, Any] = {}
    try:
        if os.path.exists(pf):
            with open(pf, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        data = {}

    elapsed = getattr(st, "duration_seconds", None) if st else None
    data = {
        **data,
        "status": status,
        "pages_crawled": getattr(st, "pages_crawled", 0) if st else 0,
        "pages_failed": getattr(st, "pages_failed", 0) if st else 0,
        "pages_skipped": getattr(st, "pages_skipped", 0) if st else 0,
        **extra,
    }
    if elapsed is not None:
        data["elapsed_seconds"] = round(elapsed, 1)
        data["pages_per_second"] = round(getattr(st, "pages_per_second", 0), 2)
    try:
        tmp = pf + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, pf)
    except OSError:
        pass
