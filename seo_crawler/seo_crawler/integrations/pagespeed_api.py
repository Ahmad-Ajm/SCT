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
        on_progress: Optional[Any] = None,
    ):
        """
        Args:
            api_key: مفتاح API من Google Cloud Console
            delay_seconds: التأخير بين الطلبات
            timeout: المهلة الزمنية لكل طلب
            cache: APICache instance (اختياري)
            cache_ttl_days: مدة صلاحية الـ cache
            raw_dir: حفظ JSON الخام لكل صفحة (اختياري)
            on_progress: callback(idx, total, url, strategy) لتحديث تقدّم الواجهة
        """
        self.api_key = api_key
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self.cache = cache
        self.cache_ttl_seconds = cache_ttl_days * 86400
        self.raw_dir = raw_dir  # حفظ تقرير Lighthouse الكامل (JSON خام) لكل صفحة
        self._cache_hits = 0
        self._cache_misses = 0
        self.on_progress = on_progress
        # v1.02: تجميع أخطاء الشبكة/DNS كي نُلخّصها في نهاية الجلسة بدل لوغ متضخّم
        # يحوي مفاتيح: {dns: int, timeout: int, http_429: int, http_5xx: int, other: int,
        # sample_urls: list[str]}
        self.error_stats: dict[str, Any] = {
            "dns": 0, "timeout": 0, "http_429": 0, "http_5xx": 0,
            "other": 0, "sample_urls": [],
        }

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

        # بناء معاملات الطلب كقائمة أزواج — تُمرَّر عبر params= فلا يُبنى رابط
        # يحوي المفتاح السرّي في النص (يمنع تسرّب المفتاح إلى السجلّات).
        req_params: list[tuple[str, str]] = [
            ("url", url),
            ("strategy", strategy),
            ("key", self.api_key),
        ]
        req_params.extend(("category", cat) for cat in categories)

        # إعادة محاولة مع تراجع تصاعدي للأخطاء العابرة:
        # v1.02: نُعالج أيضاً أخطاء DNS / getaddrinfo / ConnectionError (انقطاع شبكة لحظي
        # شائع على Windows عند الإقلاع). نُعيد المحاولة بمهلات أطول لها لإعطاء DNS وقتاً.
        max_attempts = 4
        last_error = "Unknown"
        dns_backoff = [2.0, 5.0, 10.0]   # ثوانٍ — أوسع من الافتراضي للأخطاء العابرة DNS
        for attempt in range(max_attempts):
            try:
                response = requests.get(
                    self.BASE_URL, params=req_params, timeout=self.timeout
                )

                if response.status_code != 200:
                    # جسم الخطأ قد لا يكون JSON صالحاً — نحميه.
                    try:
                        error_msg = (
                            response.json().get("error", {}).get("message", "Unknown")
                        )
                    except ValueError:
                        error_msg = (response.text or "Unknown")[:200]
                    last_error = f"HTTP {response.status_code}: {error_msg}"
                    # أخطاء عابرة: أعد المحاولة؛ غير ذلك توقّف فوراً.
                    if response.status_code in (429, 500, 502, 503, 504) \
                            and attempt < max_attempts - 1:
                        if response.status_code == 429:
                            self.error_stats["http_429"] += 1
                        else:
                            self.error_stats["http_5xx"] += 1
                        time.sleep(self.delay_seconds * (2 ** attempt))
                        continue
                    self._record_error(url, "other")
                    log.debug(f"PageSpeed فشل لـ {url}: {error_msg}")
                    return {"url": url, "strategy": strategy, "error": last_error}

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
                last_error = "Timeout"
                if attempt < max_attempts - 1:
                    self.error_stats["timeout"] += 1
                    time.sleep(self.delay_seconds * (2 ** attempt))
                    continue
                self._record_error(url, "timeout")
                return {"url": url, "strategy": strategy, "error": "Timeout"}
            except requests.exceptions.ConnectionError as e:
                # v1.02: DNS / getaddrinfo / Network unreachable — أعد بمهلة أطول.
                # هذا أكثر الأخطاء شيوعاً وأقلّها استحقاقاً للوغ كامل لكلّ مرّة.
                msg = str(e)
                if "getaddrinfo" in msg or "NameResolutionError" in msg \
                        or "Name or service not known" in msg:
                    last_error = "DNS_resolution_failed"
                    self.error_stats["dns"] += 1
                else:
                    last_error = "ConnectionError"
                    self.error_stats["other"] += 1
                if attempt < max_attempts - 1:
                    backoff = dns_backoff[min(attempt, len(dns_backoff) - 1)]
                    log.debug(f"PageSpeed شبكة/DNS لـ {url} — محاولة #{attempt+2} بعد {backoff}s")
                    time.sleep(backoff)
                    continue
                self._record_error(url, "dns" if "getaddrinfo" in msg else "other")
                return {"url": url, "strategy": strategy, "error": last_error}
            except Exception as e:
                self._record_error(url, "other")
                log.debug(f"خطأ في PageSpeed لـ {url}: {e}")
                return {"url": url, "strategy": strategy, "error": str(e)[:200]}

        return {"url": url, "strategy": strategy, "error": last_error}

    def _record_error(self, url: str, kind: str) -> None:
        """يجمع عيّنة الروابط الفاشلة لتلخيصها في النهاية بدل لوغ متضخّم."""
        if len(self.error_stats["sample_urls"]) < 10:
            self.error_stats["sample_urls"].append({"url": url, "kind": kind})

    def log_error_summary(self) -> None:
        """ينشر سطراً واحداً ملخّصاً لأخطاء PageSpeed في نهاية الجلسة."""
        es = self.error_stats
        total = es["dns"] + es["timeout"] + es["http_429"] + es["http_5xx"] + es["other"]
        if total == 0:
            return
        log.warning(
            f"PageSpeed errors summary: total={total} | dns={es['dns']} "
            f"timeout={es['timeout']} http_429={es['http_429']} "
            f"http_5xx={es['http_5xx']} other={es['other']}"
        )

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
                # v1.02: تحديث تقدّم الواجهة (اسم الرابط الحالي + نسبة الإنجاز)
                if self.on_progress:
                    try:
                        self.on_progress(count, total, url, strategy)
                    except Exception:  # noqa: BLE001
                        pass
                result = self.audit(url, strategy=strategy)
                results.append(result)

        # v1.02: ملخّص أخطاء واحد في النهاية بدل لوغ متضخّم
        self.log_error_summary()
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

        # === الجداول المنظّمة العميقة (IMP-17أ) ===
        # تدقيقات فاشلة مُختصرة (تبقى في JSON/التقرير — صغيرة)، والجداول الكبيرة (audits/
        # network/treemap) تُستعمل لتصدير CSV فقط وتُستثنى من JSON لتفادي التضخّم.
        result["failed_audits"] = extract_failed_audits(data, url, strategy)
        result["lighthouse_tables"] = extract_lighthouse_tables(data, url, strategy)

        return result


