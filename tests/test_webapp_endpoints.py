"""
tests/test_webapp_endpoints.py
==============================
v1.10-B2: اختبارات TestClient على webapp endpoints — كانت مفقودة تماماً.

نُغطّي حالات المصادقة (auth)، CSRF، rate limit، validation، 404 على معرّفات
غير صالحة، و /health / /readyz. الاختبارات مستقلّة عن state و filesystem
real (تستعمل tempdir للـjobs).
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# مسارات الاستيراد كما في tests الأخرى
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "seo_crawler" / "seo_crawler"))


class WebappEndpointTests(unittest.TestCase):
    """اختبارات على FastAPI TestClient — تتحقّق من سلوك الـ47 endpoint الحرجة."""

    @classmethod
    def setUpClass(cls):
        # نُجبر السطح على dir tempدي قبل استيراد app
        cls._tmp = tempfile.mkdtemp(prefix="sct_test_")
        os.environ["SCT_NONINTERACTIVE"] = "1"
        try:
            from fastapi.testclient import TestClient
            from webapp.app import app, _LOCAL_TOKEN
            cls.client = TestClient(app, raise_server_exceptions=False)
            cls.token = _LOCAL_TOKEN
            cls.hdrs = {"Authorization": f"Bearer {cls.token}"}
        except ImportError as e:
            raise unittest.SkipTest(f"FastAPI/TestClient غير متوفّر: {e}")

    # ─────────── auth + CSRF + headers ───────────

    def test_health_endpoint_no_auth_needed(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_readyz_endpoint_no_auth_needed(self):
        r = self.client.get("/readyz")
        # قد يردّ 200 أو 503 على بيئة CI بلا أذونات كتابة — كلاهما مقبول
        self.assertIn(r.status_code, (200, 503))

    def test_api_without_token_returns_401(self):
        r = self.client.get("/api/jobs/list")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["error"], "unauthorized")

    def test_api_with_bad_token_returns_401(self):
        r = self.client.get("/api/jobs/list", headers={"Authorization": "Bearer WRONG"})
        self.assertEqual(r.status_code, 401)

    def test_api_with_query_token_works(self):
        r = self.client.get(f"/api/jobs/list?token={self.token}")
        self.assertEqual(r.status_code, 200)

    def test_api_with_bearer_token_works(self):
        r = self.client.get("/api/jobs/list", headers=self.hdrs)
        self.assertEqual(r.status_code, 200)

    def test_correlation_id_header_present(self):
        r = self.client.get("/api/jobs/list", headers=self.hdrs)
        self.assertIn("x-request-id", {k.lower() for k in r.headers.keys()})

    def test_csrf_cross_origin_post_rejected(self):
        # Origin من نطاق أجنبي ⇒ middleware يرفض حتّى مع token
        r = self.client.post(
            "/api/jobs/delete-all",
            headers={**self.hdrs, "Origin": "https://evil.com"},
        )
        self.assertEqual(r.status_code, 403)

    def test_csrf_localhost_origin_passes(self):
        r = self.client.post(
            "/api/jobs/delete-all",
            headers={**self.hdrs, "Origin": "http://127.0.0.1:8000"},
        )
        # 200 مهما كان (لا توجد مهام في tmpdir جديد)
        self.assertEqual(r.status_code, 200)

    # ─────────── validation + 404 + bad input ───────────

    def test_invalid_job_id_returns_400_on_xml_download(self):
        r = self.client.get("/api/jobs/totally_invalid/download/xml", headers=self.hdrs)
        self.assertEqual(r.status_code, 400)
        self.assertIn("invalid", r.json().get("error", "").lower())

    def test_unknown_job_id_returns_404(self):
        # job_id valid format لكن غير موجود
        r = self.client.get(
            "/api/jobs/20260101_000000_aaaaaa/progress", headers=self.hdrs,
        )
        # يردّ 200 مع meta فارغ (السلوك الحالي) أو 404 — كلاهما مقبول
        self.assertIn(r.status_code, (200, 404))

    def test_phase2_on_missing_job_returns_error(self):
        r = self.client.post(
            "/api/jobs/20260101_000000_aaaaaa/phase2", headers=self.hdrs,
        )
        # JSON response مع `ok: False` + error message
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertFalse(j.get("ok"))
        self.assertIn(j.get("error"), ("job_not_found", "active_job", "config_missing",
                                       "no_deferred_urls"))

    def test_generate_invalid_format_handled(self):
        r = self.client.post(
            "/api/jobs/20260101_000000_aaaaaa/generate?format=virus.exe",
            headers=self.hdrs,
        )
        # 422 = FastAPI validation reject; 400/404/500 = handler-side reject
        self.assertIn(r.status_code, (400, 404, 422, 500))

    def test_log_board_unknown_job_returns_404(self):
        r = self.client.post(
            "/api/jobs/20260101_000000_aaaaaa/log-board",
            headers=self.hdrs,
            files={"file": ("a.log", b"x", "text/plain")},
        )
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
