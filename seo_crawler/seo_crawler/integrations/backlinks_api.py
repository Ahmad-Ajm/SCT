"""
integrations/backlinks_api.py
=============================
v1.04: تكاملات الروابط الخلفيّة الحيّة (Ahrefs / Majestic).

مطفأة افتراضياً وتحتاج مفاتيح مدفوعة. الـ AWT importer (CSV — مجاني للمواقع التي
تملكها) يبقى البديل غير المدفوع المُفضَّل لمعظم المستخدمين.

التصميم:
- كلّ كلاينت يقبل `api_key` + يُرجع `{summary, top_referring_domains, top_anchors,
  error}` بصيغة موحّدة كي يستطيع التقرير عرضها سواء كان المزوّد Ahrefs أو Majestic.
- HTTP عبر `requests` فقط (لا تبعيات إضافية).
- يحترم timeout قصيراً + لا يُسجّل المفتاح في الـURL (لمنع تسرّبه إلى وسطاء/وكلاء).
- على الفشل يُرجع dict فيه `error` نصّياً قصيراً (لا يرمي استثناءً يُسقط الجوب).

استخدم `BacklinksProvider.create(provider, api_key)` كنقطة دخول واحدة من main.py.
"""
from __future__ import annotations

from typing import Any, Optional

from utils.logger import get_logger

log = get_logger(__name__)


class _BaseBacklinks:
    """واجهة موحّدة لمزوّدي الروابط الخلفيّة."""

    name = "base"

    def __init__(self, api_key: str, timeout: int = 30):
        self.api_key = api_key
        self.timeout = timeout

    def fetch(self, site_url: str) -> dict[str, Any]:
        """يجلب ملخّصاً + أعلى نطاقات/نصوص روابط لـsite_url."""
        raise NotImplementedError