# === استخراج جداول Lighthouse المنظّمة من الاستجابة الخام (IMP-17أ) ===
# دوال نقية قابلة للاختبار مباشرةً من ملف الخام، بلا أي نداء شبكة.

def _lh_audits(data: dict[str, Any]) -> dict[str, Any]:
    lr = data.get("lighthouseResult") or {}
    au = lr.get("audits") or {}
    return au if isinstance(au, dict) else {}


def extract_audit_rows(
    data: dict[str, Any], url: str, strategy: str
) -> list[dict[str, Any]]:
    """جدول كل تدقيقات Lighthouse (`lighthouseResult.audits`)."""
    rows: list[dict[str, Any]] = []
    for audit_id, a in _lh_audits(data).items():
        if not isinstance(a, dict):
            continue
        details = a.get("details") if isinstance(a.get("details"), dict) else {}
        rows.append({
            "url": url,
            "strategy": strategy,
            "audit_id": audit_id,
            "title": a.get("title", ""),
            "score": a.get("score"),
            "scoreDisplayMode": a.get("scoreDisplayMode", ""),
            "displayValue": a.get("displayValue", ""),
            "numericValue": a.get("numericValue"),
            "numericUnit": a.get("numericUnit", ""),
            "details_type": (details or {}).get("type", ""),
        })
    return rows


