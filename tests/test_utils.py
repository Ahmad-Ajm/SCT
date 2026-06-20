"""
tests/test_utils.py — utils/helpers + utils/monitoring + utils/auto_install + storage/cache + webapp infra.
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

from utils.helpers import (
    normalize_url,
    is_internal_url,
    is_safe_remote_url,
    matches_any_pattern,
    neutralize_formula,
    format_duration,
)


class TestUtils(unittest.TestCase):
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
    def test_auto_install_present_and_refuses_unknown(self):
        # IMP-16: المكتبة الموجودة لا تُثبَّت؛ غير المُدرَجة تُرفَض بأمان بلا تثبيت
        from utils.auto_install import ensure_package
        self.assertTrue(ensure_package("json"))  # موجودة في المكتبة القياسية
        # اسم خارج القائمة البيضاء وغير موجود ⇒ يُرفض دون محاولة تثبيت
        self.assertFalse(ensure_package("totally_made_up_pkg_xyz", auto=True))
        # مُدرَج لكن التثبيت معطّل ⇒ لا يُثبّت
        self.assertFalse(ensure_package("playwright_not_real_import", pip_name="x", auto=False))
    def test_job_delete_safely_removes_folder(self):
        # v1.01: حذف المهمة من القرص — مع رفض المهام قيد التشغيل ومعرّفات غير صالحة
        import json as _json
        sys.path.insert(0, str(ROOT / "webapp"))
        import job_runner as jr_mod
        # نوجّه JOBS_DIR إلى مجلد مؤقت كي لا نلمس بيانات حقيقية
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "webapp_jobs"; jobs_dir.mkdir()
            original = jr_mod.JOBS_DIR
            jr_mod.JOBS_DIR = jobs_dir
            try:
                runner = jr_mod.JobRunner()
                # مهمّة وهمية بمعرّف صالح
                jid = "20260530_120000_abc123"
                (jobs_dir / jid).mkdir()
                (jobs_dir / jid / "run.log").write_text("log\n", encoding="utf-8")
                (jobs_dir / jid / "meta.json").write_text(
                    _json.dumps({"job_id": jid, "status": "done"}), encoding="utf-8")
                # معرّف غير صالح ⇒ يُرفض
                self.assertFalse(runner.delete_job("../etc/passwd").get("ok"))
                self.assertFalse(runner.delete_job("not_a_valid_id").get("ok"))
                # مهمّة قيد التشغيل ⇒ يُرفض
                class _Fake:
                    def poll(self): return None  # لا يزال يعمل
                runner._procs[jid] = _Fake()
                self.assertFalse(runner.delete_job(jid).get("ok"))
                # نوقف، ثم نحذف بنجاح
                runner._procs.clear()
                self.assertTrue(runner.delete_job(jid).get("ok"))
                self.assertFalse((jobs_dir / jid).exists())
                # delete_all على مجلد فارغ يعيد قائمة فارغة
                res = runner.delete_all_jobs()
                self.assertEqual(res["deleted"], [])
            finally:
                jr_mod.JOBS_DIR = original
    def test_job_config_maps_new_ui_options(self):
        # توصيلات الواجهة: الخيارات المشحونة حديثاً تُكتب في إعداد المهمة بشكل صحيح
        import yaml as _yaml
        sys.path.insert(0, str(ROOT / "webapp"))
        from job_runner import JobRunner
        runner = JobRunner()
        with tempfile.TemporaryDirectory() as tmp:
            overrides = {
                "url": "https://x.com/",
                "platform_preset": "zid",
                "generate_sitemap": True,
                "adaptive_throttle": True,
                "integrations": {
                    "gsc": {"enabled": True, "url_inspection": True, "inspect_max_urls": 30},
                    "pagespeed": {"enabled": True, "crux_history": True},
                },
            }
            cfg_path = runner._build_job_config(Path(tmp), overrides)
            cfg = _yaml.safe_load(Path(cfg_path).read_text(encoding="utf-8"))
        self.assertEqual(cfg["site"]["platform_preset"], "zid")
        self.assertTrue(cfg["output"]["generate_sitemap"])
        self.assertTrue(cfg["crawl"]["adaptive_throttle"]["enabled"])
        self.assertTrue(cfg["integrations"]["gsc"]["url_inspection"])
        self.assertEqual(cfg["integrations"]["gsc"]["inspect_max_urls"], 30)
        self.assertTrue(cfg["integrations"]["pagespeed"]["crux_history"])
    def test_probe_token_expired_corrupt_file(self):
        """v1.06: token تالف على القرص ⇒ يُعامَل كمنتهٍ (يطالب بإعادة التفويض)."""
        import tempfile
        from webapp.app import _probe_token_expired
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("not json at all")
            tmp = f.name
        try:
            self.assertTrue(_probe_token_expired(__import__("pathlib").Path(tmp)))
        finally:
            __import__("os").unlink(tmp)
    def test_cache_key_differs_per_api_identity(self):
        """v1.09-B7: مفاتيح cache تختلف بحسب api_key — منع leak عبر share."""
        import tempfile, os
        from storage.cache import APICache
        # Windows يحتفظ بقفل DB حتّى إغلاق الاتصال — نُغلق قبل cleanup الـtempdir.
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        try:
            cache = APICache(db_path)
            k1 = cache._make_key("ps", "https://x/y", {"key": "USER_A_KEY", "u": "1"})
            k2 = cache._make_key("ps", "https://x/y", {"key": "USER_B_KEY", "u": "1"})
            self.assertNotEqual(k1, k2)
            k3 = cache._make_key("ps", "https://x/y", {"key": "USER_A_KEY", "u": "1"})
            self.assertEqual(k1, k3)
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass
    def test_ssrf_blocks_ipv4_mapped_ipv6(self):
        """v1.09-B5: bypass عبر `::ffff:127.0.0.1` مغلق الآن."""
        from utils.helpers import is_safe_remote_url
        ok, _reason = is_safe_remote_url("http://[::ffff:127.0.0.1]/x", allow_private=False)
        self.assertFalse(ok)
        # وصحيح أنّ النطاقات العامّة تمرّ
        ok2, _r = is_safe_remote_url("https://example.com/", allow_private=False)
        self.assertTrue(ok2)

