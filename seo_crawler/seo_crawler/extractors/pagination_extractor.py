"""
extractors/pagination_extractor.py
==================================
استخراج روابط ترقيم الصفحات (pagination) عبر:
- <link rel="next"> / <link rel="prev"> في HTML
- rel=next / rel=prev في HTTP Link header (احتياطي)

تُعيد روابط مطلقة ومُطبَّعة لتسهيل ربطها لاحقاً بصفحات أخرى مزحوفة.
"""

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from utils.helpers import normalize_url


def _from_link_header(headers: dict[str, str], rel: str) -> str:
    """استخراج href لعلاقة (next/prev) من HTTP Link header."""
    link_header = headers.get("Link", "") or headers.get("link", "")
    if not link_header:
        return ""
    target = rel.lower()
    for part in link_header.split(","):
        part = part.strip()
        low = part.lower()
        if f'rel="{target}"' in low or f"rel={target}" in low:
            if "<" in part and ">" in part:
                return part.split("<", 1)[1].split(">", 1)[0].strip()
    return ""


def extract_pagination(
    soup: BeautifulSoup, headers: dict[str, str], current_url: str
) -> dict[str, str | bool]:
    """
    استخراج روابط rel=next / rel=prev.

    Returns:
        dict: {
            "pagination_next": str (مطلق ومطبَّع),
            "pagination_prev": str,
            "pagination_next_raw": str,
            "pagination_prev_raw": str,
            "pagination_source": "html" | "header" | "" ,
            "is_paginated": bool,
        }
    """
    next_raw = ""
    prev_raw = ""
    source = ""

    # === HTML <link rel="next/prev"> (له الأولوية) ===
    next_tag = soup.find("link", rel="next")
    if next_tag and next_tag.get("href"):
        next_raw = next_tag["href"].strip()
        source = "html"
    prev_tag = soup.find("link", rel="prev")
    if prev_tag and prev_tag.get("href"):
        prev_raw = prev_tag["href"].strip()
        source = "html"

    # === HTTP Link header (احتياطي عند غياب وسوم HTML) ===
    if not next_raw:
        h = _from_link_header(headers, "next")
        if h:
            next_raw = h
            source = source or "header"
    if not prev_raw:
        h = _from_link_header(headers, "prev")
        if h:
            prev_raw = h
            source = source or "header"

    def _abs(raw: str) -> str:
        if not raw:
            return ""
        try:
            return normalize_url(urljoin(current_url, raw))
        except Exception:
            return raw

    return {
        "pagination_next": _abs(next_raw),
        "pagination_prev": _abs(prev_raw),
        "pagination_next_raw": next_raw,
        "pagination_prev_raw": prev_raw,
        "pagination_source": source,
        "is_paginated": bool(next_raw or prev_raw),
    }
