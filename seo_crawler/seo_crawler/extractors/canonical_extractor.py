"""
extractors/canonical_extractor.py
==================================
استخراج Canonical URL من:
- <link rel="canonical"> في HTML
- Link header في HTTP response
"""

from urllib.parse import urljoin
from bs4 import BeautifulSoup

from utils.helpers import normalize_url


def extract_canonical(
    soup: BeautifulSoup, headers: dict[str, str], current_url: str
) -> dict[str, str | bool]:
    """
    استخراج canonical URL.

    Args:
        soup: BeautifulSoup
        headers: HTTP response headers
        current_url: الرابط الحالي للمقارنة

    Returns:
        dict: {
            "canonical": str,
            "canonical_raw": str (قبل التطبيع),
            "in_header": bool,
            "in_html": bool,
            "is_self": bool,
            "is_self_normalized": bool,
            "is_absolute": bool,
            "matches_protocol": bool,
        }
    """
    canonical = ""
    canonical_raw = ""
    in_header = False
    in_html = False

    # === 1. من HTTP Header (له الأولوية) ===
    link_header = headers.get("Link", "") or headers.get("link", "")
    if link_header and 'rel="canonical"' in link_header.lower():
        # استخراج URL من Link header
        # Format: <https://example.com>; rel="canonical"
        try:
            for link_part in link_header.split(","):
                link_part = link_part.strip()
                if 'rel="canonical"' in link_part.lower() or "rel=canonical" in link_part.lower():
                    if "<" in link_part and ">" in link_part:
                        url = link_part.split("<")[1].split(">")[0].strip()
                        canonical_raw = url
                        in_header = True
                        break
        except Exception:
            pass

    # === 2. من HTML <link rel="canonical"> ===
    canonical_tag = soup.find("link", rel="canonical")
    if canonical_tag and canonical_tag.get("href"):
        html_canonical = canonical_tag["href"].strip()
        in_html = True
        # إذا لم يكن في header، استخدم HTML
        if not canonical_raw:
            canonical_raw = html_canonical

    # === تطبيع وحل URL النسبي ===
    if canonical_raw:
        try:
            canonical = urljoin(current_url, canonical_raw)
            canonical = normalize_url(canonical)
        except Exception:
            canonical = canonical_raw

    # === مقارنات ===
    current_normalized = normalize_url(current_url)
    is_self = canonical == current_url if canonical else False
    is_self_normalized = canonical == current_normalized if canonical else False

    is_absolute = canonical_raw.startswith(("http://", "https://"))

    matches_protocol = True
    if canonical and current_url:
        try:
            from urllib.parse import urlparse
            canonical_scheme = urlparse(canonical).scheme
            current_scheme = urlparse(current_url).scheme
            matches_protocol = canonical_scheme == current_scheme
        except Exception:
            matches_protocol = True

    return {
        "canonical": canonical,
        "canonical_raw": canonical_raw,
        "in_header": in_header,
        "in_html": in_html,
        "is_self": is_self,
        "is_self_normalized": is_self_normalized,
        "is_absolute": is_absolute,
        "matches_protocol": matches_protocol,
    }
