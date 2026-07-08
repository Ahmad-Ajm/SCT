"""
integrations/gsc_api.py
========================
تكامل Google Search Console API.

يجلب:
- Top Queries
- Top Pages
- Performance metrics (Clicks, Impressions, CTR, Position)
- Index Coverage status

المتطلبات:
1. حساب Google Cloud Console
2. تفعيل Search Console API
3. إنشاء OAuth credentials (JSON file)
4. تأكيد ملكية الموقع في GSC

سيُفعَّل بعد توفّر credentials.json
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from utils.logger import get_logger

log = get_logger(__name__)


class GSCClient:
    """
    عميل Google Search Console.

    Example:
        >>> client = GSCClient(
        ...     credentials_path="credentials/gsc.json",
        ...     site_url="https://example.com/"
        ... )
        >>> client.authenticate()
        >>> pages = client.get_top_pages(months_back=16)
        >>> queries = client.get_top_queries(months_back=16)
    """

    # نطاقات OAuth المطلوبة
    SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]

    def __init__(
        self,
        credentials_path: str,
        site_url: str,
        months_back: int = 16,
    ):
        """
        Args:
            credentials_path: مسار ملف credentials.json
            site_url: الموقع كما هو مُسجَّل في GSC
            months_back: عدد الأشهر للجلب
        """
        self.credentials_path = Path(credentials_path)
        self.site_url = site_url
        self.months_back = months_back
        self.service = None
        self._authenticated = False

    def authenticate(self, allow_interactive: bool | None = None) -> bool:
        """
        المصادقة مع Google API.

        Args:
            allow_interactive: هل يُسمح بفتح متصفّح موافقة OAuth عند غياب token صالح؟
                اختبارات الاتصال في الواجهة تمرّره False كي لا تتعلّق بانتظار الموافقة.

        Returns:
            bool: نجاح المصادقة
        """
        if not self.credentials_path.exists():
            log.error(f"ملف credentials غير موجود: {self.credentials_path}")
            return False

        try:
            from googleapiclient.discovery import build

            from integrations.google_auth import load_google_credentials

            # يدعم تلقائياً حساب الخدمة أو OAuth (راجع google_auth.py)
            token_path = self.credentials_path.parent / "gsc_token.json"
            creds = load_google_credentials(
                str(self.credentials_path), self.SCOPES, str(token_path),
                allow_interactive=allow_interactive,
            )
            if not creds:
                return False

            self.service = build("searchconsole", "v1", credentials=creds)
            self._authenticated = True
            log.info("تمت المصادقة مع Google Search Console بنجاح")
            return True

        except ImportError:
            log.error(
                "مكتبات Google غير مثبتة. ثبّت: "
                "pip install google-api-python-client google-auth-oauthlib"
            )
            return False
        except Exception as e:
            log.error(f"فشل المصادقة مع GSC: {e}")
            return False

    # v1.13.26 (L6-BUG-3): سقف افتراضي مرتفع بدل 10000 كي لا تُقتطع الخصائص الكبيرة
    # صمتاً. الـ _query يُقسّم الطلب على صفحات startRow (25000/طلب) حتى بلوغ هذا السقف.
    DEFAULT_ROW_LIMIT = 50000

    def get_top_pages(
        self, limit: int = DEFAULT_ROW_LIMIT, months_back: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """
        جلب أعلى الصفحات في GSC.

        Args:
            limit: أقصى عدد صفوف إجمالي (يُقسَّم على صفحات 25000؛ الافتراضي 50000)
            months_back: عدد الأشهر (default: من config)

        Returns:
            list[dict]: [
                {
                    "page": str,
                    "clicks": int,
                    "impressions": int,
                    "ctr": float,
                    "position": float,
                },
                ...
            ]
        """
        return self._query(
            dimensions=["page"],
            limit=limit,
            months_back=months_back or self.months_back,
        )

    def get_top_queries(
        self, limit: int = DEFAULT_ROW_LIMIT, months_back: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """جلب أعلى الكلمات المفتاحية."""
        return self._query(
            dimensions=["query"],
            limit=limit,
            months_back=months_back or self.months_back,
        )

    def get_pages_with_queries(
        self, limit: int = DEFAULT_ROW_LIMIT, months_back: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """جلب صفحات مع الكلمات المرتبطة بها."""
        return self._query(
            dimensions=["page", "query"],
            limit=limit,
            months_back=months_back or self.months_back,
        )

    def _query(
        self, dimensions: list[str], limit: int, months_back: int
    ) -> list[dict[str, Any]]:
        """تنفيذ استعلام GSC."""
        if not self._authenticated:
            log.warning("لم يتم المصادقة. استدعِ authenticate() أولاً")
            return []

        # حساب نطاق التاريخ
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=months_back * 30)

        try:
            results = []
            row_limit = 25000  # حد GSC لكل request
            start_row = 0

            while True:
                # v1.13.26 (L6-BUG-3): حجم الصفحة الفعلي = الأصغر بين حدّ GSC والمتبقّي
                # من السقف؛ نستعمله أيضاً لكشف نهاية البيانات (صفحة أقصر منه = النهاية).
                page_size = max(1, min(row_limit, limit - len(results)))
                request_body = {
                    "startDate": start_date.isoformat(),
                    "endDate": end_date.isoformat(),
                    "dimensions": dimensions,
                    "rowLimit": page_size,
                    "startRow": start_row,
                }

                response = (
                    self.service.searchanalytics()
                    .query(siteUrl=self.site_url, body=request_body)
                    .execute()
                )

                rows = response.get("rows", [])
                if not rows:
                    break

                for row in rows:
                    entry: dict[str, Any] = {}
                    for i, dim_name in enumerate(dimensions):
                        entry[dim_name] = row["keys"][i]
                    entry["clicks"] = row.get("clicks", 0)
                    entry["impressions"] = row.get("impressions", 0)
                    entry["ctr"] = round(row.get("ctr", 0) * 100, 4)
                    entry["position"] = round(row.get("position", 0), 2)
                    results.append(entry)

                # v1.13.26 (L6-BUG-3): صفحة أقصر من المطلوب = نفدت بيانات GSC.
                if len(rows) < page_size:
                    break
                # بلغنا السقف لكن الصفحة كانت ممتلئة → يُحتمَل وجود صفوف مقتطعة.
                if len(results) >= limit:
                    log.warning(
                        f"GSC: بلغنا سقف {limit} صف للأبعاد {dimensions} — "
                        f"قد تكون هناك صفوف إضافية مقتطعة (ارفع limit عند الحاجة)"
                    )
                    break

                start_row += len(rows)

            log.info(
                f"GSC: تم جلب {len(results)} صف للأبعاد {dimensions}"
            )
            return results

        except Exception as e:
            log.error(f"فشل استعلام GSC: {e}")
            return []

    def get_sitemaps_status(self) -> list[dict[str, Any]]:
        """جلب حالة Sitemaps المُرسَلة."""
        if not self._authenticated:
            return []

        try:
            response = (
                self.service.sitemaps().list(siteUrl=self.site_url).execute()
            )
            return response.get("sitemap", [])
        except Exception as e:
            log.error(f"فشل جلب Sitemaps: {e}")
            return []

    def inspect_url(self, url: str) -> dict[str, Any]:
        """حالة الفهرسة الحقيقية لرابط واحد عبر URL Inspection API (IMP-2)."""
        if not self._authenticated:
            return {"url": url, "error": "not_authenticated"}
        try:
            resp = self.service.urlInspection().index().inspect(
                body={"inspectionUrl": url, "siteUrl": self.site_url}
            ).execute()
            return parse_inspection_result(resp, url)
        except Exception as e:  # noqa: BLE001
            return {"url": url, "error": str(e)[:200]}

    def inspect_urls(self, urls: list[str], max_urls: int = 50) -> list[dict[str, Any]]:
        """فحص فهرسة عيّنة من الروابط (مع سقف لاحترام حصّة API اليومية)."""
        out: list[dict[str, Any]] = []
        for url in (urls or [])[: max(0, int(max_urls))]:
            out.append(self.inspect_url(url))
        return out


def parse_gsc_sites(resp: dict[str, Any]) -> list[dict[str, Any]]:
    """يُسطّح استجابة `sites.list` إلى صفوف {site_url, permission_level} (دالّة نقية)."""
    out: list[dict[str, Any]] = []
    for s in (resp or {}).get("siteEntry", []) or []:
        if not isinstance(s, dict):
            continue
        url = s.get("siteUrl") or ""
        if not url:
            continue
        out.append({
            "site_url": url,
            "permission_level": s.get("permissionLevel", ""),
        })
    return out


def parse_inspection_result(resp: dict[str, Any], url: str) -> dict[str, Any]:
    """يُسطّح استجابة URL Inspection إلى صف واحد (دالّة نقية قابلة للاختبار)."""
    idx = ((resp or {}).get("inspectionResult") or {}).get("indexStatusResult") or {}
    mobile = ((resp or {}).get("inspectionResult") or {}).get("mobileUsabilityResult") or {}
    rich = ((resp or {}).get("inspectionResult") or {}).get("richResultsResult") or {}
    return {
        "url": url,
        "verdict": idx.get("verdict", ""),                 # PASS / FAIL / NEUTRAL
        "coverage_state": idx.get("coverageState", ""),    # سبب الفهرسة/عدمها
        "robots_txt_state": idx.get("robotsTxtState", ""),
        "indexing_state": idx.get("indexingState", ""),
        "page_fetch_state": idx.get("pageFetchState", ""),
        "last_crawl_time": idx.get("lastCrawlTime", ""),
        "google_canonical": idx.get("googleCanonical", ""),
        "user_canonical": idx.get("userCanonical", ""),
        "mobile_verdict": mobile.get("verdict", ""),
        "rich_results_verdict": rich.get("verdict", ""),
    }
