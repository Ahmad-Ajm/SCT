import csv
import sys
import tempfile
import threading
import unittest
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "seo_crawler" / "seo_crawler"
sys.path.insert(0, str(APP))

from crawler.robots_parser import RobotsParser
from analyzers.canonical_analyzer import analyze_canonicals
from analyzers.url_issues import analyze_url_issues
from analyzers.duplicate_detector import detect_duplicates
from analyzers.broken_links import detect_broken_links
from analyzers.thin_content import detect_thin_content
from analyzers.redirect_analyzer import analyze_redirects
from analyzers.seo_issues import collect_seo_issues
from analyzers.schema_validator import validate_schemas
from exporters.csv_exporter import CSVExporter
from exporters.html_exporter import HTMLReportExporter
from storage.database import CrawlDatabase
from utils.helpers import (
    normalize_url,
    is_internal_url,
    is_safe_remote_url,
    matches_any_pattern,
    neutralize_formula,
    format_duration,
)


class FakeResponse:
    status_code = 200
    text = "User-agent: *\nDisallow: /blocked\nSitemap: https://example.com/sitemap.xml\n"
    encoding = "utf-8"

    def iter_content(self, chunk_size=8192):
        data = self.text.encode("utf-8")
        for i in range(0, len(data), chunk_size):
            yield data[i:i + chunk_size]

    def close(self):
        return None


@dataclass
class MinimalPage:
    url: str
    status_code: int = 200
    is_indexable: bool = True
    canonical: str = ""


