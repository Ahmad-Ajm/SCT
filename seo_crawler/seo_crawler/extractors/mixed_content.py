"""
extractors/mixed_content.py
============================
كشف Mixed Content — موارد HTTP داخل صفحة HTTPS.

أنواع Mixed Content:
1. Active Content (خطر جداً - تحجبه المتصفحات):
   - <script src="http://...">
   - <iframe src="http://...">
   - <link href="http://...stylesheet">
   - XMLHttpRequest / fetch لـ HTTP URLs

2. Passive Content (يُعرض مع تحذير):
   - <img src="http://...">
   - <video src="http://...">
   - <audio src="http://...">

3. Form Mixed Content (خطير جداً):
   - <form action="http://..."> داخل HTTPS
"""

from typing import Any
from urllib.parse import urljoin
from bs4 import BeautifulSoup


def detect_mixed_content(soup: BeautifulSoup, page_url: str) -> dict[str, Any]:
    """
    كشف Mixed Content في صفحة.

    Args:
        soup: BeautifulSoup
        page_url: رابط الصفحة (لمعرفة هل HTTPS)

    Returns:
        dict: {
            "has_mixed_content": bool,
            "is_https_page": bool,
            "active_mixed": list,   # خطر
            "passive_mixed": list,  # تحذير
            "form_mixed": list,     # خطر جداً
            "total_count": int,
        }
    """
    is_https = page_url.startswith("https://")

    # إذا الصفحة HTTP أصلاً، لا توجد مشكلة mixed content
    if not is_https:
        return {
            "has_mixed_content": False,
            "is_https_page": False,
            "active_mixed": [],
            "passive_mixed": [],
            "form_mixed": [],
            "total_count": 0,
        }

    active_mixed: list[dict[str, str]] = []
    passive_mixed: list[dict[str, str]] = []
    form_mixed: list[dict[str, str]] = []

    # === Active Mixed Content ===

    # Scripts
    for script in soup.find_all("script", src=True):
        src = script.get("src", "").strip()
        if _is_http_resource(src, page_url):
            active_mixed.append({
                "type": "script",
                "tag": "<script>",
                "url": _absolute_url(src, page_url),
                "severity": "blocked",
            })

    # Stylesheets
    for link in soup.find_all("link", rel="stylesheet", href=True):
        href = link.get("href", "").strip()
        if _is_http_resource(href, page_url):
            active_mixed.append({
                "type": "stylesheet",
                "tag": "<link>",
                "url": _absolute_url(href, page_url),
                "severity": "blocked",
            })

    # Iframes
    for iframe in soup.find_all("iframe", src=True):
        src = iframe.get("src", "").strip()
        if _is_http_resource(src, page_url):
            active_mixed.append({
                "type": "iframe",
                "tag": "<iframe>",
                "url": _absolute_url(src, page_url),
                "severity": "blocked",
            })

    # Object/Embed
    for obj in soup.find_all(["object", "embed"]):
        src = obj.get("src") or obj.get("data") or ""
        src = src.strip()
        if _is_http_resource(src, page_url):
            active_mixed.append({
                "type": obj.name,
                "tag": f"<{obj.name}>",
                "url": _absolute_url(src, page_url),
                "severity": "blocked",
            })

    # === Passive Mixed Content ===

    # Images
    for img in soup.find_all("img", src=True):
        src = img.get("src", "").strip()
        if _is_http_resource(src, page_url):
            passive_mixed.append({
                "type": "image",
                "tag": "<img>",
                "url": _absolute_url(src, page_url),
                "alt": img.get("alt", "").strip(),
                "severity": "warning",
            })

    # Video sources
    for video in soup.find_all("video"):
        # video src
        src = video.get("src", "").strip()
        if _is_http_resource(src, page_url):
            passive_mixed.append({
                "type": "video",
                "tag": "<video>",
                "url": _absolute_url(src, page_url),
                "severity": "warning",
            })
        # <source> inside video
        for source in video.find_all("source", src=True):
            src = source.get("src", "").strip()
            if _is_http_resource(src, page_url):
                passive_mixed.append({
                    "type": "video_source",
                    "tag": "<source>",
                    "url": _absolute_url(src, page_url),
                    "severity": "warning",
                })

    # Audio sources
    for audio in soup.find_all("audio"):
        src = audio.get("src", "").strip()
        if _is_http_resource(src, page_url):
            passive_mixed.append({
                "type": "audio",
                "tag": "<audio>",
                "url": _absolute_url(src, page_url),
                "severity": "warning",
            })
        for source in audio.find_all("source", src=True):
            src = source.get("src", "").strip()
            if _is_http_resource(src, page_url):
                passive_mixed.append({
                    "type": "audio_source",
                    "tag": "<source>",
                    "url": _absolute_url(src, page_url),
                    "severity": "warning",
                })

    # === Form Mixed Content ===

    for form in soup.find_all("form", action=True):
        action = form.get("action", "").strip()
        if _is_http_resource(action, page_url):
            form_mixed.append({
                "type": "form",
                "tag": "<form>",
                "url": _absolute_url(action, page_url),
                "method": form.get("method", "GET").upper(),
                "severity": "critical",  # خطير جداً!
            })

    # === Background images في style attributes ===
    # نفحص فقط أهم العناصر لتجنّب البطء
    for elem in soup.find_all(["body", "div", "section"], style=True):
        style = elem.get("style", "")
        if "http://" in style:
            # استخراج URLs من background-image
            import re
            urls = re.findall(r'url\(["\']?(http://[^)"\']+)', style)
            for url in urls:
                passive_mixed.append({
                    "type": "inline_style_image",
                    "tag": f"<{elem.name} style>",
                    "url": url,
                    "severity": "warning",
                })

    total_count = len(active_mixed) + len(passive_mixed) + len(form_mixed)

    return {
        "has_mixed_content": total_count > 0,
        "is_https_page": True,
        "active_mixed": active_mixed,
        "passive_mixed": passive_mixed,
        "form_mixed": form_mixed,
        "active_count": len(active_mixed),
        "passive_count": len(passive_mixed),
        "form_count": len(form_mixed),
        "total_count": total_count,
        # URLs مسطّحة للحفظ في DB
        "mixed_urls": [
            item["url"] for item in (active_mixed + passive_mixed + form_mixed)
        ],
    }


def _is_http_resource(url: str, page_url: str) -> bool:
    """
    التحقق إن كان المورد HTTP (mixed content).

    يتجاهل:
    - الروابط النسبية (لأنها ترث الـ scheme)
    - data: URIs
    - protocol-relative URLs (//example.com)
    - javascript: / mailto: / etc.
    """
    if not url:
        return False

    # data URIs
    if url.startswith("data:"):
        return False

    # protocol-relative
    if url.startswith("//"):
        return False

    # javascript / mailto / tel
    if url.startswith(("javascript:", "mailto:", "tel:", "sms:")):
        return False

    # نسبي
    if not url.startswith(("http://", "https://")):
        return False

    # HTTPS = آمن
    return url.startswith("http://")


def _absolute_url(url: str, base: str) -> str:
    """تحويل URL لشكل مطلق."""
    try:
        return urljoin(base, url)
    except Exception:
        return url
