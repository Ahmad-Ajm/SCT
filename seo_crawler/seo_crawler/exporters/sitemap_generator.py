"""
exporters/sitemap_generator.py
==============================
مولّد Sitemap XML نظيف من الصفحات القابلة للفهرسة المُكتشَفة بالزحف (IMP-5).

يلتزم معيار sitemaps.org 0.9: يُدرِج فقط الصفحات (status 200 + indexable + غير محظورة
بـ canonical يشير لغيرها)، مع `lastmod` اختياري. يحترم سقف 50,000 رابط لكل ملف؛ عند التجاوز
يقسّم إلى عدّة ملفات مع ملف فهرس (sitemap index).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape

from utils.logger import get_logger

log = get_logger(__name__)

_MAX_PER_FILE = 50000  # حدّ بروتوكول Sitemap


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _is_eligible(page: Any) -> bool:
    """هل تُدرَج الصفحة في الـ sitemap؟ (قابلة للفهرسة، 200، وقانونيّتها ذاتية أو غائبة)."""
    try:
        status = int(_get(page, "status_code", 0) or 0)
    except (TypeError, ValueError):
        status = 0
    if status != 200:
        return False
    if not _get(page, "is_indexable", False):
        return False
    url = _get(page, "url", "")
    if not url:
        return False
    canonical = _get(page, "canonical", "") or ""
    # إن وُجد canonical يشير لصفحة أخرى، لا نُدرِج هذه (الأصل سيُدرَج بنفسه)
    if canonical and canonical.rstrip("/") != str(url).rstrip("/"):
        return False
    return True


def _lastmod(page: Any) -> str:
    for field in ("last_modified", "lastmod", "crawled_at", "fetch_time"):
        v = _get(page, field, "")
        if v:
            # نأخذ جزء التاريخ فقط (YYYY-MM-DD) إن كان timestamp كاملاً
            s = str(v)
            return s[:10] if len(s) >= 10 else s
    return ""


def _eligible_urls(pages: list[Any]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for p in pages or []:
        if not _is_eligible(p):
            continue
        url = str(_get(p, "url", ""))
        if url in seen:
            continue
        seen.add(url)
        out.append((url, _lastmod(p)))
    return out


def _write_urlset(path: Path, urls: list[tuple[str, str]]) -> None:
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url, lastmod in urls:
        parts.append("  <url>")
        parts.append(f"    <loc>{escape(url)}</loc>")
        if lastmod:
            parts.append(f"    <lastmod>{escape(lastmod)}</lastmod>")
        parts.append("  </url>")
    parts.append("</urlset>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


class SitemapGenerator:
    """يولّد sitemap.xml (أو عدّة ملفات + فهرس) من الصفحات المزحوفة."""

    def __init__(self, output_dir: str, base_url: Optional[str] = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = (base_url or "").rstrip("/")

    def generate(self, pages: list[Any]) -> dict[str, Any]:
        """يكتب الـ sitemap ويعيد المسار/المسارات وعدد الروابط."""
        urls = _eligible_urls(pages)
        if not urls:
            log.info("Sitemap: لا توجد صفحات قابلة للفهرسة — لم يُكتَب ملف")
            return {"files": [], "url_count": 0}

        if len(urls) <= _MAX_PER_FILE:
            path = self.output_dir / "sitemap.xml"
            _write_urlset(path, urls)
            log.info(f"تم توليد sitemap.xml ({len(urls)} رابط)")
            return {"files": [str(path)], "url_count": len(urls)}

        # تقسيم + ملف فهرس
        files: list[str] = []
        chunks = [urls[i:i + _MAX_PER_FILE] for i in range(0, len(urls), _MAX_PER_FILE)]
        for idx, chunk in enumerate(chunks, start=1):
            p = self.output_dir / f"sitemap_{idx}.xml"
            _write_urlset(p, chunk)
            files.append(str(p))
        index_path = self.output_dir / "sitemap.xml"
        parts = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for idx in range(1, len(chunks) + 1):
            loc = f"{self.base_url}/sitemap_{idx}.xml" if self.base_url else f"sitemap_{idx}.xml"
            parts.append(f"  <sitemap><loc>{escape(loc)}</loc></sitemap>")
        parts.append("</sitemapindex>")
        index_path.write_text("\n".join(parts) + "\n", encoding="utf-8")
        files.insert(0, str(index_path))
        log.info(f"تم توليد sitemap مقسّم: {len(chunks)} ملف + فهرس ({len(urls)} رابط)")
        return {"files": files, "url_count": len(urls)}