class _FakeAIResp:
    """استجابة requests وهمية لاختبار مستشار الذكاء الاصطناعي دون شبكة."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class CoreBehaviorTests(unittest.TestCase):
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

    def test_csv_exporter_serializes_nested_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            exporter = CSVExporter(tmp)
            path = exporter._export("nested.csv", [{"url": "x", "tags": ["a", "b"]}])
            with open(path, newline="", encoding="utf-8-sig") as f:
                row = next(csv.DictReader(f))
            self.assertEqual(row["url"], "x")
            self.assertEqual(row["tags"], '["a", "b"]')

    def test_url_issues_analyzer_detects_common_patterns(self):
        pages = [
            MinimalPage("https://example.com/Some_Path/?utm_source=x&a=1&b=2&c=3&d=4&e=5"),
            MinimalPage("https://example.com/arabic/مرحبا"),
        ]
        result = analyze_url_issues(pages, max_length=25, max_query_params=3, flag_non_ascii=True)
        self.assertEqual(result["long_urls_count"], 2)
        self.assertEqual(result["uppercase_urls_count"], 1)
        self.assertEqual(result["underscore_urls_count"], 1)
        self.assertEqual(result["tracking_params_count"], 1)
        self.assertEqual(result["too_many_query_params_count"], 1)
        self.assertEqual(result["non_ascii_urls_count"], 1)

    def test_canonical_analyzer_detects_bad_targets_and_loops(self):
        pages = [
            MinimalPage("https://example.com/a", canonical="https://example.com/b"),
            MinimalPage("https://example.com/b", canonical="https://example.com/a"),
            MinimalPage("https://example.com/missing"),
            MinimalPage("https://example.com/broken-target", status_code=404),
            MinimalPage("https://example.com/to-broken", canonical="https://example.com/broken-target"),
            MinimalPage("https://example.com/external", canonical="https://other.example/page"),
        ]
        result = analyze_canonicals(pages, primary_domain="example.com")
        self.assertEqual(result["canonical_loops_count"], 2)
        self.assertEqual(result["canonical_to_non_200_count"], 1)
        self.assertEqual(result["canonical_external_count"], 1)
        self.assertEqual(result["missing_canonicals_count"], 1)

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


class RegressionTests(unittest.TestCase):
    """اختبارات تحمي الإصلاحات الموثّقة في AUDIT_NOTES."""

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

    def test_analyzers_accept_dict_rows(self):
        pages = [
            {"url": "https://x.com/", "status_code": 200, "is_indexable": True,
             "title": "Home", "meta_description": "d", "h1_text": ["H"], "h1_count": 1,
             "content_hash": "abc", "word_count": 50, "depth": 0, "content_type": "text/html",
             "title_length": 4, "meta_description_length": 1},
            {"url": "https://x.com/404", "status_code": 404, "is_indexable": False, "depth": 1},
        ]
        links = [{"from_url": "https://x.com/", "to_url": "https://x.com/404",
                  "to_url_normalized": "https://x.com/404", "is_internal": True}]
        dup = detect_duplicates(pages)
        broken = detect_broken_links(pages, links)
        thin = detect_thin_content(pages)
        seo = collect_seo_issues(pages=pages, duplicate_data=dup, orphan_data={},
                                 redirect_data={}, thin_content_data=thin, broken_data=broken,
                                 images_data={}, config={})
        self.assertEqual(broken["pages_4xx_count"], 1)
        self.assertIn("summary", seo)

    def test_redirect_chain_ordering_and_internal(self):
        reds = [
            {"from_url": "https://x.com/b", "to_url": "https://x.com/c",
             "status_code": 301, "chain_length": 2, "original_url": "https://x.com/a"},
            {"from_url": "https://x.com/a", "to_url": "https://x.com/b",
             "status_code": 302, "chain_length": 2, "original_url": "https://x.com/a"},
        ]
        r = analyze_redirects([], reds, primary_domain="x.com")
        self.assertEqual(r["redirect_chains"][0]["final_url"], "https://x.com/c")
        self.assertEqual([h["from"].rsplit("/", 1)[-1]
                          for h in r["redirect_chains"][0]["hops"]], ["a", "b"])
        self.assertEqual(r["internal_redirects_count"], 2)
        self.assertEqual(r["temporary_redirects_count"], 1)

    def test_microdata_schema_is_validated(self):
        sv = validate_schemas([
            {"page_url": "p", "type": "Product", "format": "microdata",
             "properties": {"name": "X"}}
        ])
        self.assertEqual(sv["total_schemas"], 1)
        self.assertIn("Product", sv.get("by_type", {}))

    def test_normalize_url_resolves_dots_keeps_trailing(self):
        self.assertEqual(normalize_url("https://e.com/a/../b"), "https://e.com/b")
        self.assertNotEqual(normalize_url("https://e.com/p/"), normalize_url("https://e.com/p"))

    def test_is_internal_url_strips_only_leading_www(self):
        self.assertTrue(is_internal_url("https://www.e.com/x", "e.com"))
        # subdomain still internal, but mid-string www is not mangled into a false match
        self.assertFalse(is_internal_url("https://other.com/x", "e.com"))

    def test_matches_any_pattern_substring_and_glob(self):
        self.assertTrue(matches_any_pattern("https://e.com/admin/x", ["/admin"]))
        self.assertTrue(matches_any_pattern("https://e.com/p.pdf", ["*.pdf"]))
        self.assertFalse(matches_any_pattern("https://e.com/page", ["*.pdf"]))

    def test_ssrf_guard_blocks_internal(self):
        self.assertFalse(is_safe_remote_url("http://127.0.0.1/")[0])
        self.assertFalse(is_safe_remote_url("http://169.254.169.254/")[0])
        self.assertFalse(is_safe_remote_url("file:///etc/passwd")[0])

    def test_formula_neutralization(self):
        self.assertEqual(neutralize_formula("=SUM(A1)"), "'=SUM(A1)")
        self.assertEqual(neutralize_formula("normal"), "normal")

    def test_format_duration_no_sixty_seconds(self):
        self.assertEqual(format_duration(119.6), "2m 0s")
        self.assertNotIn("60s", format_duration(119.9))

    def test_monitoring_span_event_tolerate_reserved_attrs(self):
        # يحمي من عودة الخطأ: event()/span() got multiple values for 'status'
        from utils.monitoring import configure_monitoring, span, event
        configure_monitoring({"enabled": True, "log_function_calls": False,
                              "log_url_events": False})
        with span("crawler.extract.all", url="u", status=200, bytes=10):
            pass
        event("crawler.http_response", "ok", url="u", http_status=200)
        event("crawler.fetch", "error", url="u", error="Timeout", http_status=0)
        try:
            with span("phase.x", status=500, error="x"):
                raise ValueError("boom")
        except ValueError:
            pass
        configure_monitoring({"enabled": False})

    def test_non_ascii_urls_off_by_default(self):
        pages = [MinimalPage("https://example.com/arabic/مرحبا")]
        result = analyze_url_issues(pages)  # default flag_non_ascii=False
        self.assertEqual(result["non_ascii_urls_count"], 0)

    def test_images_unique_vs_occurrences(self):
        from analyzers.images_analyzer import analyze_images
        imgs = [
            {"page_url": "p1", "src": "logo.png", "has_alt": False,
             "has_explicit_dimensions": False, "file_extension": "png", "is_lazy_loaded": False},
            {"page_url": "p2", "src": "logo.png", "has_alt": False,
             "has_explicit_dimensions": False, "file_extension": "png", "is_lazy_loaded": False},
            {"page_url": "p1", "src": "hero.webp", "has_alt": True, "alt": "hero",
             "has_explicit_dimensions": True, "file_extension": "webp", "is_lazy_loaded": True},
        ]
        r = analyze_images(imgs)
        self.assertEqual(r["total_images"], 3)        # occurrences
        self.assertEqual(r["unique_images"], 2)       # unique by src
        self.assertEqual(r["unique_no_alt_count"], 1)  # only logo.png unique
        self.assertEqual(r["unique_legacy_formats_count"], 1)

    def test_security_analyzer_flags_missing_headers(self):
        from analyzers.security_analyzer import analyze_security
        pages = [{"url": "https://x.com/", "status_code": 200, "has_mixed_content": False},
                 {"url": "http://x.com/insecure", "status_code": 200}]
        headers = [{"page_url": "https://x.com/", "hsts_enabled": True, "csp": "default-src",
                    "x_frame_options": "DENY", "x_content_type_options": "nosniff",
                    "referrer_policy": "", "permissions_policy": ""}]
        r = analyze_security(pages, headers)
        self.assertEqual(r["pages_checked"], 2)
        self.assertEqual(r["not_https_count"], 1)
        self.assertGreater(r["total_issues"], 0)

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

    def test_lighthouse_importer(self):
        import json as _json
        from integrations.lighthouse_importer import LighthouseImporter
        with tempfile.TemporaryDirectory() as tmp:
            _json.dump({"finalUrl": "https://x.com/",
                        "categories": {"performance": {"score": 0.83}, "seo": {"score": 1.0}}},
                       open(Path(tmp) / "a.json", "w"))
            rows = LighthouseImporter(tmp).load()
            self.assertEqual(rows[0]["performance"], 83)
            self.assertEqual(rows[0]["seo"], 100)

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

    def test_run_log_summary_counts_by_level_not_substring(self):
        # العدّ يجب أن يعتمد على مستوى السجل الفعلي (| LEVEL |) لا على ورود
        # الكلمة داخل نص الرسالة (سطر INFO يذكر ERROR لا يُحتسب خطأً).
        sys.path.insert(0, str(ROOT / "webapp"))
        from job_runner import JobRunner
        runner = JobRunner()
        with tempfile.TemporaryDirectory() as tmp:
            lp = Path(tmp) / "run.log"
            lp.write_text(
                "12:00:00 | INFO     | starting crawl, 0 ERROR so far\n"
                "12:00:01 | ERROR    | fetch failed for /a\n"
                "12:00:02 | WARNING  | slow page /b\n"
                "12:00:03 | ERROR    | fetch failed for /c\n"
                "12:00:04 | CRITICAL | aborting\n"
                "Traceback (most recent call last):\n"
                "    raise ValueError('x')\n",
                encoding="utf-8",
            )
            s = runner._summarize_run_log(lp)
        self.assertEqual(s["error_count"], 2)
        self.assertEqual(s["warning_count"], 1)
        self.assertEqual(s["critical_count"], 1)
        self.assertEqual(s["traceback_count"], 1)
        # السطور المهمة: ERROR×2 + CRITICAL×1 + Traceback×1
        self.assertEqual(len(s["last_important_lines"]), 4)

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

    def test_pagination_analyzer_sequence_and_canonical(self):
        from analyzers.pagination_analyzer import analyze_pagination
        pages = [
            {"url": "https://x.com/p1", "status_code": 200, "is_paginated": True,
             "pagination_next": "https://x.com/p2", "pagination_prev": "",
             "canonical": "https://x.com/p1"},
            {"url": "https://x.com/p2", "status_code": 200, "is_paginated": True,
             "pagination_next": "https://x.com/p3", "pagination_prev": "https://x.com/WRONG",
             "canonical": "https://x.com/p1"},
            {"url": "https://x.com/p3", "status_code": 404, "is_paginated": True,
             "pagination_next": "", "pagination_prev": "https://x.com/p2", "canonical": ""},
        ]
        r = analyze_pagination(pages)
        self.assertEqual(r["total_paginated"], 3)
        self.assertEqual(r["first_pages"], 1)            # p1: next بلا prev
        flagged = {(i["page_url"], i["issue"]) for i in r["issues"]}
        self.assertIn(("https://x.com/p1", "broken_sequence"), flagged)
        self.assertIn(("https://x.com/p2", "non_self_canonical_on_paginated"), flagged)
        self.assertIn(("https://x.com/p2", "next_target_not_ok"), flagged)

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

    def test_ai_advisor_graceful_without_key(self):
        from integrations.ai_advisor import AIAdvisor
        with patch.dict("os.environ", {"AI_API_KEY": ""}, clear=False):
            adv = AIAdvisor(provider="openai", api_key="")
            out = adv.analyze({"issue_counts": {"total": 1}})
        self.assertTrue(out["enabled"])
        self.assertEqual(out["error"], "missing_api_key")
        self.assertEqual(out["recommendations"], [])

    def test_ai_advisor_openai_compatible_call_and_parse(self):
        from integrations.ai_advisor import AIAdvisor
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured.update(url=url, headers=headers, body=json)
            return _FakeAIResp({"choices": [{"message": {"content":
                '```json\n{"summary":"ok","recommendations":'
                '[{"title":"Fix titles","priority":"high"}]}\n```'}}]})

        with patch("requests.post", side_effect=fake_post):
            adv = AIAdvisor(provider="deepseek", api_key="k", language="en")
            out = adv.analyze({"issue_counts": {"total": 1}})
        self.assertEqual(out["summary"], "ok")
        self.assertEqual(out["recommendations"][0]["title"], "Fix titles")
        self.assertTrue(captured["url"].endswith("/chat/completions"))
        self.assertEqual(captured["headers"]["Authorization"], "Bearer k")
        self.assertEqual(captured["body"]["model"], "deepseek-chat")
        self.assertEqual([m["role"] for m in captured["body"]["messages"]],
                         ["system", "user"])

    def test_ai_advisor_gemini_call(self):
        from integrations.ai_advisor import AIAdvisor
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            return _FakeAIResp({"candidates": [{"content": {"parts": [
                {"text": '{"summary":"g","recommendations":[]}'}]}}]})

        with patch("requests.post", side_effect=fake_post):
            adv = AIAdvisor(provider="gemini", api_key="K", language="en")
            out = adv.analyze({"x": 1})
        self.assertEqual(out["summary"], "g")
        self.assertIn(":generateContent", captured["url"])
        # المفتاح في ترويسة x-goog-api-key لا في الـ URL (لا يُسجَّل في الوسطاء)
        self.assertNotIn("key=", captured["url"])
        self.assertEqual(captured["headers"]["x-goog-api-key"], "K")

    def test_ai_advisor_rejects_private_base_url_ssrf(self):
        # حماية SSRF: عنوان داخلي/loopback مرفوض ما لم يُفعَّل allow_private
        from integrations.ai_advisor import AIAdvisor
        adv = AIAdvisor(provider="openai_compatible", api_key="k", model="m",
                        base_url="http://127.0.0.1:11434/v1")
        ready, reason = adv.is_ready()
        self.assertFalse(ready)
        self.assertEqual(reason, "unsafe_base_url")
        adv2 = AIAdvisor(provider="openai_compatible", api_key="k", model="m",
                         base_url="http://127.0.0.1:11434/v1", allow_private=True)
        self.assertTrue(adv2.is_ready()[0])

    def test_redirect_analyzer_dedups_shared_internal_hop(self):
        from analyzers.redirect_analyzer import analyze_redirects
        # القفزة m→final مشتركة بين أصلين؛ يجب ألا تتكرر في internal_redirects
        redirects = [
            {"original_url": "https://x.com/a", "from_url": "https://x.com/a",
             "to_url": "https://x.com/m", "status_code": 301},
            {"original_url": "https://x.com/a", "from_url": "https://x.com/m",
             "to_url": "https://x.com/final", "status_code": 301},
            {"original_url": "https://x.com/b", "from_url": "https://x.com/b",
             "to_url": "https://x.com/m", "status_code": 301},
            {"original_url": "https://x.com/b", "from_url": "https://x.com/m",
             "to_url": "https://x.com/final", "status_code": 301},
        ]
        r = analyze_redirects([], redirects, primary_domain="x.com")
        pairs = [(i["from"], i["to"]) for i in r["internal_redirects"]]
        self.assertEqual(pairs.count(("https://x.com/m", "https://x.com/final")), 1)
        self.assertEqual(len(pairs), 3)  # a→m, m→final, b→m

    def test_link_score_pagerank_basic(self):
        # شبكة بسيطة: A→B, A→C, B→C, C→B → C يجب أن يحصل على درجة أعلى من A
        from analyzers.link_score import compute_link_score
        pages = [{"url": "https://x.com/a"}, {"url": "https://x.com/b"},
                 {"url": "https://x.com/c"}]
        links = [
            {"from_url": "https://x.com/a", "to_url": "https://x.com/b", "is_internal": True},
            {"from_url": "https://x.com/a", "to_url": "https://x.com/c", "is_internal": True},
            {"from_url": "https://x.com/b", "to_url": "https://x.com/c", "is_internal": True},
            {"from_url": "https://x.com/c", "to_url": "https://x.com/b", "is_internal": True},
        ]
        r = compute_link_score(pages, links)
        scores = {p["url"]: p["link_score"] for p in r["pages"]}
        self.assertGreater(scores["https://x.com/c"], scores["https://x.com/a"])
        self.assertGreater(scores["https://x.com/b"], scores["https://x.com/a"])
        # نوع البيانات وتطبيع 0..100
        self.assertEqual(r["count"], 3)
        self.assertAlmostEqual(max(scores.values()), 100.0, places=1)

    def test_simhash_near_duplicate_detection(self):
        from utils.helpers import compute_simhash, hamming_distance
        from analyzers.near_duplicate import detect_near_duplicates
        a = "the quick brown fox jumps over the lazy dog and runs fast".split()
        b = "the quick brown fox jumps over the lazy dog and runs fast".split() + ["today"]
        c = "completely different content with unrelated words about ships and oceans now".split()
        ha, hb, hc = (compute_simhash(a), compute_simhash(b), compute_simhash(c))
        # المتشابهتان أقرب بكثير من المختلفة
        self.assertLess(hamming_distance(ha, hb), hamming_distance(ha, hc))
        pages = [
            {"url": "u1", "content_simhash": str(ha)},
            {"url": "u2", "content_simhash": str(hb)},
            {"url": "u3", "content_simhash": str(hc)},
        ]
        r = detect_near_duplicates(pages, max_distance=8)
        urls = {(p["url_a"], p["url_b"]) for p in r["pairs"]}
        self.assertTrue(any({"u1", "u2"} == {a, b} for (a, b) in urls))
        # u3 لا يجب أن يظهر مع u1 أو u2 ضمن المسافة المختارة
        for a_, b_ in urls:
            self.assertNotIn("u3", (a_, b_))

    def test_spell_check_graceful_without_library(self):
        # السلوك السلس عندما تكون pyspellchecker غير مثبتة (الحالة العامة عندنا)
        from analyzers.spell_check import run_spell_check
        r = run_spell_check([{"url": "u", "language": "en", "title": "hello world",
                              "meta_description": "", "h1_text": []}])
        self.assertIn(r["status"], ("library_missing", "ok", "no_supported_language_pages"))
        self.assertIsInstance(r["top_misspellings"], list)

    def test_ai_summary_builder_compacts_audit(self):
        from integrations.ai_advisor import build_audit_summary_for_ai
        analysis = {
            "seo_issues": {"summary": {"total_issues": 3, "critical_count": 1},
                           "by_severity": {"🔴 Critical": [
                               {"issue_type": "Missing title", "affected_count": 5}]}},
            "opportunities": {"opportunities": [
                {"url": "https://x.com/a", "priority_score": 9, "clicks": 10}]},
        }
        s = build_audit_summary_for_ai(analysis, site_url="https://x.com/")
        self.assertEqual(s["site"], "https://x.com/")
        self.assertEqual(s["issue_counts"]["critical"], 1)
        self.assertEqual(s["top_issue_types"][0]["issue_type"], "Missing title")
        self.assertEqual(s["top_opportunities"][0]["url"], "https://x.com/a")

    def test_link_score_dedups_repeated_internal_edges(self):
        # روابط التنقّل/التذييل تتكرّر عبر كل صفحة؛ يجب احتساب الحافة مرة واحدة
        # كي لا يتضخّم PageRank بشكل مصطنع. هنا A→B مكرّرة 50 مرة، A→C مرة واحدة.
        from analyzers.link_score import compute_link_score
        pages = [{"url": "https://x.com/a"}, {"url": "https://x.com/b"},
                 {"url": "https://x.com/c"}]
        links = [{"from_url": "https://x.com/a", "to_url": "https://x.com/b",
                  "is_internal": True} for _ in range(50)]
        links.append({"from_url": "https://x.com/a", "to_url": "https://x.com/c",
                      "is_internal": True})
        r = compute_link_score(pages, links)
        scores = {p["url"]: p["link_score"] for p in r["pages"]}
        # بعد إزالة التكرار: A توزّع حصّتها بالتساوي على B و C ⇒ تساوي تقريبي
        self.assertAlmostEqual(scores["https://x.com/b"], scores["https://x.com/c"], places=1)

    def test_near_duplicate_autocorrects_invalid_bands(self):
        # ضمان LSH يصحّ فقط عندما bands > max_distance؛ يجب التصحيح تلقائياً
        # بدل فقدان أزواج متشابهة. هنا bands=2 و max_distance=8 (2 ≤ 8 غير صالح).
        from utils.helpers import compute_simhash, hamming_distance
        from analyzers.near_duplicate import detect_near_duplicates
        a = "the quick brown fox jumps over the lazy dog and runs fast daily".split()
        b = a + ["today"]
        ha, hb = compute_simhash(a), compute_simhash(b)
        # نتأكّد أوّلاً أنّ الزوج فعلاً ضمن المسافة المختارة قبل اختبار اكتشافه
        self.assertLessEqual(hamming_distance(ha, hb), 8)
        pages = [{"url": "u1", "content_simhash": str(ha)},
                 {"url": "u2", "content_simhash": str(hb)}]
        r = detect_near_duplicates(pages, max_distance=8, bands=2)
        urls = {(p["url_a"], p["url_b"]) for p in r["pairs"]}
        self.assertTrue(any({"u1", "u2"} == {a_, b_} for (a_, b_) in urls))

    def test_duplicate_detector_coerces_non_string_fields(self):
        # عناوين/أوصاف قد تصل كأرقام من قاعدة البيانات؛ يجب ألا ينهار التحليل
        from analyzers.duplicate_detector import detect_duplicates
        pages = [
            {"url": "https://x.com/1", "status_code": 200, "is_indexable": True,
             "title": 2024, "meta_description": 100},
            {"url": "https://x.com/2", "status_code": 200, "is_indexable": True,
             "title": 2024, "meta_description": 100},
        ]
        r = detect_duplicates(pages)
        self.assertEqual(r["duplicate_titles_count"], 1)

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


    def test_pagespeed_lighthouse_table_extraction(self):
        # IMP-17أ: استخراج جداول Lighthouse المنظّمة من الخام
        from integrations.pagespeed_api import (
            extract_lighthouse_tables, extract_failed_audits)
        data = {"lighthouseResult": {"audits": {
            "image-alt": {"title": "Image alt", "score": 0, "scoreDisplayMode": "binary",
                          "displayValue": "", "details": {"type": "table"}},
            "speed-index": {"title": "Speed Index", "score": 0.4, "scoreDisplayMode": "numeric",
                            "numericValue": 11876.6, "numericUnit": "millisecond",
                            "details": {"type": "numeric"}},
            "focus-traps": {"title": "Focus traps", "score": None, "scoreDisplayMode": "manual"},
            "network-requests": {"details": {"type": "table", "items": [
                {"url": "https://x.com/a.js", "resourceType": "Script", "transferSize": 100,
                 "resourceSize": 300, "statusCode": 200, "protocol": "h2", "priority": "High",
                 "mimeType": "text/javascript", "networkRequestTime": 1.0,
                 "networkEndTime": 5.0, "entity": "x.com"}]}},
            "script-treemap-data": {"details": {"type": "treemap-data", "nodes": [
                {"name": "https://x.com/a.js", "resourceBytes": 1000, "encodedBytes": 400,
                 "unusedBytes": 250},
                {"name": "https://x.com/zero.js", "resourceBytes": 0, "encodedBytes": 0,
                 "unusedBytes": 0}]}},
        }}}
        t = extract_lighthouse_tables(data, "https://x.com/", "mobile")
        self.assertEqual(len(t["audits"]), 5)  # كل المفاتيح تدقيقات (شاملة network/treemap)
        self.assertEqual(len(t["network_requests"]), 1)
        self.assertEqual(t["network_requests"][0]["request_url"], "https://x.com/a.js")
        tm = {r["script_url"]: r["unusedPercent"] for r in t["js_treemap"]}
        self.assertEqual(tm["https://x.com/a.js"], 25.0)
        self.assertEqual(tm["https://x.com/zero.js"], 0.0)  # حارس القسمة على صفر
        # التدقيقات الفاشلة: image-alt(0) و speed-index(0.4) فقط؛ focus-traps(manual/None) مُستبعَد
        fa = {r["audit_id"] for r in extract_failed_audits(data, "https://x.com/", "mobile")}
        self.assertEqual(fa, {"image-alt", "speed-index"})


    def test_gsc_cannibalization_and_link_opportunities(self):
        # IMP-1: تكلّس الكلمات + فُرَص الروابط الداخلية من بيانات GSC
        from analyzers.gsc_insights import (
            detect_cannibalization, find_internal_link_opportunities)
        page_queries = [
            {"page": "https://x.com/a", "query": "كتب", "clicks": 10, "impressions": 500, "position": 5},
            {"page": "https://x.com/b", "query": "كتب", "clicks": 3, "impressions": 300, "position": 8},
            {"page": "https://x.com/c", "query": "روايات", "clicks": 20, "impressions": 200, "position": 3},
        ]
        cann = detect_cannibalization(page_queries, min_impressions=10, min_pages=2)
        # "كتب" يتنافس عليه صفحتان؛ "روايات" صفحة واحدة فقط
        self.assertEqual(cann["count"], 1)
        self.assertEqual(cann["cannibalization"][0]["query"], "كتب")
        self.assertEqual(cann["cannibalization"][0]["pages_count"], 2)

        gsc_pages = [
            {"page": "https://x.com/strong", "clicks": 50, "impressions": 5000, "position": 4},
            {"page": "https://x.com/weak", "clicks": 5, "impressions": 800, "position": 12},
            {"page": "https://x.com/lowimp", "clicks": 0, "impressions": 5, "position": 40},
        ]
        link_score_pages = [
            {"url": "https://x.com/strong", "internal_inlinks": 40},
            {"url": "https://x.com/weak", "internal_inlinks": 1},
        ]
        opp = find_internal_link_opportunities(
            gsc_pages, link_score_pages, min_impressions=100, max_inlinks=2)
        urls = {o["page"] for o in opp["opportunities"]}
        self.assertIn("https://x.com/weak", urls)       # ظهور عالٍ + روابط قليلة
        self.assertNotIn("https://x.com/strong", urls)  # روابط كثيرة
        self.assertNotIn("https://x.com/lowimp", urls)  # ظهور منخفض


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


    def test_seo_issue_hints_attached(self):
        # IMP-8: إثراء المشاكل بالأثر/الجهد/لماذا/كيف وأولوية
        from analyzers.hints import attach_hints
        seo = {"all_issues": [
            {"issue_type": "Broken internal links", "severity": "🔴 Critical"},
            {"issue_type": "Missing meta description", "severity": "🟡 Medium"},
        ], "by_severity": {}, "by_category": {}}
        attach_hints(seo)
        broken = seo["all_issues"][0]
        self.assertEqual(broken["impact"], "high")
        self.assertEqual(broken["effort"], "low")
        self.assertTrue(broken["why_it_matters"])
        self.assertTrue(broken["how_to_fix"])
        self.assertGreater(broken["priority_score"], 0)

    def test_crawl_compare_fixed_new_persisting(self):
        # IMP-4: مقارنة زمنية بين زحفتين
        from analyzers.crawl_compare import compare_crawls
        old = {"pages": [{"url": "https://x.com/a"}, {"url": "https://x.com/b"}],
               "seo_issues": {"all_issues": [
                   {"issue_type": "Missing title", "affected_count": 5},
                   {"issue_type": "Broken links", "affected_count": 3}],
                   "summary": {"total_issues": 8}}}
        new = {"pages": [{"url": "https://x.com/a"}, {"url": "https://x.com/c"}],
               "seo_issues": {"all_issues": [
                   {"issue_type": "Missing title", "affected_count": 2},
                   {"issue_type": "Thin content", "affected_count": 4}],
                   "summary": {"total_issues": 6}}}
        r = compare_crawls(old, new)
        fixed = {f["issue_type"] for f in r["fixed_issue_types"]}
        newp = {f["issue_type"] for f in r["new_issue_types"]}
        pers = {f["issue_type"]: f for f in r["persisting_issue_types"]}
        self.assertEqual(fixed, {"Broken links"})
        self.assertEqual(newp, {"Thin content"})
        self.assertEqual(pers["Missing title"]["delta"], -3)
        self.assertTrue(r["summary"]["improved"])
        self.assertEqual(r["summary"]["pages_added_count"], 1)   # /c
        self.assertEqual(r["summary"]["pages_removed_count"], 1)  # /b

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


    def test_auto_install_present_and_refuses_unknown(self):
        # IMP-16: المكتبة الموجودة لا تُثبَّت؛ غير المُدرَجة تُرفَض بأمان بلا تثبيت
        from utils.auto_install import ensure_package
        self.assertTrue(ensure_package("json"))  # موجودة في المكتبة القياسية
        # اسم خارج القائمة البيضاء وغير موجود ⇒ يُرفض دون محاولة تثبيت
        self.assertFalse(ensure_package("totally_made_up_pkg_xyz", auto=True))
        # مُدرَج لكن التثبيت معطّل ⇒ لا يُثبّت
        self.assertFalse(ensure_package("playwright_not_real_import", pip_name="x", auto=False))

    def test_gsc_url_inspection_parser(self):
        # IMP-2: تسطيح استجابة URL Inspection
        from integrations.gsc_api import parse_inspection_result
        resp = {"inspectionResult": {
            "indexStatusResult": {"verdict": "PASS", "coverageState": "Submitted and indexed",
                                  "robotsTxtState": "ALLOWED", "googleCanonical": "https://x.com/a"},
            "mobileUsabilityResult": {"verdict": "PASS"},
        }}
        row = parse_inspection_result(resp, "https://x.com/a")
        self.assertEqual(row["verdict"], "PASS")
        self.assertEqual(row["coverage_state"], "Submitted and indexed")
        self.assertEqual(row["mobile_verdict"], "PASS")

    def test_crux_history_parser(self):
        # IMP-9: تسطيح سلسلة CrUX الزمنية إلى صف لكل فترة
        from integrations.crux_history import parse_crux_history
        resp = {"record": {
            "collectionPeriods": [
                {"lastDate": {"year": 2026, "month": 4, "day": 1}},
                {"lastDate": {"year": 2026, "month": 5, "day": 1}}],
            "metrics": {
                "largest_contentful_paint": {"percentilesTimeseries": {"p75s": [2500, 2100]}},
                "cumulative_layout_shift": {"percentilesTimeseries": {"p75s": ["0.10", "0.05"]}},
            }}}
        rows = parse_crux_history(resp)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["period_end"], "2026-04-01")
        self.assertEqual(rows[0]["lcp_p75_ms"], 2500)
        self.assertEqual(rows[1]["cls_p75"], "0.05")

    def test_accessibility_axe_summary(self):
        # IMP-7: تلخيص ناتج axe وترتيبه حسب الأثر
        from analyzers.accessibility import summarize_axe_results
        axe = {"violations": [
            {"id": "color-contrast", "impact": "serious", "help": "Contrast",
             "nodes": [{}, {}]},
            {"id": "image-alt", "impact": "critical", "help": "Alt", "nodes": [{}]},
        ]}
        s = summarize_axe_results(axe, "https://x.com/")
        self.assertEqual(s["violations_count"], 2)
        self.assertEqual(s["nodes_total"], 3)
        self.assertEqual(s["violations"][0]["rule_id"], "image-alt")  # critical أولاً
        self.assertEqual(s["by_impact"]["serious"], 1)


    def test_connection_test_helper_times_out(self):
        # اختبارات الاتصال محدودة بمهلة كي لا يتعلّق الطلب (سبب CancelledError عند الإيقاف)
        import asyncio as _asyncio
        sys.path.insert(0, str(ROOT / "webapp"))
        try:
            import app as webapp_app
        except Exception:  # noqa: BLE001
            self.skipTest("webapp app import unavailable in this environment")

        def _slow():
            import time
            time.sleep(0.5)
            return {"ok": True}

        res = _asyncio.run(webapp_app._run_conn_test(_slow, timeout=0.1))
        self.assertFalse(res["ok"])
        self.assertIn("مهلة", res["error"])  # رسالة انتهاء المهلة


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


if __name__ == "__main__":
    unittest.main()
