"""
analyzers/duplicate_detector.py
================================
كشف المحتوى/Title/Description المكرر.
"""

from collections import defaultdict
from typing import Any

from crawler.core import PageData


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

    for page in pages:
        # تخطّي الصفحات الفاشلة
        if page.crawl_error or page.status_code != 200:
            continue

        # تخطّي الصفحات NoIndex
        if not page.is_indexable:
            continue

        if page.title:
            title_groups[page.title.strip().lower()].append(page.url)
        if page.meta_description:
            desc_groups[page.meta_description.strip().lower()].append(page.url)
        if page.h1_text:
            # نأخذ أول H1 فقط
            h1_groups[page.h1_text[0].strip().lower()].append(page.url)
        if page.content_hash:
            content_groups[page.content_hash].append(page.url)

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