class AhrefsClient(_BaseBacklinks):
    """عميل Ahrefs API v3 (مدفوع — Standard خطة وأعلى).

    تنبيه: Ahrefs Webmaster Tools (المجاني) لا يُوفّر API عامّة — فقط لوحة + تصدير CSV.
    لاستخدام هذا الكلاينت تحتاج اشتراك Ahrefs Standard أو أعلى.

    Endpoints المستخدمة (v3):
    - GET /v3/site-explorer/overview — ملخّص نطاق
    - GET /v3/site-explorer/refdomains — أعلى نطاقات مُحيلة
    - GET /v3/site-explorer/anchors — توزيع نصوص الروابط
    """

    name = "ahrefs"
    BASE = "https://api.ahrefs.com"

    def fetch(self, site_url: str) -> dict[str, Any]:
        try:
            import requests
        except ImportError:
            return {"error": "requests_not_installed"}
        if not self.api_key:
            return {"error": "missing_api_key"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        params_common = {"target": site_url, "mode": "domain"}
        out: dict[str, Any] = {"provider": "ahrefs", "site_url": site_url}

        try:
            r = requests.get(
                f"{self.BASE}/v3/site-explorer/overview",
                headers=headers, params=params_common, timeout=self.timeout,
            )
            if r.status_code != 200:
                return {**out, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
            data = r.json()
            metrics = data.get("metrics") or data
            out["summary"] = {
                "domain_rating": metrics.get("domain_rating"),
                "backlinks_total": metrics.get("backlinks"),
                "referring_domains": metrics.get("refdomains"),
                "organic_traffic": metrics.get("traffic"),
            }
        except Exception as e:  # noqa: BLE001
            return {**out, "error": f"overview: {type(e).__name__}: {str(e)[:160]}"}

        # أعلى نطاقات مُحيلة (نطلب أوّل 50)
        try:
            r = requests.get(
                f"{self.BASE}/v3/site-explorer/refdomains",
                headers=headers,
                params={**params_common, "limit": 50, "order_by": "domain_rating:desc"},
                timeout=self.timeout,
            )
            if r.status_code == 200:
                items = (r.json() or {}).get("refdomains") or []
                out["top_referring_domains"] = [
                    {
                        "domain": it.get("domain"),
                        "domain_rating": it.get("domain_rating"),
                        "backlinks": it.get("backlinks"),
                        "first_seen": it.get("first_seen"),
                    }
                    for it in items[:50]
                ]
        except Exception as e:  # noqa: BLE001
            # v1.09-B9: warning بدل debug — العامل يحتاج إشارة عند فشل refdomains
            log.warning(f"Ahrefs refdomains failed: {e}")

        # توزيع نصوص الروابط
        try:
            r = requests.get(
                f"{self.BASE}/v3/site-explorer/anchors",
                headers=headers,
                params={**params_common, "limit": 30, "order_by": "backlinks:desc"},
                timeout=self.timeout,
            )
            if r.status_code == 200:
                items = (r.json() or {}).get("anchors") or []
                out["top_anchors"] = [
                    {"text": it.get("anchor"), "backlinks": it.get("backlinks")}
                    for it in items[:30]
                ]
        except Exception as e:  # noqa: BLE001
            log.warning(f"Ahrefs anchors failed: {e}")

        return out


class MajesticClient(_BaseBacklinks):
    """عميل Majestic API (مدفوع — يحتاج OpenApp key).

    Endpoint: https://api.majestic.com/api/json
    أوامر مستخدمة:
    - GetIndexItemInfo: ملخّص النطاق (TrustFlow, CitationFlow, RefDomains, ExtBackLinks).
    - GetTopBackLinks: أعلى الروابط الخلفية (نأخذ منها أعلى النطاقات المُحيلة).
    """

    name = "majestic"
    BASE = "https://api.majestic.com/api/json"

    def fetch(self, site_url: str) -> dict[str, Any]:
        try:
            import requests
        except ImportError:
            return {"error": "requests_not_installed"}
        if not self.api_key:
            return {"error": "missing_api_key"}

        out: dict[str, Any] = {"provider": "majestic", "site_url": site_url}
        # v1.09-B6: Majestic API لا يدعم Authorization header — المفتاح يبقى في
        # query param بحكم القيد. نُؤكّد عدم تسجيل `r.url` أو `r.request.url` في أيّ
        # log line: كل رسائل الفشل تستعمل `r.status_code` ونصّاً عاماً فقط.
        # 1) Overview
        try:
            r = requests.get(self.BASE, params={
                "app_api_key": self.api_key,
                "cmd": "GetIndexItemInfo",
                "items": 1,
                "item0": site_url,
                "datasource": "fresh",
            }, timeout=self.timeout)
            if r.status_code != 200:
                return {**out, "error": f"HTTP {r.status_code}"}
            data = r.json() or {}
            if data.get("Code") and data.get("Code") != "OK":
                return {**out, "error": f"Majestic: {data.get('ErrorMessage', data.get('Code'))}"}
            tbl = (data.get("DataTables") or {}).get("Results") or {}
            rows = tbl.get("Data") or []
            row = rows[0] if rows else {}
            out["summary"] = {
                "trust_flow": row.get("TrustFlow"),
                "citation_flow": row.get("CitationFlow"),
                "referring_domains": row.get("RefDomains"),
                "backlinks_total": row.get("ExtBackLinks"),
            }
        except Exception as e:  # noqa: BLE001
            return {**out, "error": f"overview: {type(e).__name__}: {str(e)[:160]}"}

        # 2) Top referring domains (نأخذ من GetTopBackLinks)
        try:
            r = requests.get(self.BASE, params={
                "app_api_key": self.api_key,
                "cmd": "GetTopBackLinks",
                "item": site_url,
                "Count": 50,
                "datasource": "fresh",
            }, timeout=self.timeout)
            if r.status_code == 200:
                data = r.json() or {}
                tbl = (data.get("DataTables") or {}).get("BackLinks") or {}
                rows = tbl.get("Data") or []
                # نُجمّع حسب النطاق المُحيل
                seen: dict[str, dict[str, Any]] = {}
                for row in rows:
                    from urllib.parse import urlparse
                    src = row.get("SourceURL") or ""
                    dom = urlparse(src).netloc.lower()
                    if not dom:
                        continue
                    e = seen.setdefault(dom, {
                        "domain": dom, "trust_flow_max": 0, "backlinks": 0,
                    })
                    e["backlinks"] += 1
                    tf = int(row.get("SourceTrustFlow", 0) or 0)
                    if tf > e["trust_flow_max"]:
                        e["trust_flow_max"] = tf
                out["top_referring_domains"] = sorted(
                    seen.values(),
                    key=lambda x: (-x["trust_flow_max"], -x["backlinks"]),
                )[:50]
        except Exception as e:  # noqa: BLE001
            log.warning(f"Majestic topbacklinks failed: {e}")

        return out


_PROVIDER_MAP = {
    "ahrefs": AhrefsClient,
    "majestic": MajesticClient,
}


class BacklinksProvider:
    """نقطة دخول واحدة لإنشاء كلاينت بحسب اسم المزوّد."""

    @staticmethod
    def create(provider: str, api_key: str, timeout: int = 30) -> Optional[_BaseBacklinks]:
        cls = _PROVIDER_MAP.get((provider or "").lower())
        if not cls:
            return None
        return cls(api_key=api_key, timeout=timeout)

    @staticmethod
    def known_providers() -> list[str]:
        return list(_PROVIDER_MAP.keys())
