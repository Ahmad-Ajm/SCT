"""
analyzers/broken_links.py
==========================
كشف الروابط المكسورة (4xx, 5xx) في الموقع.

أنواع المشاكل المُكتشفة:
- صفحات داخلية 404 (مع inlinks)
- صفحات داخلية 5xx
- روابط خارجية مكسورة (اختياري - يحتاج فحص إضافي)
- صور 404
"""

from collections import defaultdict
from typing import Any

from analyzers._coerce import status_of  # v1.09-B2
from crawler.core import PageData
from utils.helpers import normalize_url


def _get(item: Any, key: str, default: Any = None) -> Any:
    """Read a field from either a PageData object or a dict row (DB-backed)."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def detect_broken_links(
    pages: list[PageData], all_links: list[dict[str, Any]]
) -> dict[str, Any]:
    """
    كشف الروابط المكسورة.

    Returns:
        dict: تقرير شامل
    """
    # === صفحات 4xx ===
    pages_4xx = [
        {
            "url": _get(page, "url", ""),
            "status_code": _get(page, "status_code", 0),
            "depth": _get(page, "depth", 0),
            "title": _get(page, "title", "") or "",
        }
        for page in pages
        if 400 <= status_of(page) < 500
    ]

    # === صفحات 5xx ===
    pages_5xx = [
        {
            "url": _get(page, "url", ""),
            "status_code": _get(page, "status_code", 0),
            "depth": _get(page, "depth", 0),
            "title": _get(page, "title", "") or "",
        }
        for page in pages
        if 500 <= status_of(page) < 600
    ]

    # === فهرسة الروابط حسب الوجهة مرة واحدة (يتفادى O(n²) وعدم تطابق التطبيع) ===
    links_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for link in all_links:
        norm = link.get("to_url_normalized") or normalize_url(link.get("to_url", ""))
        if norm:
            links_by_target[norm].append(link)

    # === صفحات 404 لها inlinks (الأخطر!) ===
    pages_404_with_inlinks = []
    for page in pages:
        if status_of(page) != 404:
            continue

        page_url = _get(page, "url", "")
        inlinks = links_by_target.get(normalize_url(page_url), [])
        if inlinks:
            pages_404_with_inlinks.append(
                {
                    "url": page_url,
                    "inlinks_count": len(inlinks),
                    "linking_from": list(
                        {link.get("from_url", "") for link in inlinks[:10]} - {""}
                    ),
                }
            )

    # === روابط خارجية ===
    external_links = [
        link for link in all_links
        if not link.get("is_internal") and not link.get("is_special_link")
    ]
    external_unique_urls = set(link.get("to_url", "") for link in external_links)

    return {
        "pages_4xx": pages_4xx,
        "pages_4xx_count": len(pages_4xx),
        "pages_5xx": pages_5xx,
        "pages_5xx_count": len(pages_5xx),
        "pages_404_with_inlinks": pages_404_with_inlinks,
        "pages_404_with_inlinks_count": len(pages_404_with_inlinks),
        "external_links_total": len(external_links),
        "external_unique_urls": len(external_unique_urls),
        # ملاحظة: لفحص الروابط الخارجية، يحتاج طلب HEAD لكل رابط
        # هذا يُفعَّل في config إذا كان مطلوباً
    }
