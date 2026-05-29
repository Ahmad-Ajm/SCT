"""
integrations/ga4_api.py
=======================
موصل Google Analytics 4 (Data API) — اختياري، بلا أي مفاتيح داخل الكود.

المتطلبات (يثبّتها المستخدم عند الحاجة فقط):
    pip install google-analytics-data
ويضع اعتماد service account في ملف JSON يُشار إليه من .env/الإعدادات:
    GA4_CREDENTIALS_FILE=credentials/ga4_service_account.json
    GA4_PROPERTY_ID=123456789

نُبقيه آمناً: بدون المكتبة/الاعتماد يُرجع قوائم فارغة دون كسر التشغيل.
لا نجمع بيانات شخصية (PII) — مقاييس مجمّعة وعلى مستوى الصفحة فقط.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from utils.logger import get_logger

log = get_logger(__name__)


class GA4Client:
    def __init__(self, property_id: str, credentials_file: str = "", date_range_days: int = 90):
        self.property_id = str(property_id or "").strip()
        self.credentials_file = (credentials_file or "").strip()
        self.date_range_days = int(date_range_days or 90)
        self._client = None

    def authenticate(self, allow_interactive: bool | None = None) -> bool:
        """يصادق مع GA4.

        allow_interactive: هل يُسمح بفتح متصفّح موافقة OAuth عند غياب token صالح؟
        تمرّره اختبارات الاتصال في الواجهة بـFalse كي لا تتعلّق بانتظار الموافقة.
        """
        if not self.property_id:
            log.warning("GA4: property_id غير محدّد — تخطّي")
            return False
        try:
            from google.analytics.data_v1beta import BetaAnalyticsDataClient
        except ImportError:
            log.error("مكتبة GA4 غير مثبتة. ثبّت: pip install google-analytics-data")
            return False
        try:
            if self.credentials_file:
                from pathlib import Path as _Path

                from integrations.google_auth import load_google_credentials

                # يدعم تلقائياً حساب الخدمة أو OAuth (حساب المالك) — راجع google_auth.py
                token_path = str(
                    _Path(self.credentials_file).parent / "ga4_token.json"
                )
                creds = load_google_credentials(
                    self.credentials_file,
                    ["https://www.googleapis.com/auth/analytics.readonly"],
                    token_path,
                    allow_interactive=allow_interactive,
                )
                if not creds:
                    return False
                self._client = BetaAnalyticsDataClient(credentials=creds)
            else:
                # يعتمد على GOOGLE_APPLICATION_CREDENTIALS من البيئة إن وُجد
                self._client = BetaAnalyticsDataClient()
            log.info("تمت المصادقة مع GA4 بنجاح")
            return True
        except Exception as e:
            log.error(f"فشل المصادقة مع GA4: {e}")
            return False

    def _date_range(self):
        from google.analytics.data_v1beta.types import DateRange
        end = date.today()
        start = end - timedelta(days=self.date_range_days)
        return DateRange(start_date=start.isoformat(), end_date=end.isoformat())

    def _run(self, dimensions: list[str], metrics: list[str], limit: int = 25000):
        from google.analytics.data_v1beta.types import (
            Dimension, Metric, RunReportRequest,
        )
        req = RunReportRequest(
            property=f"properties/{self.property_id}",
            dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m) for m in metrics],
            date_ranges=[self._date_range()],
            limit=limit,
        )
        resp = self._client.run_report(req)
        rows = []
        for r in resp.rows:
            dim_vals = [v.value for v in r.dimension_values]
            met_vals = [v.value for v in r.metric_values]
            rows.append((dim_vals, met_vals))
        return rows

    def get_landing_pages(self) -> list[dict[str, Any]]:
        """أعلى صفحات الهبوط مع الجلسات/المستخدمين/التفاعل."""
        if not self._client:
            return []
        try:
            rows = self._run(
                dimensions=["landingPagePlusQueryString"],
                metrics=["sessions", "activeUsers", "engagementRate",
                         "averageSessionDuration", "screenPageViews"],
            )
        except Exception as e:
            log.error(f"GA4 landing pages error: {e}")
            return []
        out = []
        for dims, mets in rows:
            out.append({
                "path": dims[0],
                "sessions": _int(mets[0]),
                "users": _int(mets[1]),
                "engagement_rate": round(_float(mets[2]) * 100, 2),
                "avg_session_duration": round(_float(mets[3]), 1),
                "pageviews": _int(mets[4]),
            })
        log.info(f"GA4: تم جلب {len(out)} صفحة هبوط")
        return out

    def get_channels(self) -> list[dict[str, Any]]:
        """توزيع الزيارات حسب القناة (channel grouping)."""
        if not self._client:
            return []
        try:
            rows = self._run(
                dimensions=["sessionDefaultChannelGroup"],
                metrics=["sessions", "activeUsers"],
            )
        except Exception as e:
            log.error(f"GA4 channels error: {e}")
            return []
        return [
            {"channel": dims[0], "sessions": _int(mets[0]), "users": _int(mets[1])}
            for dims, mets in rows
        ]


def _int(v: Any) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _float(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0
