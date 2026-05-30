"""
reporting/url_detail.py
=======================
يبني صورة شاملة لرابط واحد بدمج كل المصادر المتاحة في تدقيق SCT (الزحف + GSC + GA4 +
PageSpeed + محرّك الأولويات + الوصولية) — لاستعمالها في لوحة «تفاصيل الرابط» في الواجهة.

دالّة نقية: تأخذ قاموس التدقيق المُحمَّل + رابطاً، وتُرجع قاموساً مُنظَّماً. كل المطابقات
عبر `normalize_url` كي تتّسق مع باقي المحرّك، وGA4 يُطابَق بالمسار لأنّه يُرجع paths.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from utils.helpers import normalize_url


# الحقول المهمّة من بيانات الصفحة (نُبرزها في الواجهة)
_PAGE_FIELDS = (
    "url", "final_url", "status_code", "is_indexable", "depth", "content_type",
    "title", "title_length", "meta_description", "meta_description_length",
    "h1_count", "h1_text", "canonical", "word_count", "internal_links_count",
    "outlinks_count", "robots_meta", "lang", "size_bytes",
)

# مقاييس PageSpeed المختصرة (لكل استراتيجية)
_PS_FIELDS = (
    "strategy", "performance_score", "accessibility_score", "best_practices_score",
    "seo_score", "lcp_lab_ms", "cls_lab", "tbt_lab_ms", "crux_overall",
)


def _path_of(url: str) -> str:
    try:
        p = (urlparse(url).path or "/").lower()
    except ValueError:
        return "/"
    return p.rstrip("/") or "/" if len(p) > 1 else p


def _pick(obj: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(obj, dict):
        return {}
    return {f: obj.get(f) for f in fields if f in obj}


def build_url_detail(audit: dict[str, Any], url: str) -> dict[str, Any]:
    """يُجمع كل ما تعرفه الأداة عن رابط واحد في قاموس مُنظَّم."""
    if not url:
        return {"url": "", "error": "missing_url"}
    target = normalize_url(url)
    target_path = _path_of(url)
    integ = (audit or {}).get("integrations", {}) or {}

    # 1) بيانات الصفحة من الزحف
    page: dict[str, Any] | None = None
    for p in (audit or {}).get("pages", []) or []:
        u = p.get("url") if isinstance(p, dict) else None
        if u and normalize_url(u) == target:
            page = _pick(p, _PAGE_FIELDS)
            break

    # 2) GSC (مطابقة بالـ URL المُطبَّع)
    gsc: dict[str, Any] | None = None
    for g in integ.get("gsc_pages", []) or []:
        if not isinstance(g, dict):
            continue
        gu = g.get("page") or g.get("url") or ""
        if gu and normalize_url(gu) == target:
            gsc = {
                "clicks": g.get("clicks", 0),
                "impressions": g.get("impressions", 0),
                "ctr": g.get("ctr", 0),
                "position": g.get("position", 0),
            }
            break

    # 2b) URL Inspection (إن جُلب)
    index_status: dict[str, Any] | None = None
    for r in integ.get("gsc_index_status", []) or []:
        if isinstance(r, dict) and r.get("url") and normalize_url(r["url"]) == target:
            index_status = {k: r.get(k) for k in (
                "verdict", "coverage_state", "robots_txt_state", "indexing_state",
                "page_fetch_state", "last_crawl_time", "google_canonical",
                "user_canonical", "mobile_verdict", "rich_results_verdict",
            )}
            break

    # 3) GA4 (مطابقة بالمسار)
    ga4: dict[str, Any] | None = None
    for a in integ.get("ga4_landing_pages", []) or []:
        if not isinstance(a, dict):
            continue
        ap = a.get("path") or a.get("landing_page") or a.get("page_path") or ""
        if ap and _path_of(ap if str(ap).startswith("http") else "http://x" + str(ap)) == target_path:
            ga4 = {
                "sessions": a.get("sessions", 0),
                "users": a.get("users") or a.get("active_users", 0),
                "engagement_rate": a.get("engagement_rate", 0),
                "conversions": a.get("conversions") or a.get("key_events", 0),
            }
            break

    # 4) PageSpeed (يمكن وجود نتائج متعدّدة لاستراتيجيات مختلفة)
    pagespeed: list[dict[str, Any]] = []
    for r in integ.get("pagespeed", []) or []:
        if not isinstance(r, dict):
            continue
        ru = r.get("url") or r.get("final_url") or ""
        if ru and normalize_url(ru) == target:
            pagespeed.append(_pick(r, _PS_FIELDS))

    # 5) محرّك الأولويات
    priority: dict[str, Any] | None = None
    for p in ((audit or {}).get("priority", {}) or {}).get("pages", []) or []:
        if isinstance(p, dict) and p.get("url") and normalize_url(p["url"]) == target:
            priority = {k: p.get(k) for k in (
                "page_type", "priority_score", "priority_band", "action_group",
                "owner", "ease", "tech_issue_count", "technical_issues", "top_fix",
                "reason", "factor_severity", "factor_demand", "factor_business",
                "factor_importance", "factor_ease", "factor_confidence",
            )}
            break

    # 6) الوصولية (axe-core)
    accessibility: dict[str, Any] | None = None
    for s in (audit or {}).get("accessibility", []) or []:
        if isinstance(s, dict) and s.get("url") and normalize_url(s["url"]) == target:
            accessibility = {
                "violations_count": s.get("violations_count", 0),
                "nodes_total": s.get("nodes_total", 0),
                "by_impact": s.get("by_impact", {}) or {},
            }
            break

    found = any([page, gsc, ga4, pagespeed, priority, accessibility, index_status])
    return {
        "url": url,
        "found": found,
        "page": page,
        "gsc": gsc,
        "index_status": index_status,
        "ga4": ga4,
        "pagespeed": pagespeed,
        "priority": priority,
        "accessibility": accessibility,
    }
