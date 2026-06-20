"""
crawler/robots_parser.py
=========================
قراءة وتحليل robots.txt:
- التحقق من الـ URLs المسموحة/المحظورة
- استخراج Sitemaps المُعلَنة
- احترام Crawl-Delay
"""

from typing import Optional
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

from utils.logger import get_logger

log = get_logger(__name__)


class RobotsParser:
    """
    معالج robots.txt للموقع.

    Example:
        >>> robots = RobotsParser("https://example.com/", "MyBot/1.0")
        >>> robots.load()
        >>> robots.can_fetch("https://example.com/category/books")
        True
        >>> robots.get_sitemaps()
        ['https://example.com/sitemap.xml']
    """

    def __init__(
        self,
        site_url: str,
        user_agent: str = "*",
        failure_policy: str = "allow",
        verify_ssl: bool = True,
        timeout: int = 10,
    ):
        """
        Args:
            site_url: رابط الموقع (سيُضاف /robots.txt تلقائياً)
            user_agent: اسم الزاحف للتحقق
        """
        self.site_url = site_url
        self.user_agent = user_agent
        self.failure_policy = failure_policy
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.robots_url = urljoin(site_url, "/robots.txt")
        self.parser = RobotFileParser()
        self.parser.set_url(self.robots_url)
        self._loaded = False
        self._sitemaps: list[str] = []
        self._crawl_delay: Optional[float] = None

    def load(self) -> bool:
        """
        تحميل وتحليل robots.txt.

        Returns:
            bool: True إذا نجح التحميل
        """
        try:
            import requests

            # نُحمّل robots.txt تدفقياً مع سقف حجم (ملف robots.txt المشروع صغير؛
            # السقف يمنع استنزاف الذاكرة من ردّ ضخم أو قنبلة ضغط).
            max_bytes = 2 * 1024 * 1024  # 2MB
            response = requests.get(
                self.robots_url,
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout,
                verify=self.verify_ssl,
                stream=True,
            )
            try:
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"robots.txt returned HTTP {response.status_code}"
                    )
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise RuntimeError("robots.txt يتجاوز الحدّ الأقصى (2MB)")
                    chunks.append(chunk)
            finally:
                response.close()
            encoding = response.encoding or "utf-8"
            robots_text = b"".join(chunks).decode(encoding, errors="replace")

            self.parser.parse(robots_text.splitlines())
            self._loaded = True

            # استخراج Sitemaps
            self._extract_sitemaps(robots_text)

            # استخراج Crawl-Delay
            self._extract_crawl_delay()

            log.info(f"تم تحميل robots.txt من: {self.robots_url}")
            log.info(f"  Sitemaps: {len(self._sitemaps)}")
            if self._crawl_delay:
                log.info(f"  Crawl-Delay: {self._crawl_delay}s")

            return True

        except Exception:
            log.warning("فشل تحميل robots.txt", exc_info=True)
            self._loaded = False
            return False

    def _extract_sitemaps(self, robots_text: str) -> None:
        """استخراج روابط Sitemap من robots.txt."""
        self._sitemaps.clear()
        for line in robots_text.splitlines():
            line = line.strip()
            if line.lower().startswith("sitemap:"):
                sitemap_url = line.split(":", 1)[1].strip()
                if sitemap_url:
                    self._sitemaps.append(sitemap_url)

    def _extract_crawl_delay(self) -> None:
        """استخراج Crawl-Delay المُحدَّد للـ User-Agent."""
        try:
            delay = self.parser.crawl_delay(self.user_agent)
            if delay:
                self._crawl_delay = float(delay)
        except Exception:
            self._crawl_delay = None

    def can_fetch(self, url: str) -> bool:
        """
        التحقق هل المسموح زحف هذا الـ URL.

        Args:
            url: الرابط المطلوب فحصه

        Returns:
            bool: True إذا كان مسموحاً (أو لم يُحمَّل robots.txt)
        """
        if not self._loaded:
            return self.failure_policy != "deny"

        try:
            return self.parser.can_fetch(self.user_agent, url)
        except Exception as e:
            log.debug(f"خطأ في can_fetch لـ {url}: {e}")
            return True

    def get_sitemaps(self) -> list[str]:
        """قائمة الـ Sitemaps المُعلَنة في robots.txt."""
        return self._sitemaps.copy()

    def get_crawl_delay(self) -> Optional[float]:
        """الـ Crawl-Delay المُحدَّد (أو None إذا غير موجود)."""
        return self._crawl_delay

    def is_loaded(self) -> bool:
        """هل تم تحميل robots.txt بنجاح؟"""
        return self._loaded
