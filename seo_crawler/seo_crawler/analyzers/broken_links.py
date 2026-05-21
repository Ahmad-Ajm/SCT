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

from typing import Any

from crawler.core import PageData


def detect_broken_links(
    pages: list[PageData], all_links: list[dict[str, Any]]
) -> dict[str, Any]:
    """
    كشف الروابط المكسورة.

    Returns:
        dict: تقرير شامل
    """
    # === تجميع pages حسب URL لإمكانية lookup سريع ===
    page_by_url: dict[str, PageData] = {}
    for page in pages:
        page_by_url[page.url] = page
        if page.final_url and page.final_url != page.url:
            page_by_url[page.final_url] = page

    # === صفحات 4xx ===
    pages_4xx = [
        {
            "url": page.url,
            "status_code": page.status_code,
            "depth": page.depth,
            "title": page.title or "",
        }
        for page in pages
        if 400 <= page.status_code < 500
    ]

    # === صفحات 5xx ===
    pages_5xx = [
        {
            "url": page.url,
            "status_code": page.status_code,
            "depth": page.depth,
            "title": page.title or "",
        }
        for page in pages
        if 500 <= page.status_code < 600
    ]

    # === صفحات 404 لها inlinks (الأخطر!) ===
    pages_404_with_inlinks = []
    for page in pages:
        if page.status_code != 404:
            continue

        # احسب inlinks لهذه الصفحة
        inlinks = [
            link
            for link in all_links
            if link.get("to_url_normalized") == page.url
            or link.get("to_url") == page.url
        ]

        if inlinks:
            pages_404_with_inlinks.append(
                {
                    "url": page.url,
                    "inlinks_count": len(inlinks),
                    "linking_from": list(set(link["from_url"] for link in inlinks[:10])),
                }
            )

    # === روابط خارجية ===
    external_links = [link for link in all_links if not link.get("is_internal")]
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
