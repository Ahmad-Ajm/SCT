"""
integrations/crux_history.py
============================
اتجاه Core Web Vitals عبر الزمن من Chrome UX Report History API (IMP-9).

بخلاف PageSpeed (لقطة واحدة)، تُعيد هذه الواجهة سلسلة زمنية لبيانات الحقل الحقيقية
(p75 لكل مقياس عبر عدّة فترات أسبوعية) — لإظهار التحسّن/التدهور. اختياري، مطفأ افتراضياً،
ويستعمل `requests` فقط (بلا تبعية جديدة). المفتاح يأتي من إعداد محلي/متغيّر بيئة فقط.
"""

from __future__ import annotations

from typing import Any, Optional

import requests

from utils.logger import get_logger

log = get_logger(__name__)

_ENDPOINT = "https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord"
_METRICS = {
    "largest_contentful_paint": "lcp_p75_ms",
    "interaction_to_next_paint": "inp_p75_ms",
    "cumulative_layout_shift": "cls_p75",
    "first_contentful_paint": "fcp_p75_ms",
    "experimental_time_to_first_byte": "ttfb_p75_ms",
}


def _period_end(period: dict[str, Any]) -> str:
    last = (period or {}).get("lastDate") or {}
    if last:
        return f"{last.get('year',''):04}-{last.get('month',0):02}-{last.get('day',0):02}"
    return ""


def parse_crux_history(resp: dict[str, Any]) -> list[dict[str, Any]]:
    """يُسطّح استجابة CrUX History إلى صف لكل فترة (p75 لكل مقياس). دالّة نقية."""
    record = (resp or {}).get("record") or {}
    periods = record.get("collectionPeriods") or []
    metrics = record.get("metrics") or {}
    rows: list[dict[str, Any]] = []
    for i, period in enumerate(periods):
        row: dict[str, Any] = {"period_end": _period_end(period)}
        for api_name, col in _METRICS.items():
            m = metrics.get(api_name) or {}
            p75s = (m.get("percentilesTimeseries") or {}).get("p75s") or []
            row[col] = p75s[i] if i < len(p75s) else None
        rows.append(row)
    return rows


class CrUXHistoryClient:
    """عميل CrUX History API (اختياري، يتطلّب مفتاح PageSpeed/CrUX)."""

    def __init__(self, api_key: str, timeout: int = 30):
        self.api_key = api_key or ""
        self.timeout = timeout

    def query(
        self,
        url: Optional[str] = None,
        origin: Optional[str] = None,
        form_factor: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """يجلب السلسلة الزمنية لرابط (url) أو لكامل الأصل (origin)."""
        if not self.api_key:
            log.error("CrUX History: مفتاح API غير موجود")
            return []
        body: dict[str, Any] = {}
        if origin:
            body["origin"] = origin
        elif url:
            body["url"] = url
        else:
            return []
        if form_factor:
            body["formFactor"] = form_factor  # PHONE / DESKTOP / TABLET
        try:
            resp = requests.post(
                _ENDPOINT, params={"key": self.api_key}, json=body, timeout=self.timeout
            )
            if resp.status_code != 200:
                try:
                    msg = resp.json().get("error", {}).get("message", "")
                except ValueError:
                    msg = (resp.text or "")[:200]
                log.warning(f"CrUX History فشل ({resp.status_code}): {msg}")
                return []
            return parse_crux_history(resp.json())
        except requests.RequestException as e:
            log.error(f"CrUX History خطأ: {e}")
            return []
