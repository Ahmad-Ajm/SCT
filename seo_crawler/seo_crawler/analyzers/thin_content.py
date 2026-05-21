"""
analyzers/thin_content.py
==========================
كشف الصفحات ذات المحتوى الرقيق (Thin Content) - مهم لـ SEO.
"""

from typing import Any

from crawler.core import PageData


def _get(item: Any, key: str, default: Any = None) -> Any:
    """Read a field from either a PageData object or a dict row (DB-backed)."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


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
        if _get(page, "crawl_error") or _get(page, "status_code", 0) != 200:
            continue

        # تخطّي non-HTML
        content_type = _get(page, "content_type", "") or ""
        if "html" not in content_type.lower():
            continue

        word_count = int(_get(page, "word_count", 0) or 0)
        text_to_html_ratio = float(_get(page, "text_to_html_ratio", 0) or 0)

        page_data = {
            "url": _get(page, "url", ""),
            "title": _get(page, "title", ""),
            "word_count": word_count,
            "character_count": _get(page, "character_count", 0),
            "text_to_html_ratio": text_to_html_ratio,
            "is_indexable": _get(page, "is_indexable", False),
            "depth": _get(page, "depth", 0),
        }

        # محتوى رقيق حرج
        if 0 < word_count < critical_threshold:
            critical_thin.append(page_data)
        # محتوى رقيق عادي
        elif word_count < word_threshold:
            thin_pages.append(page_data)

        # نسبة text-to-html منخفضة
        if 0 < text_to_html_ratio < text_ratio_threshold:
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
