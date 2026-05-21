"""
storage/cache.py
=================
نظام Cache للـ APIs (PageSpeed, GSC, etc.).

يستخدم SQLite لحفظ النتائج لفترة TTL محددة.

المزايا:
- توفير quota الـ APIs (PageSpeed: 25K/يوم)
- سرعة في إعادة الزحف
- مقارنة قبل/بعد دقيقة (نفس الـ data)
- يمكن مشاركة الـ cache بين مشاريع
"""

import hashlib
import json
import sqlite3
import threading
import time
# datetime imports removed - unused
from pathlib import Path
from typing import Any, Optional

from utils.logger import get_logger

log = get_logger(__name__)


CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_cache (
    cache_key TEXT PRIMARY KEY,
    api_name TEXT NOT NULL,
    request_url TEXT,
    request_params TEXT,  -- JSON
    response_data TEXT NOT NULL,  -- JSON
    cached_at REAL NOT NULL,  -- Unix timestamp
    expires_at REAL NOT NULL,
    hit_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cache_api ON api_cache(api_name);
CREATE INDEX IF NOT EXISTS idx_cache_expires ON api_cache(expires_at);
"""


class APICache:
    """
    Cache لاستجابات APIs.

    Example:
        >>> cache = APICache("./state/api_cache.db", default_ttl_days=7)
        >>>
        >>> # محاولة الجلب من cache
        >>> cached = cache.get("pagespeed", "https://example.com", {"strategy": "mobile"})
        >>> if cached:
        ...     return cached
        >>>
        >>> # إذا غير موجود، اطلب من API
        >>> result = make_api_request(...)
        >>> cache.set("pagespeed", "https://example.com", {"strategy": "mobile"}, result)
    """

    def __init__(
        self,
        db_path: str,
        default_ttl_days: int = 7,
        max_size_mb: int = 500,
    ):
        """
        Args:
            db_path: مسار قاعدة بيانات الـ cache
            default_ttl_days: مدة صلاحية الـ cache بالأيام
            max_size_mb: الحد الأقصى لحجم الـ cache
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.default_ttl_seconds = default_ttl_days * 86400
        self.max_size_mb = max_size_mb

        self._local = threading.local()
        self._initialize()

    def _initialize(self) -> None:
        with self._get_connection() as conn:
            conn.executescript(CACHE_SCHEMA)
            conn.execute("PRAGMA journal_mode = WAL")

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                timeout=10.0,
                check_same_thread=False,
            )
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _make_key(
        self, api_name: str, request_url: str, params: dict[str, Any]
    ) -> str:
        """إنشاء مفتاح فريد للـ cache."""
        # ترتيب params لضمان نفس المفتاح بغض النظر عن الترتيب
        params_str = json.dumps(params, sort_keys=True, ensure_ascii=False)
        raw = f"{api_name}|{request_url}|{params_str}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(
        self,
        api_name: str,
        request_url: str,
        params: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        """
        محاولة جلب نتيجة من الـ cache.

        Returns:
            dict أو None (إذا غير موجود أو منتهي الصلاحية)
        """
        params = params or {}
        key = self._make_key(api_name, request_url, params)
        now = time.time()

        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    """SELECT response_data, expires_at FROM api_cache
                       WHERE cache_key = ?""",
                    (key,),
                ).fetchone()

                if not row:
                    return None

                # التحقق من الصلاحية
                if row["expires_at"] < now:
                    log.debug(f"Cache expired: {api_name}/{request_url[:60]}")
                    return None

                # زيادة عداد الـ hits
                conn.execute(
                    "UPDATE api_cache SET hit_count = hit_count + 1 WHERE cache_key = ?",
                    (key,),
                )
                conn.commit()

                log.debug(f"Cache HIT: {api_name}/{request_url[:60]}")
                return json.loads(row["response_data"])

        except (sqlite3.Error, json.JSONDecodeError) as e:
            log.warning(f"خطأ في قراءة cache: {e}")
            return None

    def set(
        self,
        api_name: str,
        request_url: str,
        params: dict[str, Any],
        response_data: Any,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """
        حفظ نتيجة في الـ cache.

        Args:
            api_name: اسم API (pagespeed, gsc, etc.)
            request_url: الرابط المطلوب
            params: parameters الطلب
            response_data: البيانات للحفظ (سيتم تحويلها لـ JSON)
            ttl_seconds: مدة الصلاحية (override default)
        """
        key = self._make_key(api_name, request_url, params)
        now = time.time()
        ttl = ttl_seconds or self.default_ttl_seconds
        expires_at = now + ttl

        try:
            with self._get_connection() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO api_cache
                       (cache_key, api_name, request_url, request_params,
                        response_data, cached_at, expires_at, hit_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                    (
                        key,
                        api_name,
                        request_url,
                        json.dumps(params, ensure_ascii=False),
                        json.dumps(response_data, ensure_ascii=False, default=str),
                        now,
                        expires_at,
                    ),
                )
                conn.commit()

                log.debug(f"Cache SET: {api_name}/{request_url[:60]} (TTL: {ttl/86400:.1f} days)")

        except (sqlite3.Error, TypeError) as e:
            log.warning(f"خطأ في حفظ cache: {e}")

    def invalidate(
        self,
        api_name: Optional[str] = None,
        request_url: Optional[str] = None,
    ) -> int:
        """
        إبطال (حذف) entries من الـ cache.

        Args:
            api_name: حذف كل entries لـ API معين
            request_url: حذف entry محدد

        Returns:
            int: عدد الـ entries المحذوفة
        """
        try:
            with self._get_connection() as conn:
                if request_url and api_name:
                    cursor = conn.execute(
                        "DELETE FROM api_cache WHERE api_name = ? AND request_url = ?",
                        (api_name, request_url),
                    )
                elif api_name:
                    cursor = conn.execute(
                        "DELETE FROM api_cache WHERE api_name = ?", (api_name,)
                    )
                else:
                    cursor = conn.execute("DELETE FROM api_cache")

                conn.commit()
                deleted = cursor.rowcount
                log.info(f"تم حذف {deleted} cache entry")
                return deleted
        except sqlite3.Error as e:
            log.error(f"خطأ في invalidate: {e}")
            return 0

    def cleanup_expired(self) -> int:
        """حذف entries منتهية الصلاحية."""
        try:
            now = time.time()
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM api_cache WHERE expires_at < ?", (now,)
                )
                conn.commit()
                deleted = cursor.rowcount
                if deleted > 0:
                    log.info(f"تم حذف {deleted} cache entry منتهي الصلاحية")
                return deleted
        except sqlite3.Error:
            return 0

    def get_stats(self) -> dict[str, Any]:
        """إحصائيات الـ cache."""
        try:
            with self._get_connection() as conn:
                total = conn.execute("SELECT COUNT(*) FROM api_cache").fetchone()[0]

                now = time.time()
                expired = conn.execute(
                    "SELECT COUNT(*) FROM api_cache WHERE expires_at < ?", (now,)
                ).fetchone()[0]

                by_api = conn.execute(
                    """SELECT api_name, COUNT(*) as cnt, SUM(hit_count) as hits
                       FROM api_cache GROUP BY api_name"""
                ).fetchall()

                # حجم الـ DB
                db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

                return {
                    "total_entries": total,
                    "expired_entries": expired,
                    "valid_entries": total - expired,
                    "by_api": {row["api_name"]: {
                        "count": row["cnt"],
                        "hits": row["hits"] or 0,
                    } for row in by_api},
                    "db_size_bytes": db_size,
                    "db_size_mb": round(db_size / (1024 * 1024), 2),
                }
        except sqlite3.Error:
            return {}

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None
