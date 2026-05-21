"""
modes/competitor.py
====================
وضع تحليل المنافس (Competitor Mode).

الهدف: فهم استراتيجية المنافس بدون إرهاق سيرفره.

التركيز على:
- بنية المحتوى (Titles, Headings, Word counts)
- Schema.org المستخدم (Rich Results)
- Internal linking structure
- Hreflang strategy
- استهداف الكلمات في Titles/Meta

التحفظات:
- delay أكبر (2s+ افتراضياً)
- max_pages محدود (300)
- لا فحص للمشاكل (ليست مشكلتنا)
- لا فحص للروابط الخارجية
- لا تكاملات (GSC/PageSpeed لا تعمل لمواقع لا نملكها)
"""

from typing import Any

from modes.base import CrawlMode


class CompetitorMode(CrawlMode):
    """وضع تحليل المنافس - زحف خفيف ومحترم."""

    name = "competitor"
    description = "Light analysis of a competitor site (no audit)"

    def apply_defaults(self, config: dict[str, Any]) -> dict[str, Any]:
        """إعدادات محترمة للمنافس - لا نُرهق سيرفره."""
        cfg = dict(config)

        # زحف خفيف ومحترم
        crawl = dict(cfg.get("crawl", {}))
        crawl["max_pages"] = min(crawl.get("max_pages", 300), 300)  # حد أقصى 300
        crawl["delay_seconds"] = max(crawl.get("delay_seconds", 2.0), 2.0)  # ≥2s
        crawl["concurrent_requests"] = min(crawl.get("concurrent_requests", 2), 2)
        crawl["respect_robots"] = True  # إلزامي
        crawl["robots_failure_policy"] = "deny"
        cfg["crawl"] = crawl

        # نستخرج فقط ما يهمنا للتحليل التنافسي
        extraction = dict(cfg.get("extraction", {}))
        extraction.update({
            "extract_meta": True,
            "extract_headings": True,
            "extract_links": True,
            "extract_images": True,  # نريد معرفة كم صورة وأي صيغ
            "extract_schema": True,  # ⭐ مهم - ما الـ Schema الذي يستخدمه
            "extract_hreflang": True,  # ⭐ هل يستهدف لغات أخرى
            "extract_og": True,
            "extract_canonical": True,
            "extract_headers": False,  # لا نحتاج
            "extract_content": True,  # word count + language
            "extract_mixed_content": False,
        })
        cfg["extraction"] = extraction

        # لا فحص للروابط الخارجية (ليست مشكلتنا)
        external = dict(cfg.get("external_check", {}))
        external["enabled"] = False
        cfg["external_check"] = external

        # لا تكاملات
        integrations = dict(cfg.get("integrations", {}))
        for integration in ("gsc", "pagespeed", "awt"):
            if integration in integrations:
                integrations[integration] = {**integrations[integration], "enabled": False}
        cfg["integrations"] = integrations

        return cfg

    def get_extractors(self) -> list[str]:
        return [
            "meta", "headings", "links", "images", "schema",
            "hreflang", "og", "canonical", "content",
        ]

    def get_analyzers(self) -> list[str]:
        # نُحلّل فقط البنية - لا "مشاكل"
        return [
            "url_issues",
            "canonicals",
            "schema_validator",  # ما Schema المستخدم
            "hreflang_validator",  # هل لديهم استراتيجية متعددة اللغات
            # لا duplicates، broken_links، seo_issues - ليست مشكلتنا
        ]

    def get_excel_sheets(self) -> list[str]:
        return [
            "Overview",  # ملخص الموقع
            "Content Strategy",  # Title patterns, Word counts, Language
            "Schema Usage",  # كل أنواع Schema
            "Internal Linking",  # بنية الروابط
            "Hreflang Strategy",  # متعدد اللغات؟
            "Pages",
            "All Links",
            "Images",
            "Schema",
        ]

    def should_check_external_links(self) -> bool:
        return False  # ليست مشكلتنا

    def should_run_integrations(self) -> bool:
        return False  # لا تعمل لمواقع لا نملكها
