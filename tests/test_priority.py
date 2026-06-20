"""
tests/test_priority.py — reporting/priority_engine + reporting/url_detail.
نُقلت من test_core_behaviors.py في v1.13 REFACTOR-tests-split.
"""

import csv
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

# v1.13 REFACTOR-tests-split: shared fixtures
from tests.conftest import FakeResponse, MinimalPage, _FakeAIResp  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "seo_crawler" / "seo_crawler"


class TestPriority(unittest.TestCase):
    def test_url_detail_joins_all_sources(self):
        # درج URL: يدمج الزحف + GSC + GA4 + PageSpeed + الأولوية + الوصولية لرابط واحد
        from reporting.url_detail import build_url_detail
        audit = {
            "pages": [
                {"url": "https://x.com/p", "status_code": 200, "title": "P", "h1_count": 1,
                 "word_count": 500, "is_indexable": True},
                {"url": "https://x.com/other", "status_code": 200},
            ],
            "integrations": {
                "gsc_pages": [
                    {"page": "https://x.com/p", "clicks": 12, "impressions": 800,
                     "ctr": 0.015, "position": 7.2}],
                "ga4_landing_pages": [{"path": "/p", "sessions": 60, "users": 50,
                                       "engagement_rate": 55.0}],
                "pagespeed": [
                    {"url": "https://x.com/p", "strategy": "mobile", "performance_score": 55,
                     "lcp_lab_ms": 4500},
                    {"url": "https://x.com/p", "strategy": "desktop", "performance_score": 80,
                     "lcp_lab_ms": 2100},
                    {"url": "https://x.com/other", "strategy": "mobile"}],
                "gsc_index_status": [
                    {"url": "https://x.com/p", "verdict": "PASS",
                     "coverage_state": "Submitted and indexed"}],
            },
            "priority": {"pages": [
                {"url": "https://x.com/p", "page_type": "product", "priority_score": 12.3,
                 "priority_band": "high", "action_group": "do_now", "owner": "content",
                 "ease": "easy", "tech_issue_count": 1, "technical_issues": "missing_meta",
                 "top_fix": "أضف وصفاً"}]},
            "accessibility": [
                {"url": "https://x.com/p", "violations_count": 2, "nodes_total": 5,
                 "by_impact": {"serious": 2}}],
        }
        d = build_url_detail(audit, "https://x.com/p")
        self.assertTrue(d["found"])
        self.assertEqual(d["page"]["status_code"], 200)
        self.assertEqual(d["gsc"]["clicks"], 12)
        self.assertEqual(d["ga4"]["sessions"], 60)
        self.assertEqual(len(d["pagespeed"]), 2)  # mobile + desktop
        self.assertEqual({r["strategy"] for r in d["pagespeed"]}, {"mobile", "desktop"})
        self.assertEqual(d["priority"]["action_group"], "do_now")
        self.assertEqual(d["accessibility"]["violations_count"], 2)
        self.assertEqual(d["index_status"]["verdict"], "PASS")
        # رابط غير معروف ⇒ found=False بدون أعطال
        d2 = build_url_detail(audit, "https://x.com/unknown")
        self.assertFalse(d2["found"])
        # رابط فارغ ⇒ خطأ واضح
        d3 = build_url_detail(audit, "")
        self.assertEqual(d3.get("error"), "missing_url")
    def test_priority_engine_page_type_and_ease(self):
        from reporting.priority_engine import (
            classify_page_type, page_importance, ease_of_fix)
        self.assertEqual(classify_page_type("https://x.com/"), "home")
        self.assertEqual(classify_page_type("https://x.com/products/123-book"), "product")
        self.assertEqual(classify_page_type("https://x.com/categories/fiqh"), "category")
        self.assertEqual(classify_page_type("https://x.com/products"), "category")  # listing
        self.assertEqual(classify_page_type("https://x.com/blog/post-1"), "blog")
        self.assertEqual(classify_page_type("https://x.com/about"), "static")
        # schema يتغلّب على المسار
        self.assertEqual(classify_page_type("https://x.com/anything", ["Product"]), "product")
        # أهمية: الرئيسية أعلى من صفحة ثابتة عميقة
        self.assertGreater(page_importance("home", 0, 50), page_importance("static", 5, 0))
        # سهولة الإصلاح: أصعب مشكلة تحكم؛ والمنصّة تُحوّل ملكية الترقيم لدعم المنصّة
        self.assertEqual(ease_of_fix(["missing_title"]), ("easy", "content"))
        self.assertEqual(ease_of_fix(["missing_title", "broken"]), ("hard", "developer"))
        self.assertEqual(ease_of_fix(["404_with_inlinks"], platform="zid"),
                         ("hard", "platform_support"))
    def test_priority_engine_scores_and_action_board(self):
        from reporting.priority_engine import compute_priority, build_action_board
        rows = [
            # صفحة منتج مركزية بظهور عالٍ + عنوان ناقص (مكسب سريع) ⇒ do_now
            {"url": "https://x.com/products/big", "technical_issues": ["missing_title"],
             "depth": 1, "internal_links_count": 40, "clicks": 80, "impressions": 9000,
             "sessions": 300},
            # صفحة 404 لها روابط داخلية على زد ⇒ needs_platform
            {"url": "https://x.com/c/x?page=0", "technical_issues": ["404_with_inlinks"],
             "depth": 2, "internal_links_count": 5, "clicks": 0, "impressions": 50,
             "sessions": 0},
            # صفحة بلا مشاكل ⇒ تُستبعَد
            {"url": "https://x.com/clean", "technical_issues": [], "impressions": 1000},
        ]
        r = compute_priority(rows, platform="zid")
        self.assertEqual(r["count"], 2)  # الصفحة النظيفة مُستبعَدة
        top = r["pages"][0]
        self.assertEqual(top["url"], "https://x.com/products/big")
        self.assertEqual(top["page_type"], "product")
        self.assertEqual(top["priority_band"], "high")
        self.assertEqual(top["action_group"], "do_now")
        groups = {p["url"]: p["action_group"] for p in r["pages"]}
        self.assertEqual(groups["https://x.com/c/x?page=0"], "needs_platform")
        # لوحة العمل مرتّبة: do_now قبل needs_platform
        board = build_action_board(r)
        first_groups = [b["action_group"] for b in board]
        self.assertEqual(first_groups[0], "do_now")
        # تفكيك العوامل موجود للشفافية
        self.assertIn("factor_severity", top)
        self.assertGreater(top["priority_score"], 0)

