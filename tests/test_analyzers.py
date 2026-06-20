"""
tests/test_analyzers.py — كل analyzers/* + crawl_compare + log_analyzer + accessibility.
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

from analyzers.canonical_analyzer import analyze_canonicals
from analyzers.url_issues import analyze_url_issues
from analyzers.duplicate_detector import detect_duplicates
from analyzers.broken_links import detect_broken_links
from analyzers.thin_content import detect_thin_content
from analyzers.redirect_analyzer import analyze_redirects
from analyzers.seo_issues import collect_seo_issues
from analyzers.schema_validator import validate_schemas
from storage.database import CrawlDatabase


class TestAnalyzers(unittest.TestCase):
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
    def test_accessibility_axe_source_loader(self):
        # IMP-7 (live): تحميل مصدر axe من ملف محلي؛ والتدرّج بسلاسة عند غيابه
        from analyzers.accessibility import load_axe_source
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "axe.min.js"
            p.write_text("/* axe-core */ var axe = { run: 1 };", encoding="utf-8")
            self.assertIn("axe", load_axe_source(str(p)))
        # غير موجود وبلا CDN ⇒ فارغ (يُعطَّل الفحص بسلاسة)
        self.assertEqual(load_axe_source("does_not_exist.js", allow_cdn=False), "")
    def test_log_analyzer_parses_clf_and_finds_orphans(self):
        # IMP-13: تحليل لوغ Apache/Nginx — استخراج زحف Googlebot وحالاته
        from analyzers.log_analyzer import (
            parse_log_line, analyze_log, detect_bot, find_orphan_bot_urls)
        gb = ('66.249.66.1 - - [29/May/2026:10:00:00 +0000] "GET /a HTTP/1.1" '
              '200 1234 "-" "Mozilla/5.0 (compatible; Googlebot/2.1; +http://google.com/bot.html)"')
        usr = ('1.2.3.4 - - [29/May/2026:10:01:00 +0000] "GET /b HTTP/1.1" '
               '200 500 "-" "Mozilla/5.0 (Windows NT 10.0)"')
        gb_404 = ('66.249.66.2 - - [29/May/2026:10:02:00 +0000] "GET /missing HTTP/1.1" '
                  '404 0 "-" "Googlebot/2.1"')
        r = parse_log_line(gb)
        self.assertIsNotNone(r)
        self.assertTrue(r["is_bot"])
        self.assertEqual(r["bot"], "Googlebot")
        self.assertEqual(r["status"], 200)
        self.assertEqual(r["path"], "/a")
        self.assertEqual(detect_bot("Mozilla/5.0 (compatible; Bingbot/2.0)"), "Bingbot")
        self.assertEqual(detect_bot("plain browser"), "")
        # تحليل تدفّق
        res = analyze_log([gb, usr, gb_404, gb], bot_only=True)
        # المستخدم العادي مُستبعَد، Googlebot يظهر مرّتين على /a و404 على /missing
        paths = {r["path"]: r for r in res["per_url"]}
        self.assertEqual(paths["/a"]["hits"], 2)
        self.assertEqual(paths["/missing"]["status_404"], 1)
        self.assertEqual(res["summary"]["bot_lines"], 3)
        self.assertEqual(res["summary"]["total_404"], 1)
        self.assertGreaterEqual(res["summary"]["top_bots"][0]["hits"], 3)
        # يتامى مزحوفون: زحفها البوت لكن الزاحف لم يرَها
        crawl = ["https://x.com/a"]  # فقط /a معروف
        orph = find_orphan_bot_urls(res["per_url"], crawl)
        orph_paths = {r["path"] for r in orph}
        self.assertIn("/missing", orph_paths)
        self.assertNotIn("/a", orph_paths)
    def test_status_of_handles_strings_and_none(self):
        """v1.09-B2: status_of يتحمّل str/None/مشوّش بلا crash."""
        from analyzers._coerce import status_of, is_4xx
        self.assertEqual(status_of({"status_code": "404"}), 404)
        self.assertEqual(status_of({"status_code": None}), 0)
        self.assertEqual(status_of({"status_code": "301 Moved"}), 301)
        self.assertEqual(status_of({}), 0)
        self.assertTrue(is_4xx({"status_code": "404"}))
        self.assertFalse(is_4xx({"status_code": "200"}))

