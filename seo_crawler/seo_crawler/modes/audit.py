"""
modes/audit.py
===============
وضع التدقيق الكامل (Audit Mode) - الافتراضي.

الهدف: تحليل موقعك لاكتشاف كل المشاكل وإصلاحها.

الإعدادات:
- زحف كامل (5000+ صفحة)
- كل الـ extractors
- كل الـ analyzers (29+ مشكلة)
- فحص الروابط الخارجية
- تكاملات GSC + PageSpeed
"""

from typing import Any

from modes.base import CrawlMode


class AuditMode(CrawlMode):
    """وضع التدقيق الكامل لموقعك."""

    name = "audit"
    description = "Full SEO audit for your own site (default)"

    def apply_defaults(self, config: dict[str, Any]) -> dict[str, Any]:
        """تطبيق إعدادات مُحسَّنة للـ audit."""
        # نُعدّل نسخة، لا الأصل
        cfg = dict(config)

        # الإعدادات الافتراضية للزحف
        crawl = dict(cfg.get("crawl", {}))
        crawl.setdefault("max_pages", 5000)
        crawl.setdefault("delay_seconds", 0.5)
        crawl.setdefault("concurrent_requests", 5)
        cfg["crawl"] = crawl

        # كل الـ extractors مفعّلة
        extraction = dict(cfg.get("extraction", {}))
        for key in [
            "extract_meta", "extract_headings", "extract_links",
            "extract_images", "extract_schema", "extract_hreflang",
            "extract_og", "extract_canonical", "extract_headers",
            "extract_content",
        ]:
            extraction.setdefault(key, True)
        cfg["extraction"] = extraction

        # فحص الروابط الخارجية مفعّل
        external = dict(cfg.get("external_check", {}))
        external.setdefault("enabled", True)
        cfg["external_check"] = external

        return cfg

    def get_extractors(self) -> list[str]:
        return [
            "meta", "headings", "links", "images", "schema",
            "hreflang", "og", "canonical", "headers", "content",
            "mixed_content",
        ]

    def get_analyzers(self) -> list[str]:
        return [
            "duplicates", "orphans", "redirects", "thin_content",
            "broken_links", "images", "url_issues", "canonicals", "seo_issues",
            "schema_validator", "sitemap_diff", "hreflang_validator",
        ]

    def get_excel_sheets(self) -> list[str]:
        return [
            "Overview", "Critical Issues", "High Priority",
            "Medium Priority", "Low Priority",
            "Pages", "All Links", "Images", "Schema",
            "Redirects", "404 Pages",
            "Duplicate Titles", "Orphan Pages", "Thin Content",
        ]

    def should_check_external_links(self) -> bool:
        return True

    def should_run_integrations(self) -> bool:
        return True
