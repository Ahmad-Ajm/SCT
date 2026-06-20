"""
tests/conftest.py — sys.path setup + shared fixtures لكلّ ملفّات الاختبار.

v1.12.7 REFACTOR-tests-split: نُقلت من رأس test_core_behaviors.py.
pytest يُحمّل conftest.py تلقائياً عند جمع الاختبارات؛ في unittest نستوردها
صراحةً (`from tests.conftest import *` أو import الفئات المطلوبة).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "seo_crawler" / "seo_crawler"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


class FakeResponse:
    """استجابة HTTP وهمية لاختبار robots.txt parsing بلا شبكة."""
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
    """نموذج صفحة مبسّط للاختبارات (لا يحتاج DB أو زحف فعلي)."""
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
