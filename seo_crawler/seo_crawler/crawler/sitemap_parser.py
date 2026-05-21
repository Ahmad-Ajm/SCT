"""
crawler/sitemap_parser.py
==========================
تحليل sitemap.xml و sitemap index files.

يدعم:
- Sitemap عادي (urlset)
- Sitemap Index (مجموعة Sitemaps)
- Sitemap مضغوط (.xml.gz)
- استخراج: URL, lastmod, changefreq, priority

ملاحظة أمنية: نستخدم defusedxml لحماية من XXE attacks
(External Entity Expansion, Billion Laughs, etc.)
"""

import gzip
from dataclasses import dataclass
from typing import Any, Optional

# نستخدم defusedxml للحماية من XXE attacks
try:
    from defusedxml.ElementTree import fromstring as safe_fromstring
    from defusedxml.ElementTree import ParseError as XMLParseError
    DEFUSEDXML_AVAILABLE = True
except ImportError:
    # fallback (تحذير: غير آمن!)
    from xml.etree.ElementTree import fromstring as safe_fromstring  # nosec B405
    from xml.etree.ElementTree import ParseError as XMLParseError  # nosec B405
    DEFUSEDXML_AVAILABLE = False

from crawler.http_client import HTTPClient
from utils.logger import get_logger

log = get_logger(__name__)

if not DEFUSEDXML_AVAILABLE:
    log.warning(
        "defusedxml غير مثبت - استخدام XML parser غير آمن! "
        "ثبّت: pip install defusedxml"
    )


@dataclass
class SitemapEntry:
    """صف من Sitemap."""

    url: str
    lastmod: Optional[str] = None
    changefreq: Optional[str] = None
    priority: Optional[float] = None
    source_sitemap: str = ""


class SitemapParser:
    """
    قارئ Sitemap موحّد.

    Example:
        >>> parser = SitemapParser(http_client)
        >>> entries = parser.parse("https://example.com/sitemap.xml")
        >>> for entry in entries:
        ...     print(entry.url)
    """

    # XML namespaces الشائعة
    NAMESPACES = {
        "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "image": "http://www.google.com/schemas/sitemap-image/1.1",
        "video": "http://www.google.com/schemas/sitemap-video/1.1",
        "news": "http://www.google.com/schemas/sitemap-news/0.9",
    }

    def __init__(self, http_client: HTTPClient):
        """
        Args:
            http_client: عميل HTTP لجلب Sitemaps
        """
        self.http_client = http_client
        self._all_entries: list[SitemapEntry] = []
        self._visited_sitemaps: set[str] = set()

    def parse(self, sitemap_url: str, max_depth: int = 3) -> list[SitemapEntry]:
        """
        تحليل sitemap بشكل تكراري (يتبع sitemap indexes).

        Args:
            sitemap_url: رابط الـ Sitemap
            max_depth: الحد الأقصى لعمق التداخل

        Returns:
            list[SitemapEntry]: كل الصفحات المُستخرجة
        """
        self._all_entries.clear()
        self._visited_sitemaps.clear()
        self._parse_recursive(sitemap_url, max_depth)
        return self._all_entries.copy()

    def _parse_recursive(self, sitemap_url: str, depth: int) -> None:
        """تحليل recursive للـ sitemaps."""
        if depth <= 0 or sitemap_url in self._visited_sitemaps:
            return

        self._visited_sitemaps.add(sitemap_url)

        log.info(f"جلب Sitemap: {sitemap_url}")
        response = self.http_client.get(sitemap_url)

        if not response.is_success:
            log.warning(f"فشل جلب Sitemap: {sitemap_url} (status: {response.status_code})")
            return

        # فك ضغط إذا كان .gz
        content = response.content
        if sitemap_url.endswith(".gz") or response.content_type == "application/x-gzip":
            try:
                content = gzip.decompress(content)
            except Exception as e:
                log.error(f"فشل فك ضغط Sitemap: {e}")
                return

        # تحليل XML (آمن من XXE attacks بفضل defusedxml)
        try:
            root = safe_fromstring(content)
        except XMLParseError as e:
            log.error(f"فشل تحليل XML لـ {sitemap_url}: {e}")
            return

        # إزالة namespace من tag name
        tag = self._strip_namespace(root.tag)

        if tag == "sitemapindex":
            self._handle_sitemap_index(root, depth)
        elif tag == "urlset":
            self._handle_urlset(root, sitemap_url)
        else:
            log.warning(f"نوع Sitemap غير معروف: {tag}")

    def _handle_sitemap_index(self, root: Any, depth: int) -> None:
        """معالجة sitemap index (مجموعة من sitemaps)."""
        sitemap_count = 0
        for sitemap_elem in root:
            if self._strip_namespace(sitemap_elem.tag) != "sitemap":
                continue

            loc_elem = sitemap_elem.find("sm:loc", self.NAMESPACES) or sitemap_elem.find("loc")
            if loc_elem is not None and loc_elem.text:
                self._parse_recursive(loc_elem.text.strip(), depth - 1)
                sitemap_count += 1

        log.info(f"تم العثور على {sitemap_count} sub-sitemap")

    def _handle_urlset(self, root: Any, source: str) -> None:
        """معالجة urlset (الـ URLs الفعلية)."""
        entries_added = 0

        for url_elem in root:
            if self._strip_namespace(url_elem.tag) != "url":
                continue

            entry = self._parse_url_entry(url_elem, source)
            if entry:
                self._all_entries.append(entry)
                entries_added += 1

        log.info(f"  → {entries_added} URL مُستخرج من {source}")

    def _parse_url_entry(
        self, url_elem: Any, source: str
    ) -> Optional[SitemapEntry]:
        """تحليل عنصر <url> واحد."""
        loc = self._find_child_text(url_elem, "loc")
        if not loc:
            return None

        priority = self._find_child_text(url_elem, "priority")
        try:
            priority_float = float(priority) if priority else None
        except ValueError:
            priority_float = None

        return SitemapEntry(
            url=loc.strip(),
            lastmod=self._find_child_text(url_elem, "lastmod"),
            changefreq=self._find_child_text(url_elem, "changefreq"),
            priority=priority_float,
            source_sitemap=source,
        )

    def _find_child_text(self, parent: Any, tag_name: str) -> Optional[str]:
        """البحث عن child element مع/بدون namespace وإرجاع نصه."""
        # جرّب مع namespace أولاً
        elem = parent.find(f"sm:{tag_name}", self.NAMESPACES)
        if elem is None:
            # جرّب بدون namespace
            elem = parent.find(tag_name)
        return elem.text.strip() if elem is not None and elem.text else None

    @staticmethod
    def _strip_namespace(tag: str) -> str:
        """إزالة namespace من XML tag: {ns}tag → tag."""
        if "}" in tag:
            return tag.split("}", 1)[1]
        return tag
