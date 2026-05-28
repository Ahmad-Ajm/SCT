"""
integrations/pagespeed_api.py
==============================
تكامل Google PageSpeed Insights API.

يفحص:
- Performance Score (Lab)
- Core Web Vitals (Field data من CrUX)
- Opportunities (تحسينات مقترحة)
- Diagnostics
- Accessibility Score
- SEO Score
- Best Practices Score

الحد المجاني: 25,000 طلب/يوم

يدعم الآن caching لتوفير الـ quota!
"""

import time
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from utils.logger import get_logger

log = get_logger(__name__)


class PageSpeedClient:
    """
    عميل PageSpeed Insights API مع cache support.

    Example:
        >>> from storage.cache import APICache
        >>> cache = APICache("./state/api_cache.db", default_ttl_days=7)
        >>> client = PageSpeedClient(api_key="...", cache=cache)
        >>> mobile = client.audit("https://example.com/", strategy="mobile")
        >>> # المرة التالية ستأتي من cache!
    """

    BASE_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

    def __init__(
        self,
        api_key: str,
        delay_seconds: float = 1.0,
        timeout: int = 60,
        cache: Optional[Any] = None,
        cache_ttl_days: int = 7,
        raw_dir: Optional[str] = None,
    ):
        """
        Args:
            api_key: مفتاح API من Google Cloud Console
            delay_seconds: التأخير بين الطلبات
            timeout: المهلة الزمنية لكل طلب
            cache: APICache instance (اختياري)
            cache_ttl_days: مدة صلاحية الـ cache
        """
        self.api_key = api_key
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self.cache = cache
        self.cache_ttl_seconds = cache_ttl_days * 86400
        self.raw_dir = raw_dir  # حفظ تقرير Lighthouse الكامل (JSON خام) لكل صفحة
        self._cache_hits = 0
        self._cache_misses = 0

    def audit(
        self,
        url: str,
        strategy: str = "mobile",
        categories: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """
        فحص صفحة واحدة.

        Args:
            url: الرابط
            strategy: "mobile" أو "desktop"
            categories: ["performance", "accessibility", "best-practices", "seo"]

        Returns:
            dict: نتيجة مُختصرة ومُنظَّمة
        """
        if not self.api_key:
            log.error("PageSpeed API key غير موجود")
            return {"url": url, "error": "No API key"}

        if categories is None:
            categories = ["performance", "accessibility", "best-practices", "seo"]

        # === محاولة القراءة من الـ cache أولاً ===
        cache_params = {"strategy": strategy, "categories": sorted(categories)}
        if self.cache:
            cached = self.cache.get("pagespeed", url, cache_params)
            if cached:
                self._cache_hits += 1
                log.debug(f"PageSpeed cache HIT: {url} ({strategy})")
                return cached

        self._cache_misses += 1

        # بناء الطلب
        params = {
            "url": url,
            "strategy": strategy,
            "key": self.api_key,
        }

        # إضافة categories كـ params متعددة
        category_params = [("category", cat) for cat in categories]
        full_url = f"{self.BASE_URL}?{urlencode(params)}&{urlencode(category_params)}"

        try:
            response = requests.get(full_url, timeout=self.timeout)

            if response.status_code != 200:
                error_msg = response.json().get("error", {}).get("message", "Unknown")
                log.warning(f"PageSpeed فشل لـ {url}: {error_msg}")
                return {
                    "url": url,
                    "strategy": strategy,
                    "error": f"HTTP {response.status_code}: {error_msg}",
                }

            data = response.json()

            # حفظ تقرير Lighthouse الكامل (الخام) إن طُلب — للتحليل العميق
            if self.raw_dir:
                self._save_raw(data, url, strategy)

            # تأخير لاحترام rate limits
            time.sleep(self.delay_seconds)

            # استخراج المقاييس
            result = self._extract_metrics(data, url, strategy)

            # === حفظ في الـ cache ===
            if self.cache and "error" not in result:
                self.cache.set(
                    "pagespeed", url, cache_params, result,
                    ttl_seconds=self.cache_ttl_seconds,
                )

            return result

        except requests.exceptions.Timeout:
            return {"url": url, "strategy": strategy, "error": "Timeout"}
        except Exception as e:
            log.error(f"خطأ في PageSpeed لـ {url}: {e}")
            return {"url": url, "strategy": strategy, "error": str(e)[:200]}

    def _save_raw(self, data: dict[str, Any], url: str, strategy: str) -> None:
        """يحفظ استجابة PageSpeed/Lighthouse الكاملة في ملف JSON لكل صفحة."""
        try:
            import json as _json
            import re
            from pathlib import Path

            d = Path(self.raw_dir)
            d.mkdir(parents=True, exist_ok=True)
            slug = re.sub(r"[^A-Za-z0-9._-]+", "_", url)[:80].strip("_") or "page"
            (d / f"{slug}__{strategy}.json").write_text(
                _json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except (OSError, ValueError) as e:
            log.debug(f"تعذّر حفظ raw PageSpeed لـ {url}: {e}")

    def get_cache_stats(self) -> dict[str, int]:
        """إحصائيات استخدام الـ cache."""
        total = self._cache_hits + self._cache_misses
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "total": total,
            "hit_rate": round(self._cache_hits / total * 100, 2) if total > 0 else 0,
        }

    def audit_bulk(
        self,
        urls: list[str],
        strategies: list[str] = None,
    ) -> list[dict[str, Any]]:
        """
        فحص قائمة من URLs (mobile + desktop).

        Args:
            urls: قائمة URLs
            strategies: ["mobile", "desktop"]

        Returns:
            list[dict]: نتائج كل URL × strategy
        """
        if strategies is None:
            strategies = ["mobile", "desktop"]

        results = []
        total = len(urls) * len(strategies)
        count = 0

        for url in urls:
            for strategy in strategies:
                count += 1
                log.info(f"[{count}/{total}] PageSpeed: {url} ({strategy})")
                result = self.audit(url, strategy=strategy)
                results.append(result)

        return results

    def _extract_metrics(
        self, data: dict[str, Any], url: str, strategy: str
    ) -> dict[str, Any]:
        """استخراج المقاييس المهمة من response."""
        result = {
            "url": url,
            "final_url": data.get("id", url),
            "strategy": strategy,
            "fetch_time": data.get("analysisUTCTimestamp", ""),
        }

        lighthouse = data.get("lighthouseResult", {})
        categories = lighthouse.get("categories", {})
        audits = lighthouse.get("audits", {})

        # === Scores ===
        for cat_name in ["performance", "accessibility", "best-practices", "seo"]:
            score = categories.get(cat_name, {}).get("score")
            result[f"{cat_name.replace('-', '_')}_score"] = (
                round(score * 100) if score is not None else None
            )

        # === Core Web Vitals (Lab) ===
        def get_audit_value(audit_id: str, field: str = "numericValue") -> Any:
            audit = audits.get(audit_id, {})
            return audit.get(field)

        result["lcp_lab_ms"] = get_audit_value("largest-contentful-paint")
        result["fcp_lab_ms"] = get_audit_value("first-contentful-paint")
        result["cls_lab"] = get_audit_value("cumulative-layout-shift")
        result["tbt_lab_ms"] = get_audit_value("total-blocking-time")
        result["si_lab_ms"] = get_audit_value("speed-index")
        result["tti_lab_ms"] = get_audit_value("interactive")

        # === Core Web Vitals (Field - من CrUX) ===
        # هذه البيانات الحقيقية من المستخدمين
        loading_experience = data.get("loadingExperience", {}).get("metrics", {})

        def get_field_value(metric: str) -> dict[str, Any]:
            m = loading_experience.get(metric, {})
            return {
                "percentile": m.get("percentile"),
                "category": m.get("category"),  # FAST, AVERAGE, SLOW
            }

        result["lcp_field"] = get_field_value("LARGEST_CONTENTFUL_PAINT_MS")
        result["fcp_field"] = get_field_value("FIRST_CONTENTFUL_PAINT_MS")
        result["cls_field"] = get_field_value("CUMULATIVE_LAYOUT_SHIFT_SCORE")
        result["inp_field"] = get_field_value("INTERACTION_TO_NEXT_PAINT")
        result["ttfb_field"] = get_field_value("EXPERIMENTAL_TIME_TO_FIRST_BYTE")

        # === Overall CrUX assessment ===
        overall = data.get("loadingExperience", {}).get("overall_category", "")
        result["crux_overall"] = overall

        # === Opportunities (أهم 10) ===
        opportunities = []
        for audit_id, audit in audits.items():
            if audit.get("details", {}).get("type") == "opportunity":
                savings = audit.get("details", {}).get("overallSavingsMs", 0)
                if savings > 0:
                    opportunities.append(
                        {
                            "id": audit_id,
                            "title": audit.get("title", ""),
                            "description": audit.get("description", "")[:200],
                            "savings_ms": savings,
                            "savings_bytes": audit.get("details", {}).get(
                                "overallSavingsBytes", 0
                            ),
                        }
                    )

        # ترتيب حسب التوفير
        opportunities.sort(key=lambda x: x["savings_ms"], reverse=True)
        result["opportunities"] = opportunities[:10]
        result["opportunities_total_count"] = len(opportunities)

        return result
