"""
analyzers/thin_content.py
==========================
كشف الصفحات ذات المحتوى الرقيق (Thin Content) - مهم لـ SEO.
"""

from typing import Any

from crawler.core import PageData


def detect_thin_content(
    pages: list[PageData],
    word_threshold: int = 300,
    critical_threshold: int = 100,
    text_ratio_threshold: float = 10.0,
) -> dict[str, Any]:
    """
    كشف الصفحات ذات المحتوى الرقيق.

    Args:
        pages: قائمة الصفحات
        word_threshold: الحد الأدنى الموصى به للكلمات
        critical_threshold: الحد الحرج (أقل منه = مشكلة كبيرة)
        text_ratio_threshold: الحد الأدنى لنسبة Text-to-HTML

    Returns:
        dict: تقرير شامل
    """
    thin_pages = []
    critical_thin = []
    low_text_ratio = []

    for page in pages:
        # تخطّي الصفحات الفاشلة
        if page.crawl_error or page.status_code != 200:
            continue

        # تخطّي non-HTML
        if not page.content_type or "html" not in page.content_type.lower():
            continue

        page_data = {
            "url": page.url,
            "title": page.title,
            "word_count": page.word_count,
            "character_count": page.character_count,
            "text_to_html_ratio": page.text_to_html_ratio,
            "is_indexable": page.is_indexable,
            "depth": page.depth,
        }

        # محتوى رقيق حرج
        if page.word_count < critical_threshold and page.word_count > 0:
            critical_thin.append(page_data)
        # محتوى رقيق عادي
        elif page.word_count < word_threshold:
            thin_pages.append(page_data)

        # نسبة text-to-html منخفضة
        if 0 < page.text_to_html_ratio < text_ratio_threshold:
            low_text_ratio.append(page_data)

    return {
        "thin_content_pages": thin_pages,
        "thin_content_count": len(thin_pages),
        "critical_thin_pages": critical_thin,
        "critical_thin_count": len(critical_thin),
        "low_text_ratio_pages": low_text_ratio,
        "low_text_ratio_count": len(low_text_ratio),
        "word_threshold_used": word_threshold,
        "critical_threshold_used": critical_threshold,
    }
