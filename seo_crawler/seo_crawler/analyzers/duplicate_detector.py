"""
analyzers/duplicate_detector.py
================================
كشف المحتوى/Title/Description المكرر.
"""

from collections import defaultdict
from typing import Any

from crawler.core import PageData


def _get(item: Any, key: str, default: Any = None) -> Any:
    """Read a field from either a PageData object or a dict row (DB-backed)."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def detect_duplicates(pages: list[PageData]) -> dict[str, Any]:
    """
    اكتشاف التكرارات في الصفحات.

    Returns:
        dict: {
            "duplicate_titles": list,
            "duplicate_descriptions": list,
            "duplicate_h1": list,
            "duplicate_content": list,
            "duplicate_titles_count": int,
            ...
        }
    """
    # === تجميع حسب القيمة ===
    title_groups: dict[str, list[str]] = defaultdict(list)
    desc_groups: dict[str, list[str]] = defaultdict(list)
    h1_groups: dict[str, list[str]] = defaultdict(list)
    content_groups: dict[str, list[str]] = defaultdict(list)

    from analyzers._coerce import status_of  # v1.09-B2

    for page in pages:
        # تخطّي الصفحات الفاشلة. v1.09-B2: مقارنة آمنة مع status كـstring.
        if _get(page, "crawl_error") or status_of(page) != 200:
            continue

        # تخطّي الصفحات NoIndex
        if not _get(page, "is_indexable", False):
            continue

        url = _get(page, "url", "")
        title = _get(page, "title", "")
        meta_description = _get(page, "meta_description", "")
        h1_text = _get(page, "h1_text", []) or []
        content_hash = _get(page, "content_hash", "")

        if title:
            title_groups[str(title).strip().lower()].append(url)
        if meta_description:
            desc_groups[str(meta_description).strip().lower()].append(url)
        if h1_text:
            # نأخذ أول H1 فقط (h1_text قد يكون list أو string)
            first_h1 = h1_text[0] if isinstance(h1_text, list) else h1_text
            h1_groups[str(first_h1).strip().lower()].append(url)
        if content_hash:
            content_groups[content_hash].append(url)

    # === استخراج التكرارات (>1 URL لنفس القيمة) ===
    duplicate_titles = [
        {"value": title, "urls": urls, "count": len(urls)}
        for title, urls in title_groups.items()
        if len(urls) > 1
    ]
    duplicate_descriptions = [
        {"value": desc, "urls": urls, "count": len(urls)}
        for desc, urls in desc_groups.items()
        if len(urls) > 1
    ]
    duplicate_h1 = [
        {"value": h1, "urls": urls, "count": len(urls)}
        for h1, urls in h1_groups.items()
        if len(urls) > 1
    ]
    duplicate_content = [
        {"hash": hash_val, "urls": urls, "count": len(urls)}
        for hash_val, urls in content_groups.items()
        if len(urls) > 1
    ]

    return {
        "duplicate_titles": duplicate_titles,
        "duplicate_descriptions": duplicate_descriptions,
        "duplicate_h1": duplicate_h1,
        "duplicate_content": duplicate_content,
        "duplicate_titles_count": len(duplicate_titles),
        "duplicate_descriptions_count": len(duplicate_descriptions),
        "duplicate_h1_count": len(duplicate_h1),
        "duplicate_content_count": len(duplicate_content),
        # الصفحات المتأثرة (للعد)
        "pages_with_duplicate_title": sum(len(d["urls"]) for d in duplicate_titles),
        "pages_with_duplicate_description": sum(
            len(d["urls"]) for d in duplicate_descriptions
        ),
        "pages_with_duplicate_h1": sum(len(d["urls"]) for d in duplicate_h1),
        "pages_with_duplicate_content": sum(len(d["urls"]) for d in duplicate_content),
    }
