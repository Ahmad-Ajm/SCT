"""
extractors/resources_extractor.py
=================================
جرد موارد الصفحة: CSS, JS, images, fonts, media, iframes.

لكل مورد: النوع، الرابط المطلق، داخلي/خارجي، ومحتوى مختلط (HTTP داخل HTTPS).
فحص حالة المورد (status/size) اختياري ويتم لاحقاً عبر فاحص الروابط.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from utils.helpers import is_internal_url


def _as_list(rel: Any) -> list[str]:
    if isinstance(rel, list):
        return [str(r).lower() for r in rel]
    return [p.lower() for p in str(rel or "").split()]


def extract_resources(
    soup: Any,
    page_url: str,
    primary_domain: str,
    additional_domains: list[str] | None = None,
) -> list[dict[str, Any]]:
    """استخراج كل موارد الصفحة مع تصنيفها."""
    page_is_https = page_url.lower().startswith("https://")
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []

    def add(rtype: str, raw: str) -> None:
        raw = (raw or "").strip()
        if not raw or raw.startswith(("data:", "javascript:", "mailto:", "tel:", "#")):
            return
        url = urljoin(page_url, raw)
        if not url.lower().startswith(("http://", "https://")):
            return
        key = (rtype, url)
        if key in seen:
            return
        seen.add(key)
        out.append({
            "page_url": page_url,
            "url": url,
            "resource_type": rtype,
            "is_internal": is_internal_url(url, primary_domain, additional_domains),
            "is_mixed_content": page_is_https and url.lower().startswith("http://"),
        })

    if soup is None:
        return out

    # CSS + fonts (preload) + favicons عبر <link>
    for link in soup.find_all("link", href=True):
        rels = _as_list(link.get("rel"))
        if "stylesheet" in rels:
            add("css", link["href"])
        elif "preload" in rels and str(link.get("as", "")).lower() == "font":
            add("font", link["href"])
        elif any("icon" in r for r in rels):
            add("image", link["href"])

    # JavaScript
    for s in soup.find_all("script", src=True):
        add("js", s["src"])

    # الصور
    for img in soup.find_all("img", src=True):
        add("image", img["src"])

    # وسائط
    for tag in soup.find_all(["video", "audio", "source"], src=True):
        add("media", tag["src"])

    # iframes
    for fr in soup.find_all("iframe", src=True):
        add("iframe", fr["src"])

    return out
