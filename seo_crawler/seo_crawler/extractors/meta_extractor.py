"""
extractors/meta_extractor.py
=============================
استخراج Title و Meta tags الأساسية.
"""

from typing import Any
from bs4 import BeautifulSoup

from utils.helpers import pixel_width_estimate


def extract_meta(soup: BeautifulSoup) -> dict[str, Any]:
    """
    استخراج Title و Meta tags.

    Returns:
        dict: {
            "title": str,
            "title_length": int,
            "title_pixel_width": int,
            "meta_description": str,
            "meta_description_length": int,
            "meta_keywords": str,
            "meta_robots": str,
            "meta_viewport": str,
            "meta_charset": str,
            "meta_generator": str,
            "meta_author": str,
            "meta_refresh": str,
        }
    """
    # === Title ===
    title_tag = soup.find("title")
    title = title_tag.get_text().strip() if title_tag else ""

    # === Meta tags ===
    # دالة مساعدة للبحث عن meta tag
    def get_meta_content(name: str = None, prop: str = None, http_equiv: str = None) -> str:
        if name:
            tag = soup.find("meta", attrs={"name": name})
        elif prop:
            tag = soup.find("meta", attrs={"property": prop})
        elif http_equiv:
            tag = soup.find("meta", attrs={"http-equiv": http_equiv})
        else:
            return ""

        if tag and tag.get("content"):
            return tag["content"].strip()
        return ""

    meta_description = get_meta_content(name="description")
    meta_keywords = get_meta_content(name="keywords")
    meta_robots = get_meta_content(name="robots")
    meta_author = get_meta_content(name="author")
    meta_generator = get_meta_content(name="generator")
    meta_refresh = get_meta_content(http_equiv="refresh")

    # === Viewport (مهم للجوال) ===
    meta_viewport = get_meta_content(name="viewport")

    # === Charset ===
    meta_charset = ""
    charset_tag = soup.find("meta", attrs={"charset": True})
    if charset_tag:
        meta_charset = charset_tag.get("charset", "").strip()
    else:
        # محاولة من Content-Type
        content_type_tag = soup.find("meta", attrs={"http-equiv": "Content-Type"})
        if content_type_tag and content_type_tag.get("content"):
            content = content_type_tag["content"]
            if "charset=" in content.lower():
                meta_charset = content.lower().split("charset=")[1].strip()

    return {
        "title": title,
        "title_length": len(title),
        "title_pixel_width": pixel_width_estimate(title),
        "meta_description": meta_description,
        "meta_description_length": len(meta_description),
        "meta_keywords": meta_keywords,
        "meta_robots": meta_robots,
        "meta_viewport": meta_viewport,
        "meta_charset": meta_charset,
        "meta_generator": meta_generator,
        "meta_author": meta_author,
        "meta_refresh": meta_refresh,
    }
