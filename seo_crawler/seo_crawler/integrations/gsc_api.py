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

    def authenticate(self) -> bool:
        """
        المصادقة مع Google API.

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
                str(self.credentials_path), self.SCOPES, str(token_path)
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

    def get_top_pages(
        self, limit: int = 10000, months_back: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """
        جلب أعلى الصفحات في GSC.

        Args:
            limit: عدد النتائج (max 25000)
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
        self, limit: int = 10000, months_back: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """جلب أعلى الكلمات المفتاحية."""
        return self._query(
            dimensions=["query"],
            limit=limit,
            months_back=months_back or self.months_back,
        )

    def get_pages_with_queries(
        self, limit: int = 10000, months_back: Optional[int] = None
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
                request_body = {
                    "startDate": start_date.isoformat(),
                    "endDate": end_date.isoformat(),
                    "dimensions": dimensions,
                    "rowLimit": min(row_limit, limit - len(results)),
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

                # هل نحتاج المزيد؟
                if len(rows) < row_limit or len(results) >= limit:
                    break

                start_row += row_limit

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