def extract_failed_audits(
    data: dict[str, Any], url: str, strategy: str
) -> list[dict[str, Any]]:
    """التدقيقات الفاشلة فقط — لتظهر كمشاكل حقيقية.

    الترشيح الآمن: `scoreDisplayMode ∈ {binary, numeric}` و`score` رقم فعلي و`score < 1`.
    (لا نستعمل `score < 1` وحدها لأنّ score قد يكون None في manual/notApplicable/informative
    فيرمي مقارنةً خاطئة ويُظهر إنذارات كاذبة.)
    """
    rows: list[dict[str, Any]] = []
    for audit_id, a in _lh_audits(data).items():
        if not isinstance(a, dict):
            continue
        mode = a.get("scoreDisplayMode")
        score = a.get("score")
        if mode in ("binary", "numeric") and isinstance(score, (int, float)) \
                and not isinstance(score, bool) and score < 1:
            rows.append({
                "url": url,
                "strategy": strategy,
                "audit_id": audit_id,
                "title": a.get("title", ""),
                "score": score,
                "scoreDisplayMode": mode,
                "displayValue": a.get("displayValue", ""),
            })
    return rows


def extract_network_request_rows(
    data: dict[str, Any], url: str, strategy: str
) -> list[dict[str, Any]]:
    """جدول طلبات الشبكة من `audits['network-requests'].details.items`."""
    nr = (_lh_audits(data).get("network-requests") or {})
    details = nr.get("details") if isinstance(nr.get("details"), dict) else {}
    items = (details or {}).get("items") or []
    rows: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        rows.append({
            "url": url,
            "strategy": strategy,
            # داخل العنصر الحقل اسمه url لكنه رابط الطلب — نُسمّيه request_url لتمييزه
            # عن رابط الصفحة المفحوصة.
            "request_url": it.get("url", ""),
            "resourceType": it.get("resourceType", ""),
            "transferSize": it.get("transferSize"),
            "resourceSize": it.get("resourceSize"),
            "statusCode": it.get("statusCode"),
            "protocol": it.get("protocol", ""),
            "priority": it.get("priority", ""),
            "mimeType": it.get("mimeType", ""),
            "networkRequestTime": it.get("networkRequestTime"),
            "networkEndTime": it.get("networkEndTime"),
            "entity": it.get("entity", ""),
        })
    return rows


def extract_treemap_rows(
    data: dict[str, Any], url: str, strategy: str
) -> list[dict[str, Any]]:
    """جدول خريطة JavaScript من `audits['script-treemap-data'].details.nodes`.

    نأخذ مستوى السكربت الأعلى لكل عقدة. `unusedPercent` يُحسَب (غير موجود جاهزاً).
    """
    tm = (_lh_audits(data).get("script-treemap-data") or {})
    details = tm.get("details") if isinstance(tm.get("details"), dict) else {}
    nodes = (details or {}).get("nodes") or []
    rows: list[dict[str, Any]] = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        resource_bytes = n.get("resourceBytes") or 0
        unused_bytes = n.get("unusedBytes") or 0
        pct = round(unused_bytes / resource_bytes * 100, 1) if resource_bytes else 0.0
        rows.append({
            "url": url,
            "strategy": strategy,
            "script_url": n.get("name", ""),  # الحقل الأصلي اسمه name
            "resourceBytes": resource_bytes,
            "encodedBytes": n.get("encodedBytes"),
            "unusedBytes": unused_bytes,
            "unusedPercent": pct,
        })
    return rows


def extract_lighthouse_tables(
    data: dict[str, Any], url: str, strategy: str
) -> dict[str, list[dict[str, Any]]]:
    """يجمع الجداول الكبيرة الثلاثة (للتصدير CSV)."""
    return {
        "audits": extract_audit_rows(data, url, strategy),
        "network_requests": extract_network_request_rows(data, url, strategy),
        "js_treemap": extract_treemap_rows(data, url, strategy),
    }
