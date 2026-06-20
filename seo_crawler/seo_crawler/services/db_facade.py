"""
services/db_facade.py — واجهة قراءة-فقط من DB لـ--analyze-only و--integrations-only.

نُقل من main.py في v1.12 (Tier 1 — يستورد storage.database فقط).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from storage.database import CrawlDatabase


class AttrDict(dict):
    """Dictionary row that also supports attribute access for legacy analyzers."""

    def __getattr__(self, name: str) -> Any:
        return self.get(name, "")


class DatabaseBackedCrawler:
    """Read-only crawler facade for --analyze-only without importing crawl engines."""

    def __init__(self, db: CrawlDatabase):
        self.db = db
        self.sitemap_parser = None
        # كاش للـ getters: القاعدة ثابتة في وضع analyze-only، فنبنيها مرة واحدة
        # ونعيد نسخة سطحية لكل مرحلة بدل إعادة SELECT * في كل استدعاء.
        self._getter_cache: dict[str, list[Any]] = {}
        # روابط sitemap المحفوظة من جلسة الزحف (لـ sitemap_diff في analyze-only)
        try:
            self.sitemap_urls_seen = db.get_meta("sitemap_urls", []) or []
        except Exception:
            self.sitemap_urls_seen = []

    def _memo_db(self, key: str, builder) -> list[Any]:
        cached = self._getter_cache.get(key)
        if cached is None:
            cached = builder()
            self._getter_cache[key] = cached
        return list(cached)

    def get_pages(self) -> list[dict[str, Any]]:
        return self._memo_db("pages", lambda: [AttrDict(row) for row in self.db.get_all_pages()])

    def get_links(self) -> list[dict[str, Any]]:
        return self._memo_db("links", lambda: list(self.db.get_all_links()))

    def get_images(self) -> list[dict[str, Any]]:
        return self._memo_db("images", lambda: list(self.db.get_all_images()))

    def get_headings(self) -> list[dict[str, Any]]:
        return self._memo_db("headings", lambda: list(self.db.get_all_headings()))

    def get_schema(self) -> list[dict[str, Any]]:
        return self._memo_db("schema", lambda: list(self.db.get_all_schema()))

    def get_headers(self) -> list[dict[str, Any]]:
        return self._memo_db("headers", lambda: list(self.db.get_all_headers()))

    def get_redirects(self) -> list[dict[str, Any]]:
        return self._memo_db("redirects", lambda: list(self.db.get_all_redirects()))

    def get_stats(self) -> SimpleNamespace:
        pages = self.get_pages()
        return SimpleNamespace(
            pages_crawled=len(pages),
            pages_failed=sum(1 for page in pages if page.get("crawl_error")),
            pages_skipped=0,
            status_codes={},
            duration_seconds=0,
            pages_per_second=0,
        )
