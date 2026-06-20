"""
tests/test_integrations.py — gsc_api / ga4_api / pagespeed / crux / ai_advisor / lighthouse / backlinks.
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


class TestIntegrations(unittest.TestCase):
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
    def test_google_listing_parsers_and_code_extractor(self):
        # المُحلّلات النقية: مواقع GSC، خصائص GA4، واستخراج code من رابط callback
        from integrations.gsc_api import parse_gsc_sites
        from integrations.ga4_api import parse_ga4_properties
        sys.path.insert(0, str(ROOT / "webapp"))
        try:
            import app as webapp_app
        except Exception:  # noqa: BLE001
            self.skipTest("webapp app import unavailable")

        # GSC sites
        sites = parse_gsc_sites({"siteEntry": [
            {"siteUrl": "https://a.com/", "permissionLevel": "siteOwner"},
            {"siteUrl": "https://b.com/", "permissionLevel": "siteFullUser"},
            {"siteUrl": "", "permissionLevel": "x"},  # يُتجاهَل
        ]})
        self.assertEqual([s["site_url"] for s in sites], ["https://a.com/", "https://b.com/"])
        self.assertEqual(sites[0]["permission_level"], "siteOwner")

        # GA4 properties — مسطّحة من accountSummaries
        props = parse_ga4_properties({"accountSummaries": [
            {"displayName": "Acme", "propertySummaries": [
                {"property": "properties/12345", "displayName": "Acme.com"},
                {"property": "properties/67890", "displayName": "Acme blog",
                 "propertyType": "PROPERTY_TYPE_ORDINARY"}]},
            {"displayName": "Other", "propertySummaries": [
                {"property": "", "displayName": "ignored"}]},  # بلا معرّف ⇒ يُتجاهَل
        ]})
        self.assertEqual({p["property_id"] for p in props}, {"12345", "67890"})
        self.assertEqual(props[0]["account"], "Acme")

        # استخراج الرمز: من رمز خام، ومن رابط callback كامل، ومن سلسلة استعلام فقط
        ex = webapp_app._extract_oauth_code
        self.assertEqual(ex("4/0Aabc-raw_code"), "4/0Aabc-raw_code")
        self.assertEqual(ex("http://127.0.0.1:1/?state=x&code=ABC123&scope=y"), "ABC123")
        self.assertEqual(ex("?code=XYZ&state=s"), "XYZ")
        self.assertEqual(ex(""), "")
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
    def test_backlinks_provider_unknown_returns_none(self):
        from integrations.backlinks_api import BacklinksProvider
        self.assertIsNone(BacklinksProvider.create("notarealprovider", "k"))
        self.assertIsNone(BacklinksProvider.create("", "k"))
        # المعروف يُرجع كائناً (بدون استدعاء شبكة)
        c = BacklinksProvider.create("ahrefs", "k")
        self.assertIsNotNone(c)
        self.assertEqual(c.name, "ahrefs")

