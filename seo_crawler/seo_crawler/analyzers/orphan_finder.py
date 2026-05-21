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

from crawler.core import PageData
from utils.helpers import normalize_url


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
        if page.crawl_error or page.status_code != 200:
            continue

        normalized_url = normalize_url(page.url)
        count = inlink_counts.get(normalized_url, 0)

        if count == 0:
            orphan_pages.append(
                {
                    "url": page.url,
                    "title": page.title,
                    "depth": page.depth,
                    "is_indexable": page.is_indexable,
                    "inlinks_count": 0,
                }
            )
        elif count <= 2:
            low_link_pages.append(
                {
                    "url": page.url,
                    "title": page.title,
                    "depth": page.depth,
                    "is_indexable": page.is_indexable,
                    "inlinks_count": count,
                }
            )

    # === Top/Bottom linked pages ===
    sorted_pages = sorted(inlink_counts.items(), key=lambda x: x[1], reverse=True)
    most_linked = sorted_pages[:20]
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
