"""
analyzers/orphan_finder.py
===========================
كشف الصفحات اليتيمة (Orphan Pages) — صفحات بدون روابط داخلية واردة.

الصفحة اليتيمة:
- موجودة في sitemap أو مكتشفة بالزحف
- لكن لا توجد روابط داخلية تشير إليها
- Google قد لا يجدها بسهولة
"""

from collections import defaultdict
from typing import Any

from analyzers._coerce import status_of  # L1-orphan: توحيد مع بقيّة المحلّلات
from crawler.core import PageData
from utils.helpers import normalize_url


def _get(item: Any, key: str, default: Any = None) -> Any:
    """Read a field from either a PageData object or a dict row (DB-backed)."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def find_orphan_pages(
    pages: list[PageData], all_links: list[dict[str, Any]]
) -> dict[str, Any]:
    """
    اكتشاف الصفحات اليتيمة وذات الروابط القليلة.

    Args:
        pages: قائمة الصفحات المُزحوفة
        all_links: كل الروابط المُكتشفة

    Returns:
        dict: {
            "orphan_pages": list,  # 0 inlinks
            "low_link_pages": list,  # 1-2 inlinks
            "inlink_counts": dict[url, count],
            "most_linked_pages": list[(url, count)],
            "least_linked_pages": list[(url, count)],
        }
    """
    # === حساب عدد inlinks لكل صفحة ===
    inlink_counts: dict[str, int] = defaultdict(int)

    for link in all_links:
        if not link.get("is_internal"):
            continue

        # نستخدم normalized URL للمقارنة الدقيقة
        to_url = link.get("to_url_normalized") or normalize_url(link.get("to_url", ""))
        from_url = link.get("from_url", "")

        # لا نحسب self-links
        if to_url == from_url:
            continue

        inlink_counts[to_url] += 1

    # === تصنيف الصفحات ===
    orphan_pages = []
    low_link_pages = []

    for page in pages:
        # تخطّي الصفحات الفاشلة والـ redirects
        # L1-orphan (v1.09-B2 class): نستعمل status_of() لا مقارنة status_code
        # الخام — عند إعادة استيراد الزحف من JSON يأتي status_code كسلسلة "200"
        # فتفشل "200" != 200 لكلّ الصفحات وتُخفى كلّ الصفحات اليتيمة بصمت.
        if _get(page, "crawl_error") or status_of(page) != 200:
            continue

        url = _get(page, "url", "")
        normalized_url = normalize_url(url)
        count = inlink_counts.get(normalized_url, 0)

        if count == 0:
            orphan_pages.append(
                {
                    "url": url,
                    "title": _get(page, "title", ""),
                    "depth": _get(page, "depth", 0),
                    "is_indexable": _get(page, "is_indexable", False),
                    "inlinks_count": 0,
                }
            )
        elif count <= 2:
            low_link_pages.append(
                {
                    "url": url,
                    "title": _get(page, "title", ""),
                    "depth": _get(page, "depth", 0),
                    "is_indexable": _get(page, "is_indexable", False),
                    "inlinks_count": count,
                }
            )

    # === Top/Bottom linked pages ===
    sorted_pages = sorted(inlink_counts.items(), key=lambda x: x[1], reverse=True)
    most_linked = sorted_pages[:20]
    # نتفادى تداخل القائمتين على المواقع الصغيرة (<40 صفحة مرتبطة)
    if len(sorted_pages) <= 40:
        least_linked = sorted_pages[len(most_linked):]
    else:
        least_linked = sorted_pages[-20:]

    return {
        "orphan_pages": orphan_pages,
        "low_link_pages": low_link_pages,
        "orphan_count": len(orphan_pages),
        "low_link_count": len(low_link_pages),
        "inlink_counts": dict(inlink_counts),
        "most_linked_pages": [
            {"url": url, "inlinks": count} for url, count in most_linked
        ],
        "least_linked_pages": [
            {"url": url, "inlinks": count} for url, count in least_linked
        ],
    }
