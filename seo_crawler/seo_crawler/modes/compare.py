"""
modes/compare.py
=================
وضع المقارنة (Compare Mode) - يقارن موقعك مع المنافسين.

الهدف: جدول مقارنة شامل بين عدة مواقع (موقعك + 1-N منافس).

الإعدادات:
- زحف خفيف لكل موقع (100 صفحة افتراضياً)
- استخراج البنية فقط
- مخرجات: جدول مقارنة + Excel متعدد الـ tabs

الاستخدام في config.yaml:
    sites_to_compare:
      - url: "https://yoursite.com/"
        label: "Us"
        is_primary: true
      - url: "https://competitor1.com/"
        label: "Competitor 1"
      - url: "https://competitor2.com/"
        label: "Competitor 2"
"""

from typing import Any

from modes.base import CrawlMode


class CompareMode(CrawlMode):
    """وضع مقارنة عدة مواقع."""

    name = "compare"
    description = "Compare your site against competitors (multiple sites)"

    def apply_defaults(self, config: dict[str, Any]) -> dict[str, Any]:
        cfg = dict(config)

        # زحف خفيف جداً (نريد بيانات من كل موقع، ليس تدقيق كامل)
        crawl = dict(cfg.get("crawl", {}))
        crawl["max_pages"] = min(crawl.get("max_pages", 100), 100)
        crawl["delay_seconds"] = max(crawl.get("delay_seconds", 1.5), 1.5)
        crawl["concurrent_requests"] = min(crawl.get("concurrent_requests", 3), 3)
        crawl["respect_robots"] = True
        crawl["robots_failure_policy"] = "deny"
        cfg["crawl"] = crawl

        # نريد البنية فقط
        extraction = dict(cfg.get("extraction", {}))
        extraction.update({
            "extract_meta": True,
            "extract_headings": True,
            "extract_links": True,
            "extract_images": True,
            "extract_schema": True,
            "extract_hreflang": True,
            "extract_og": True,
            "extract_canonical": True,
            "extract_headers": False,
            "extract_content": True,
            "extract_mixed_content": False,
        })
        cfg["extraction"] = extraction

        # لا فحوصات خارجية في وضع compare
        external = dict(cfg.get("external_check", {}))
        external["enabled"] = False
        cfg["external_check"] = external

        # تكاملات: فقط للموقع الأساسي (is_primary=true)
        # يُتعامل معها في run_compare()

        return cfg

    def get_extractors(self) -> list[str]:
        return [
            "meta", "headings", "links", "images", "schema",
            "hreflang", "og", "canonical", "content",
        ]

    def get_analyzers(self) -> list[str]:
        return ["url_issues", "canonicals", "schema_validator", "hreflang_validator"]

    def get_excel_sheets(self) -> list[str]:
        return [
            "Comparison Overview",  # ⭐ جدول المقارنة الرئيسي
            "Sites Summary",
            "Content Comparison",
            "Schema Comparison",
            "Linking Comparison",
        ]

    def should_check_external_links(self) -> bool:
        return False

    def should_run_integrations(self) -> bool:
        # فقط للموقع الأساسي
        return True
