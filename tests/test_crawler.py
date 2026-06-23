"""
tests/test_crawler.py — robots / db / async_core / classifier / extractors.
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

from crawler.robots_parser import RobotsParser
from storage.database import CrawlDatabase


class TestCrawler(unittest.TestCase):
    def test_robots_failure_policy_can_deny_when_unloaded(self):
        robots = RobotsParser("https://example.com/", "TestBot", failure_policy="deny")
        self.assertFalse(robots.can_fetch("https://example.com/anything"))
    def test_robots_parser_reads_rules_and_sitemaps(self):
        with patch("requests.get", return_value=FakeResponse()):
            robots = RobotsParser("https://example.com/", "TestBot")
            self.assertTrue(robots.load())
            self.assertFalse(robots.can_fetch("https://example.com/blocked/page"))
            self.assertEqual(robots.get_sitemaps(), ["https://example.com/sitemap.xml"])
    def test_database_saves_page_bundle_in_one_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = CrawlDatabase(str(Path(tmp) / "crawl.db"))
            db.save_page_bundle(
                MinimalPage("https://example.com/"),
                links=[{"from_url": "https://example.com/", "to_url": "https://example.com/a", "is_internal": True}],
                images=[{"page_url": "https://example.com/", "src": "https://example.com/a.png"}],
                headings=[{"page_url": "https://example.com/", "tag": "h1", "level": 1, "text": "Hello", "length": 5, "position": 1}],
                schema_entries=[{"page_url": "https://example.com/", "format": "json-ld", "type": "Organization", "name": "Example"}],
            )
            self.assertEqual(db.get_pages_count(), 1)
            self.assertEqual(len(list(db.get_all_links())), 1)
            self.assertEqual(len(list(db.get_all_images())), 1)
            db.close()
    def test_local_fixture_server_serves_stable_seo_cases(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                routes = {
                    "/robots.txt": "User-agent: *\nDisallow: /private\nSitemap: /sitemap.xml\n",
                    "/sitemap.xml": "<?xml version='1.0'?><urlset><url><loc>/</loc></url></urlset>",
                    "/": "<html><head><title>Home</title><link rel='canonical' href='/'></head><body><a href='/missing'>Missing</a></body></html>",
                }
                if self.path == "/missing":
                    self.send_response(404)
                    self.end_headers()
                    return
                body = routes.get(self.path, "")
                self.send_response(200 if body else 500)
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))

            def log_message(self, *_args):
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host = f"http://127.0.0.1:{server.server_port}"
            robots = RobotsParser(host, "TestBot")
            self.assertTrue(robots.load())
            self.assertFalse(robots.can_fetch(f"{host}/private/page"))
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
    def test_c3_no_duplicate_child_rows_on_recrawl(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = CrawlDatabase(str(Path(tmp) / "c.db"))
            page = MinimalPage("https://x.com/a")
            links = [{"from_url": "https://x.com/a", "to_url": "https://x.com/b", "is_internal": True}]
            reds = [{"from_url": "https://x.com/a", "to_url": "https://x.com/c",
                     "status_code": 301, "chain_length": 1, "original_url": "https://x.com/a"}]
            db.save_page_bundle(page, links=links, redirects=reds)
            db.save_page_bundle(page, links=links, redirects=reds)  # re-crawl
            self.assertEqual(len(list(db.get_all_links())), 1)
            self.assertEqual(len(list(db.get_all_redirects())), 1)
            self.assertEqual(db.get_pages_count(), 1)
            db.close()
    def test_c2_resume_db_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = CrawlDatabase(str(Path(tmp) / "c.db"))
            db.replace_queue([("https://x.com/b", 1), ("https://x.com/c", 2)])
            db.mark_visited_many(["https://x.com/a"])
            self.assertEqual(sorted(db.get_queue_all()),
                             [("https://x.com/b", 1), ("https://x.com/c", 2)])
            self.assertEqual(db.get_visited_all(), {"https://x.com/a"})
            db.replace_queue([("https://x.com/e", 3)])
            self.assertEqual(db.get_queue_all(), [("https://x.com/e", 3)])
            db.close()
    def test_db_persists_new_security_header_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = CrawlDatabase(str(Path(tmp) / "c.db"))
            db.save_page_bundle(
                MinimalPage("https://x.com/"),
                header_data={"page_url": "https://x.com/", "referrer_policy": "no-referrer",
                             "x_content_type_options": "nosniff",
                             "permissions_policy": "geolocation=()"},
            )
            rows = list(db.get_all_headers())
            self.assertEqual(rows[0]["referrer_policy"], "no-referrer")
            self.assertEqual(rows[0]["x_content_type_options"], "nosniff")
            self.assertEqual(rows[0]["permissions_policy"], "geolocation=()")
            db.close()
    def test_custom_extractor_css_and_regex(self):
        from extractors.custom_extractor import compile_rules, extract_custom
        rules = compile_rules([
            {"name": "sku", "type": "regex", "pattern": r"SKU:\s*([A-Z0-9-]+)", "group": 1},
        ])
        out = extract_custom(None, "<p>SKU: ABC-123</p>", rules)
        self.assertEqual(out["sku"], "ABC-123")
    def test_db_backed_getters_memoized(self):
        # القاعدة ثابتة بعد الزحف: get_pages يُبنى مرة واحدة ويُكاش، مع إعادة
        # نسخة سطحية لكل مستدعٍ كي لا يفسد تعديل أحدهم الكاش.
        from main import DatabaseBackedCrawler

        class FakeDB:
            def __init__(self):
                self.page_calls = 0

            def get_meta(self, *a, **k):
                return []

            def get_all_pages(self):
                self.page_calls += 1
                return iter([{"url": "https://x.com/", "status_code": 200}])

            def get_all_links(self):
                return []

            def get_all_images(self):
                return []

            def get_all_headings(self):
                return []

            def get_all_schema(self):
                return []

            def get_all_headers(self):
                return []

            def get_all_redirects(self):
                return []

        db = FakeDB()
        crawler = DatabaseBackedCrawler(db)
        p1 = crawler.get_pages()
        p2 = crawler.get_pages()
        self.assertEqual(db.page_calls, 1)        # بُنيت مرة واحدة فقط
        self.assertEqual(len(p1), 1)
        self.assertIsNot(p1, p2)                   # نسخة جديدة لكل استدعاء
        p1.append("corruption")
        self.assertEqual(len(crawler.get_pages()), 1)  # الكاش لم يتأثّر
    def test_db_persists_pagination_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = CrawlDatabase(str(Path(tmp) / "c.db"))
            db.save_page_bundle({
                "url": "https://x.com/p1", "status_code": 200,
                "is_paginated": True, "pagination_next": "https://x.com/p2",
                "pagination_prev": "",
            })
            row = next(iter(db.get_all_pages()))
            self.assertEqual(row["pagination_next"], "https://x.com/p2")
            self.assertEqual(row["is_paginated"], 1)
            db.close()
    def test_content_extractor_skips_simhash_for_short_text(self):
        # نصّ قصير جداً (<10 كلمات) بصمته غير مستقرّة ⇒ نتركها فارغة
        from bs4 import BeautifulSoup
        from extractors.content_extractor import extract_content
        short = extract_content(BeautifulSoup("<p>only three words</p>", "lxml"))
        self.assertEqual(short["content_simhash"], "")
        long_html = "<p>" + " ".join(f"word{i}" for i in range(40)) + "</p>"
        long_doc = extract_content(BeautifulSoup(long_html, "lxml"))
        self.assertTrue(long_doc["content_simhash"])
    def test_robots_parser_caps_oversized_response(self):
        # سقف الحجم يمنع استنزاف الذاكرة من robots.txt ضخم
        class HugeResponse:
            status_code = 200
            encoding = "utf-8"

            def iter_content(self, chunk_size=8192):
                # ~3MB يتجاوز سقف 2MB
                for _ in range(400):
                    yield b"x" * 8192

            def close(self):
                return None

        with patch("requests.get", return_value=HugeResponse()):
            robots = RobotsParser("https://example.com/", "TestBot")
            self.assertFalse(robots.load())  # يفشل بأمان بدل تحميل الكل
    def test_adaptive_throttle_backs_off_and_recovers(self):
        # IMP-10: التأخير يرتفع عند 429/5xx ويتعافى عند النجاح
        from crawler.adaptive_throttle import AdaptiveThrottle
        t = AdaptiveThrottle(enabled=True, min_delay=0.0, max_delay=5.0,
                             step_up=0.5, step_down=0.25)
        self.assertEqual(t.delay(), 0.0)
        t.record(503)
        self.assertEqual(t.delay(), 1.0)  # 5xx ⇒ خطوتان
        t.record(200)
        self.assertEqual(t.delay(), 0.75)  # تعافٍ تدريجي
        # معطّل ⇒ دائماً صفر
        off = AdaptiveThrottle(enabled=False)
        off.record(500)
        self.assertEqual(off.delay(), 0.0)
    def test_platform_preset_detect_and_apply(self):
        # IMP-11: كشف منصّة التجارة وتطبيق أنماط الاستبعاد
        from config_presets import detect_platform, apply_preset
        self.assertEqual(detect_platform('<script src="https://cdn.shopify.com/x.js">'), "shopify")
        self.assertEqual(detect_platform("", {"X-Shopid": "123"}), "shopify")
        self.assertEqual(detect_platform("just a normal page"), "unknown")
        cfg = {"filters": {"exclude_patterns": ["*/keepme*"]}}
        apply_preset(cfg, "salla")
        ex = cfg["filters"]["exclude_patterns"]
        self.assertIn("*/keepme*", ex)       # لم يُمسح ما وضعه المستخدم
        self.assertIn("*/checkout*", ex)      # أُضيف من القالب
        self.assertEqual(cfg["site"]["platform_preset_applied"], "Salla")

    def test_wordpress_preset_present_and_excludes_traps(self):
        """v1.13.5: WordPress preset يستبعد الفخاخ الكلاسيكيّة (replytocom/feed/tag/author)."""
        from config_presets import PRESETS, apply_preset, detect_platform
        # 1. الـpreset موجود مع الأنماط المتوقَّعة
        self.assertIn("wordpress", PRESETS)
        wp = PRESETS["wordpress"]
        for required in (
            "*?replytocom=*", "*/feed/*", "*/wp-admin*", "*/wp-json/*",
            "*/tag/*", "*/author/*", "*/xmlrpc.php*",
        ):
            self.assertIn(required, wp["exclude_patterns"], f"missing pattern: {required}")
        for q in ("replytocom", "attachment_id", "preview"):
            self.assertIn(q, wp["strip_query_params"])
        # 2. apply_preset يدمج الأنماط دون مسح ما وضعه المستخدم
        cfg = {"filters": {"exclude_patterns": ["*/keep-me*"]}}
        apply_preset(cfg, "wordpress")
        ex = cfg["filters"]["exclude_patterns"]
        self.assertIn("*/keep-me*", ex)
        self.assertIn("*?replytocom=*", ex)
        self.assertEqual(cfg["site"]["platform_preset_applied"], "WordPress")
        # 3. detect_platform يتعرّف على fingerprint WordPress (بدون Woo)
        wp_html = '<link rel="stylesheet" href="https://example.com/wp-content/themes/x/style.css">'
        self.assertEqual(detect_platform(wp_html), "wordpress")
        # 4. WooCommerce لا يزال يفوز عند تعدّد التطابق (موقع متجر على WP)
        wc_html = wp_html + '<script src="/wp-content/plugins/woocommerce/x.js"></script>'
        self.assertEqual(detect_platform(wc_html), "woocommerce")
    def test_discover_new_links_smoke_smoke(self):
        import asyncio
        from bs4 import BeautifulSoup
        from crawler.async_core import AsyncCrawler
        # نُهيّئ crawler خفيفاً بأقلّ إعداد (بلا DB، بلا robots خارجي)
        config = {
            "site": {"start_url": "https://example.com/", "domain": "example.com"},
            "crawl": {
                "max_pages": 0, "max_depth": 5, "delay_seconds": 0.1,
                "concurrent_requests": 1, "respect_robots": False,
                "user_agent": "SCT-test/1.0", "timeout_seconds": 30,
                "max_retries": 1, "verify_ssl": True,
                "deferred_crawl": {"enabled": True, "pagination_max": 3},
            },
            "extraction": {}, "filters": {}, "external_check": {"enabled": False},
            "state": {"use_db": False},
        }
        crawler = AsyncCrawler(config, db=None)
        soup = BeautifulSoup(
            '<html><body>'
            '<a href="/products/abc">A</a>'
            '<a href="/categories/x?page=2">P2 (primary)</a>'
            '<a href="/categories/x?page=9">P9 (deferred)</a>'
            '<a href="/auth/login?redirect_to=/x">Auth (deferred)</a>'
            '</body></html>',
            "html.parser",
        )
        # PageData بسيطة بحدّها الأدنى — يحتاجها _discover_new_links فقط لـpage.url
        page = type("P", (), {"url": "https://example.com/", "final_url": None})()

        async def run():
            await crawler._discover_new_links(page, soup, depth=0)
        # يجب ألّا يرمي NameError أو أيّ شيء غير متوقّع. asyncio.run() يُنشئ loop
        # جديدة كي لا نتأثّر بـloop خلّفته اختبارات أخرى في نفس thread.
        asyncio.run(run())
        # بعد التشغيل: نتوقّع روابط في الطابور وأخرى مؤجَّلة
        self.assertGreater(crawler.queue.qsize(), 0, "primary URLs should be queued")
        self.assertGreater(len(crawler.deferred), 0, "deferred URLs should be tracked")
        # التحقّق التفصيلي: /auth/login يجب أن يكون مؤجَّلاً
        deferred_paths = [u for u in crawler.deferred if "/auth/login" in u]
        self.assertEqual(len(deferred_paths), 1, "auth wrapper should be deferred")
    def test_url_classifier_branches(self):
        """التصنيف الصحيح لكلّ kind من الأنماط الـ5."""
        from utils.url_classifier import (
            UrlClassifier, KIND_SITEMAP, KIND_NAVIGATION,
            KIND_PAGINATION_DEEP, KIND_REDIRECT_WRAPPER, KIND_FILTER_COMBO, KIND_OTHER,
        )
        sm = {"https://x.com/products/a"}
        nav = {"https://x.com/categories"}
        c = UrlClassifier(sitemap_urls=sm, navigation_urls=nav,
                          pagination_max=3, filter_max=1)
        cases = [
            ("https://x.com/products/a", KIND_SITEMAP, False),
            ("https://x.com/categories", KIND_NAVIGATION, False),
            ("https://x.com/c?page=4", KIND_PAGINATION_DEEP, True),
            ("https://x.com/c?page=3", KIND_OTHER, False),  # داخل الحدّ
            ("https://x.com/auth/login?redirect_to=/x", KIND_REDIRECT_WRAPPER, True),
            ("https://x.com/c?brand=a&color=b&size=c", KIND_FILTER_COMBO, True),
            ("https://x.com/random/page", KIND_OTHER, False),
        ]
        for url, exp_kind, exp_deferred in cases:
            k, d = c.classify(url)
            self.assertEqual(
                (k, d), (exp_kind, exp_deferred),
                f"misclassified {url}: got ({k}, {d}), expected ({exp_kind}, {exp_deferred})",
            )
    def test_inject_phase2_seeds_skips_missing_csv(self):
        """v1.08 + v1.09-B1: غياب deferred_urls.csv لا يرمي exception."""
        import tempfile
        from seo_crawler.seo_crawler.main import _inject_phase2_seeds
        crawler = type("FakeCrawler", (), {"sitemap_seeds": []})()
        with tempfile.TemporaryDirectory() as d:
            cfg = {"output": {"output_dir": d}}
            _inject_phase2_seeds(crawler, cfg)
            self.assertEqual(crawler.sitemap_seeds, [])  # بقي فارغاً، بلا exception

