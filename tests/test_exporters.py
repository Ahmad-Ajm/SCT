"""
tests/test_exporters.py — csv_exporter / html_exporter / report_builder / sitemap_generator.
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

from exporters.csv_exporter import CSVExporter
from exporters.html_exporter import HTMLReportExporter


class TestExporters(unittest.TestCase):
    def test_csv_exporter_serializes_nested_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            exporter = CSVExporter(tmp)
            path = exporter._export("nested.csv", [{"url": "x", "tags": ["a", "b"]}])
            with open(path, newline="", encoding="utf-8-sig") as f:
                row = next(csv.DictReader(f))
            self.assertEqual(row["url"], "x")
            self.assertEqual(row["tags"], '["a", "b"]')
    def test_unified_join_and_opportunities(self):
        from reporting.report_join import build_unified
        from reporting.opportunities import compute_opportunities
        pages = [
            {"url": "https://x.com/a", "status_code": 200, "is_indexable": True,
             "title": "", "meta_description_length": 0, "h1_count": 0,
             "word_count": 500, "internal_links_count": 3},
            {"url": "https://x.com/ok", "status_code": 200, "is_indexable": True,
             "title": "T", "meta_description_length": 120, "h1_count": 1, "word_count": 800},
        ]
        gsc = [{"page": "https://x.com/a", "clicks": 50, "impressions": 2000,
                "ctr": 2.5, "position": 8.1}]
        ga4 = [{"path": "/a", "sessions": 120, "users": 100, "engagement_rate": 45.0}]
        rows = build_unified(pages, {}, gsc, ga4)
        a = next(r for r in rows if r["url"].endswith("/a"))
        self.assertIn("missing_title", a["technical_issues"])
        self.assertEqual(a["clicks"], 50)
        self.assertEqual(a["sessions"], 120)   # GA4 path join worked
        opp = compute_opportunities(rows)
        # page with issues+traffic is included; clean page excluded
        urls = [o["url"] for o in opp["opportunities"]]
        self.assertIn("https://x.com/a", urls)
        self.assertNotIn("https://x.com/ok", urls)
        self.assertEqual(opp["summary"]["with_traffic_and_issues"], 1)
    def test_html_report_generates_rtl(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = {
                "site_config": {"start_url": "https://x.com/"},
                "pages": [{"url": "https://x.com/", "status_code": 200, "is_indexable": True}],
                "seo_issues": {"summary": {"total_issues": 0, "critical_count": 0,
                               "high_count": 0, "medium_count": 0, "low_count": 0},
                               "by_severity": {}},
            }
            path = HTMLReportExporter(tmp).export(audit, {"language": "ar", "client_name": "X"})
            content = Path(path).read_text(encoding="utf-8")
            self.assertIn('dir="rtl"', content)
            self.assertIn("X", content)
    def test_report_audience_client_vs_expert(self):
        audit = {
            "site_config": {"start_url": "https://x.com/"},
            "pages": [{"url": "https://x.com/", "status_code": 200, "is_indexable": True}],
            "seo_issues": {"summary": {"total_issues": 2, "critical_count": 1, "high_count": 1,
                                       "medium_count": 0, "low_count": 0},
                           "by_severity": {"🔴 Critical": [
                               {"issue_type": "Missing title", "description": "no title",
                                "affected_count": 1, "recommendation": "add title",
                                "affected_urls_sample": ["https://x.com/"]}]}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            client = Path(HTMLReportExporter(tmp, "c.html").export(
                audit, {"language": "en", "audience": "client"})).read_text(encoding="utf-8")
            expert = Path(HTMLReportExporter(tmp, "e.html").export(
                audit, {"language": "en", "audience": "expert"})).read_text(encoding="utf-8")
        # تقرير العميل يحوي قسم التقييم العام (health) وشارة نوع التقرير
        self.assertIn('class="health"', client)
        self.assertIn("Client summary report", client)
        # تقرير الخبير لا يحوي قسم الصحّة (تفصيلي بلا تبسيط)
        self.assertNotIn('class="health"', expert)
    def test_report_audience_both_builds_two_files(self):
        from exporters.report_builder import build_report
        audit = {"site_config": {"start_url": "https://x.com/"},
                 "pages": [{"url": "https://x.com/", "status_code": 200, "is_indexable": True}],
                 "seo_issues": {"summary": {}, "by_severity": {}}}
        with tempfile.TemporaryDirectory() as tmp:
            res = build_report(audit, tmp, {"audience": "both", "language": "ar"},
                               make_pdf=False, name_stem="report_x")
            self.assertTrue(res.get("html_client") and Path(res["html_client"]).exists())
            self.assertTrue(res.get("html_expert") and Path(res["html_expert"]).exists())
            self.assertTrue(res["html_client"].endswith("_client.html"))
            self.assertTrue(res["html_expert"].endswith("_expert.html"))
    def test_images_csv_exports_all_not_capped_at_100(self):
        # ملف images_no_alt.csv يجب أن يحوي كل الصور بلا alt (لا عيّنة 100 فقط)
        from exporters.csv_exporter import CSVExporter
        images = [{"page_url": f"https://x.com/p{i}", "src": f"img{i}.png",
                   "has_alt": False, "has_explicit_dimensions": False,
                   "file_extension": "png", "alt": ""} for i in range(150)]
        with tempfile.TemporaryDirectory() as tmp:
            files = CSVExporter(tmp).export_all(
                pages=[], links=[], images=images, headings=[], schema=[],
                redirects=[], headers=[], seo_issues={}, duplicate_data={},
                orphan_data={}, thin_content_data={}, broken_data={},
                images_analysis={"no_alt": images[:100], "no_dimensions": images[:100]},
            )
            with open(files["images_no_alt"], encoding="utf-8-sig", newline="") as f:
                n_alt = sum(1 for _ in csv.reader(f)) - 1
            with open(files["images_no_dimensions"], encoding="utf-8-sig", newline="") as f:
                n_dim = sum(1 for _ in csv.reader(f)) - 1
        self.assertEqual(n_alt, 150)
        self.assertEqual(n_dim, 150)
    def test_sitemap_generator_includes_only_eligible(self):
        # IMP-5: مولّد sitemap يُدرِج فقط الصفحات 200 + indexable + canonical ذاتي
        from exporters.sitemap_generator import SitemapGenerator
        pages = [
            {"url": "https://x.com/a", "status_code": 200, "is_indexable": True,
             "canonical": "https://x.com/a", "last_modified": "2026-05-01T10:00:00"},
            {"url": "https://x.com/b", "status_code": 200, "is_indexable": True, "canonical": ""},
            {"url": "https://x.com/404", "status_code": 404, "is_indexable": True},
            {"url": "https://x.com/noindex", "status_code": 200, "is_indexable": False},
            {"url": "https://x.com/canon", "status_code": 200, "is_indexable": True,
             "canonical": "https://x.com/a"},  # canonical لغيرها ⇒ يُستبعَد
        ]
        with tempfile.TemporaryDirectory() as tmp:
            res = SitemapGenerator(tmp, base_url="https://x.com/").generate(pages)
            self.assertEqual(res["url_count"], 2)
            content = Path(res["files"][0]).read_text(encoding="utf-8")
            self.assertIn("<loc>https://x.com/a</loc>", content)
            self.assertIn("<loc>https://x.com/b</loc>", content)
            self.assertNotIn("/404", content)
            self.assertNotIn("/noindex", content)
            self.assertNotIn("/canon", content)
            self.assertIn("<lastmod>2026-05-01</lastmod>", content)
            self.assertIn('xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"', content)
    def test_html_report_renders_action_board(self):
        # تقرير الخبير يعرض لوحة العمل عند توفّر بيانات الأولوية
        audit = {
            "site_config": {"start_url": "https://x.com/"},
            "pages": [{"url": "https://x.com/", "status_code": 200, "is_indexable": True}],
            "seo_issues": {"summary": {"total_issues": 0, "critical_count": 0, "high_count": 0,
                           "medium_count": 0, "low_count": 0}, "by_severity": {}},
            "priority": {"pages": [
                {"url": "https://x.com/p", "page_type": "product", "priority_score": 12.3,
                 "owner": "content", "action_group": "do_now", "ease": "easy",
                 "top_fix": "Add a unique title", "technical_issues": "missing_title"}],
                "summary": {"by_action_group": {"do_now": 1}}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = HTMLReportExporter(tmp, "ab.html").export(
                audit, {"language": "en", "audience": "expert"})
            content = Path(path).read_text(encoding="utf-8")
        self.assertIn("Action Board", content)
        self.assertIn("Do now", content)
        self.assertIn("https://x.com/p", content)

