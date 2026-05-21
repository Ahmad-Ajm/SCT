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
from exporters.csv_exporter import CSVExporter
from storage.database import CrawlDatabase


class FakeResponse:
    status_code = 200
    text = "User-agent: *\nDisallow: /blocked\nSitemap: https://example.com/sitemap.xml\n"


@dataclass
class MinimalPage:
    url: str
    status_code: int = 200
    is_indexable: bool = True
    canonical: str = ""


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
        result = analyze_url_issues(pages, max_length=25, max_query_params=3)
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


if __name__ == "__main__":
    unittest.main()
