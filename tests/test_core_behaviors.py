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


if __name__ == "__main__":
    unittest.main()
