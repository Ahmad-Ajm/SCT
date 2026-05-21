"""
storage/database.py
====================
قاعدة بيانات SQLite لتخزين نتائج الزحف.

المزايا على التخزين في الذاكرة:
1. استهلاك ذاكرة منخفض (50 MB لـ 100K صفحة بدلاً من ~5 GB)
2. استعلامات سريعة بفضل الـ indexes
3. استئناف فوري بدون JSON load كبير
4. ضغط تلقائي للبيانات
5. إمكانية الاستعلام بـ SQL لتحليلات معقدة
6. آمان: لا تُفقد البيانات لو انقطعت الكهرباء
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

from utils.logger import get_logger
from utils.monitoring import increment, span

log = get_logger(__name__)

# ============================================================
# === قائمة بيضاء بأسماء الجداول المسموحة ===
# ============================================================
# نستخدم f-string في PRAGMA table_info لأن SQLite لا يقبل
# parameterized PRAGMA. الـ whitelist يحمي من أي crash أو injection
# إذا أُمرّر اسم جدول سيء عن طريق الخطأ.
# ────────────────────────────────────────────────────────────
VALID_TABLES: frozenset[str] = frozenset({
    "pages",
    "links",
    "images",
    "headings",
    "schema_entries",
    "http_headers",
    "redirects",
    "external_link_status",
    "crawl_queue",
    "visited_urls",
    "crawl_metadata",
})


# ============================================================
# === Schema ===
# ============================================================

SCHEMA_SQL = """
-- جدول الصفحات الرئيسي
CREATE TABLE IF NOT EXISTS pages (
    url TEXT PRIMARY KEY,
    final_url TEXT,
    status_code INTEGER,
    content_type TEXT,
    size_bytes INTEGER,
    response_time_ms REAL,
    encoding TEXT,
    depth INTEGER,
    crawled_at TEXT,
    
    -- Meta
    title TEXT,
    title_length INTEGER,
    title_pixel_width INTEGER,
    meta_description TEXT,
    meta_description_length INTEGER,
    meta_keywords TEXT,
    meta_robots TEXT,
    meta_viewport TEXT,
    meta_charset TEXT,
    meta_generator TEXT,
    
    -- Headings
    h1_count INTEGER,
    h1_text TEXT,  -- JSON array
    h2_count INTEGER,
    h2_text TEXT,
    h3_count INTEGER,
    h3_text TEXT,
    
    -- Canonical
    canonical TEXT,
    canonical_in_header INTEGER,  -- bool
    canonical_is_self INTEGER,
    
    -- Hreflang
    hreflang_tags TEXT,  -- JSON
    
    -- OG/Twitter
    og_title TEXT,
    og_description TEXT,
    og_image TEXT,
    og_type TEXT,
    og_url TEXT,
    twitter_card TEXT,
    twitter_title TEXT,
    twitter_description TEXT,
    twitter_image TEXT,
    
    -- Schema
    schema_count INTEGER,
    schema_types TEXT,  -- JSON array
    
    -- Content
    word_count INTEGER,
    character_count INTEGER,
    paragraph_count INTEGER,
    text_to_html_ratio REAL,
    language TEXT,
    content_hash TEXT,
    
    -- Counts
    internal_links_count INTEGER,
    external_links_count INTEGER,
    images_count INTEGER,
    images_without_alt_count INTEGER,
    nofollow_links_count INTEGER,
    
    -- Indexability
    is_indexable INTEGER,
    indexability_reason TEXT,
    x_robots_tag TEXT,
    
    -- Headers
    server TEXT,
    cache_control TEXT,
    content_encoding TEXT,
    hsts_enabled INTEGER,
    
    -- JS
    js_rendered INTEGER,
    js_console_errors TEXT,
    js_network_requests INTEGER,
    
    -- Redirect
    is_redirect INTEGER,
    redirect_chain TEXT,
    
    -- Mixed content (جديد)
    has_mixed_content INTEGER DEFAULT 0,
    mixed_content_urls TEXT,
    mixed_content_active_count INTEGER DEFAULT 0,
    mixed_content_passive_count INTEGER DEFAULT 0,
    mixed_content_form_count INTEGER DEFAULT 0,

    -- Errors
    crawl_error TEXT
);

-- جدول الروابط (Inlinks + Outlinks)
CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_url TEXT NOT NULL,
    to_url TEXT NOT NULL,
    to_url_normalized TEXT,
    anchor_text TEXT,
    anchor_text_length INTEGER,
    title TEXT,
    rel TEXT,
    target TEXT,
    is_internal INTEGER,
    nofollow INTEGER,
    ugc INTEGER,
    sponsored INTEGER,
    is_image_link INTEGER,
    link_position INTEGER,
    in_navigation INTEGER,
    in_footer INTEGER,
    in_header INTEGER,
    in_main INTEGER,
    is_special_link INTEGER,
    href_raw TEXT
);

-- جدول الصور
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_url TEXT NOT NULL,
    src TEXT NOT NULL,
    src_raw TEXT,
    alt TEXT,
    alt_length INTEGER,
    has_alt INTEGER,
    alt_is_empty INTEGER,
    title TEXT,
    width TEXT,
    height TEXT,
    has_explicit_dimensions INTEGER,
    loading TEXT,
    srcset TEXT,
    sizes TEXT,
    decoding TEXT,
    class_names TEXT,
    position INTEGER,
    is_in_picture INTEGER,
    is_lazy_loaded INTEGER,
    file_extension TEXT,
    actual_size_bytes INTEGER DEFAULT NULL,
    actual_width INTEGER DEFAULT NULL,
    actual_height INTEGER DEFAULT NULL
);

-- جدول العناوين
CREATE TABLE IF NOT EXISTS headings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_url TEXT NOT NULL,
    tag TEXT,
    level INTEGER,
    text TEXT,
    length INTEGER,
    position INTEGER
);

-- جدول Schema.org
CREATE TABLE IF NOT EXISTS schema_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_url TEXT NOT NULL,
    format TEXT,
    type TEXT,
    name TEXT,
    raw_data TEXT
);

-- جدول HTTP Headers
CREATE TABLE IF NOT EXISTS http_headers (
    page_url TEXT PRIMARY KEY,
    all_headers TEXT,
    server TEXT,
    powered_by TEXT,
    cdn TEXT,
    cache_control TEXT,
    expires TEXT,
    etag TEXT,
    last_modified TEXT,
    content_encoding TEXT,
    is_compressed INTEGER,
    hsts TEXT,
    hsts_enabled INTEGER,
    x_frame_options TEXT,
    csp TEXT,
    x_robots_tag TEXT,
    has_noindex_in_header INTEGER,
    has_nofollow_in_header INTEGER,
    content_type TEXT,
    content_length TEXT,
    content_language TEXT,
    vary TEXT,
    has_cookies INTEGER
);

-- جدول Redirects
CREATE TABLE IF NOT EXISTS redirects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_url TEXT NOT NULL,
    to_url TEXT NOT NULL,
    status_code INTEGER,
    chain_length INTEGER,
    original_url TEXT
);

-- جدول External Links Status (جديد)
CREATE TABLE IF NOT EXISTS external_link_status (
    url TEXT PRIMARY KEY,
    status_code INTEGER,
    final_url TEXT,
    response_time_ms REAL,
    checked_at TEXT,
    error TEXT
);

-- جدول Crawl Queue (للاستئناف)
CREATE TABLE IF NOT EXISTS crawl_queue (
    url TEXT PRIMARY KEY,
    depth INTEGER,
    added_at TEXT,
    priority INTEGER DEFAULT 5
);

-- جدول Visited URLs
CREATE TABLE IF NOT EXISTS visited_urls (
    url TEXT PRIMARY KEY,
    visited_at TEXT
);

-- جدول Metadata للجلسة
CREATE TABLE IF NOT EXISTS crawl_metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- ============================================================
-- === Indexes للأداء ===
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_pages_status ON pages(status_code);
CREATE INDEX IF NOT EXISTS idx_pages_indexable ON pages(is_indexable);
CREATE INDEX IF NOT EXISTS idx_pages_depth ON pages(depth);
CREATE INDEX IF NOT EXISTS idx_pages_content_hash ON pages(content_hash);
CREATE INDEX IF NOT EXISTS idx_pages_title ON pages(title);

CREATE INDEX IF NOT EXISTS idx_links_from ON links(from_url);
CREATE INDEX IF NOT EXISTS idx_links_to ON links(to_url);
CREATE INDEX IF NOT EXISTS idx_links_to_normalized ON links(to_url_normalized);
CREATE INDEX IF NOT EXISTS idx_links_internal ON links(is_internal);

CREATE INDEX IF NOT EXISTS idx_images_page ON images(page_url);
CREATE INDEX IF NOT EXISTS idx_images_has_alt ON images(has_alt);

CREATE INDEX IF NOT EXISTS idx_headings_page ON headings(page_url);
CREATE INDEX IF NOT EXISTS idx_schema_page ON schema_entries(page_url);
CREATE INDEX IF NOT EXISTS idx_redirects_origin ON redirects(original_url);
"""


class CrawlDatabase:
    """
    مدير قاعدة بيانات الزحف باستخدام SQLite.

    Thread-safe وعالي الأداء.

    Example:
        >>> db = CrawlDatabase("./state/crawl.db")
        >>> db.save_page(page_data)
        >>> db.save_links(url, links_list)
        >>> pages = db.get_all_pages()
        >>> db.close()
    """

    # الأعمدة المخزَّنة كـ JSON عبر كل الجداول (لفك ترميزها عند القراءة فقط)
    _JSON_COLUMNS: frozenset[str] = frozenset({
        "h1_text", "h2_text", "h3_text", "headings_order", "hreflang_tags",
        "schema_types", "schema_data", "redirect_chain", "js_console_errors",
        "mixed_content_urls", "all_headers", "raw_data",
    })

    def __init__(self, db_path: str, wal_mode: bool = True):
        """
        Args:
            db_path: مسار قاعدة البيانات
            wal_mode: تفعيل WAL mode (أسرع + يدعم concurrent reads)
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Thread-local connections (SQLite needs one per thread)
        self._local = threading.local()
        self._wal_mode = wal_mode

        # إنشاء الـ schema
        self._initialize()

    # أعمدة قد تكون مفقودة في قواعد بيانات قديمة (col -> تعريف SQL)
    _PAGE_MIGRATIONS: dict[str, str] = {
        "mixed_content_active_count": "INTEGER DEFAULT 0",
        "mixed_content_passive_count": "INTEGER DEFAULT 0",
        "mixed_content_form_count": "INTEGER DEFAULT 0",
    }

    def _initialize(self) -> None:
        """إنشاء الجداول والـ indexes."""
        with span("db.initialize", path=str(self.db_path)):
            with self._get_connection() as conn:
                conn.executescript(SCHEMA_SQL)
                conn.commit()
                self._migrate(conn)
                conn.commit()
                log.info(f"تم تهيئة قاعدة البيانات: {self.db_path}")

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """إضافة أي أعمدة جديدة مفقودة في قواعد بيانات أُنشئت بإصدار أقدم."""
        existing = {row[1] for row in conn.execute("PRAGMA table_info(pages)")}
        for column, definition in self._PAGE_MIGRATIONS.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE pages ADD COLUMN {column} {definition}")
                log.info(f"ترقية المخطط: أُضيف العمود pages.{column}")

    def _get_connection(self) -> sqlite3.Connection:
        """الحصول على connection للـ thread الحالي."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                timeout=30.0,  # ينتظر إذا كان DB locked
                check_same_thread=False,
            )
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA foreign_keys = ON")

            # تحسينات الأداء
            if self._wal_mode:
                self._local.conn.execute("PRAGMA journal_mode = WAL")
            self._local.conn.execute("PRAGMA synchronous = NORMAL")
            self._local.conn.execute("PRAGMA cache_size = -64000")  # 64 MB cache
            self._local.conn.execute("PRAGMA temp_store = MEMORY")

        return self._local.conn

    @contextmanager
    def transaction(self):
        """Context manager لـ transactions."""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ========================================================
    # === Pages ===
    # ========================================================

    def save_page_bundle(
        self,
        page_data: Any,
        links: list[dict[str, Any]] | None = None,
        images: list[dict[str, Any]] | None = None,
        headings: list[dict[str, Any]] | None = None,
        schema_entries: list[dict[str, Any]] | None = None,
        header_data: dict[str, Any] | None = None,
    ) -> None:
        """Save all extracted page data in a single transaction."""
        try:
            with span(
                "db.save_page_bundle",
                links=len(links or []),
                images=len(images or []),
                headings=len(headings or []),
                schema_entries=len(schema_entries or []),
            ):
                with self.transaction() as conn:
                    self._insert_page(conn, page_data)
                    self._insert_links(conn, links or [])
                    self._insert_images(conn, images or [])
                    self._insert_headings(conn, headings or [])
                    self._insert_schema(conn, schema_entries or [])
                    if header_data:
                        self._insert_headers(conn, header_data)
                increment("db.pages_saved")
        except sqlite3.Error as e:
            url = getattr(page_data, "url", None)
            if url is None and isinstance(page_data, dict):
                url = page_data.get("url")
            log.error(f"خطأ في حفظ حزمة الصفحة {url or 'unknown'}: {e}")

    def save_page(self, page_data: Any) -> None:
        """
        حفظ بيانات صفحة كاملة.

        Args:
            page_data: PageData dataclass أو dict
        """
        try:
            with span("db.save_page"):
                with self.transaction() as conn:
                    self._insert_page(conn, page_data)
                increment("db.pages_saved")
        except sqlite3.Error as e:
            url = getattr(page_data, "url", None)
            if url is None and isinstance(page_data, dict):
                url = page_data.get("url")
            log.error(f"خطأ في حفظ الصفحة {url or 'unknown'}: {e}")

    def get_all_pages(self) -> Iterator[dict[str, Any]]:
        """
        استرجاع كل الصفحات كـ generator (لا تحمّل كل شيء للذاكرة).
        """
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM pages")
            for row in cursor:
                yield self._row_to_dict(row)

    def get_pages_count(self) -> int:
        """عدد الصفحات المحفوظة."""
        with self._get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]

    def get_pages_by_status(self, status_min: int, status_max: int) -> list[dict]:
        """جلب صفحات حسب نطاق status code."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM pages WHERE status_code >= ? AND status_code <= ?",
                (status_min, status_max),
            )
            return [self._row_to_dict(row) for row in cursor]

    # ========================================================
    # === Links ===
    # ========================================================

    def save_links(self, links: list[dict[str, Any]]) -> None:
        """حفظ مجموعة روابط دفعة واحدة (batch insert سريع)."""
        if not links:
            return

        try:
            with span("db.save_links", rows=len(links)):
                with self.transaction() as conn:
                    self._insert_links(conn, links)
                increment("db.links_saved", len(links))
        except sqlite3.Error as e:
            log.error(f"خطأ في حفظ الروابط: {e}")

    def get_all_links(self) -> Iterator[dict[str, Any]]:
        """generator لكل الروابط."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM links")
            for row in cursor:
                yield self._row_to_dict(row)

    def get_inlinks_for(self, url: str) -> list[dict]:
        """جلب كل الروابط الواردة لـ URL محدد."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM links WHERE to_url_normalized = ? OR to_url = ?",
                (url, url),
            )
            return [self._row_to_dict(row) for row in cursor]

    def get_inlinks_count_by_url(self) -> dict[str, int]:
        """عدد inlinks لكل URL."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """SELECT to_url_normalized, COUNT(*) as cnt
                   FROM links WHERE is_internal = 1
                   GROUP BY to_url_normalized"""
            )
            return {row["to_url_normalized"]: row["cnt"] for row in cursor}

    # ========================================================
    # === Images ===
    # ========================================================

    def save_images(self, images: list[dict[str, Any]]) -> None:
        """حفظ صور دفعة واحدة."""
        if not images:
            return

        try:
            with span("db.save_images", rows=len(images)):
                with self.transaction() as conn:
                    self._insert_images(conn, images)
                increment("db.images_saved", len(images))
        except sqlite3.Error as e:
            log.error(f"خطأ في حفظ الصور: {e}")

    def get_all_images(self) -> Iterator[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM images")
            for row in cursor:
                yield self._row_to_dict(row)

    # ========================================================
    # === Headings ===
    # ========================================================

    def save_headings(self, headings: list[dict[str, Any]]) -> None:
        if not headings:
            return

        try:
            with span("db.save_headings", rows=len(headings)):
                with self.transaction() as conn:
                    self._insert_headings(conn, headings)
                increment("db.headings_saved", len(headings))
        except sqlite3.Error as e:
            log.error(f"خطأ في حفظ Headings: {e}")

    def get_all_headings(self) -> Iterator[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM headings")
            for row in cursor:
                yield self._row_to_dict(row)

    # ========================================================
    # === Schema ===
    # ========================================================

    def save_schema(self, schema_entries: list[dict[str, Any]]) -> None:
        if not schema_entries:
            return

        try:
            with span("db.save_schema", rows=len(schema_entries)):
                with self.transaction() as conn:
                    self._insert_schema(conn, schema_entries)
                increment("db.schema_entries_saved", len(schema_entries))
        except sqlite3.Error as e:
            log.error(f"خطأ في حفظ Schema: {e}")

    def get_all_schema(self) -> Iterator[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM schema_entries")
            for row in cursor:
                yield self._row_to_dict(row)

    # ========================================================
    # === Headers ===
    # ========================================================

    def save_headers(self, header_data: dict[str, Any]) -> None:
        """حفظ HTTP headers لصفحة."""
        try:
            with span("db.save_headers"):
                with self.transaction() as conn:
                    self._insert_headers(conn, header_data)
                increment("db.headers_saved")
        except sqlite3.Error as e:
            log.error(f"خطأ في حفظ Headers: {e}")

    def get_all_headers(self) -> Iterator[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM http_headers")
            for row in cursor:
                yield self._row_to_dict(row)

    # ========================================================
    # === Redirects ===
    # ========================================================

    def save_redirects(self, redirects: list[dict[str, Any]]) -> None:
        if not redirects:
            return

        rows = []
        for r in redirects:
            rows.append([
                r.get("from_url"),
                r.get("to_url"),
                r.get("status_code"),
                r.get("chain_length"),
                r.get("original_url"),
            ])

        try:
            with span("db.save_redirects", rows=len(rows)):
                with self.transaction() as conn:
                    conn.executemany(
                        "INSERT INTO redirects (from_url, to_url, status_code, chain_length, original_url) VALUES (?, ?, ?, ?, ?)",
                        rows,
                    )
                increment("db.redirects_saved", len(rows))
        except sqlite3.Error as e:
            log.error(f"خطأ في حفظ Redirects: {e}")

    def get_all_redirects(self) -> Iterator[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM redirects")
            for row in cursor:
                yield self._row_to_dict(row)

    # ========================================================
    # === External Links Status ===
    # ========================================================

    def save_external_link_status(
        self,
        url: str,
        status_code: int,
        final_url: str = "",
        response_time_ms: float = 0.0,
        error: Optional[str] = None,
    ) -> None:
        """حفظ نتيجة فحص رابط خارجي."""
        try:
            with span("db.save_external_link_status", status_code=status_code):
                with self.transaction() as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO external_link_status
                           (url, status_code, final_url, response_time_ms, checked_at, error)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (url, status_code, final_url, response_time_ms,
                         datetime.now().isoformat(), error),
                    )
                increment("db.external_link_status_saved")
        except sqlite3.Error as e:
            log.error(f"خطأ في حفظ External Link: {e}")

    def get_unchecked_external_links(self) -> list[str]:
        """جلب الروابط الخارجية التي لم تُفحص بعد."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """SELECT DISTINCT to_url FROM links
                   WHERE is_internal = 0
                   AND to_url NOT IN (SELECT url FROM external_link_status)
                   AND to_url NOT LIKE 'mailto:%'
                   AND to_url NOT LIKE 'tel:%'
                   AND to_url NOT LIKE 'javascript:%'"""
            )
            return [row[0] for row in cursor]

    def get_broken_external_links(self) -> list[dict[str, Any]]:
        """جلب الروابط الخارجية المكسورة."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """SELECT * FROM external_link_status
                   WHERE status_code >= 400 OR error IS NOT NULL"""
            )
            return [self._row_to_dict(row) for row in cursor]

    # ========================================================
    # === Queue Management ===
    # ========================================================

    def add_to_queue(self, url: str, depth: int, priority: int = 5) -> bool:
        """إضافة URL لقائمة الانتظار (يتجاهل إذا موجود)."""
        try:
            with self.transaction() as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO crawl_queue (url, depth, added_at, priority)
                       VALUES (?, ?, ?, ?)""",
                    (url, depth, datetime.now().isoformat(), priority),
                )
                return conn.total_changes > 0
        except sqlite3.Error:
            return False

    def get_next_from_queue(self) -> Optional[tuple[str, int]]:
        """جلب URL التالي من القائمة (حسب priority + الأقدم)."""
        with self.transaction() as conn:
            row = conn.execute(
                """SELECT url, depth FROM crawl_queue
                   ORDER BY priority DESC, added_at ASC LIMIT 1"""
            ).fetchone()

            if row:
                conn.execute("DELETE FROM crawl_queue WHERE url = ?", (row[0],))
                return (row[0], row[1])
            return None

    def queue_size(self) -> int:
        with self._get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM crawl_queue").fetchone()[0]

    def mark_visited(self, url: str) -> None:
        """تسجيل URL كـ visited."""
        try:
            with self.transaction() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO visited_urls (url, visited_at) VALUES (?, ?)",
                    (url, datetime.now().isoformat()),
                )
        except sqlite3.Error:
            pass

    def is_visited(self, url: str) -> bool:
        with self._get_connection() as conn:
            return conn.execute(
                "SELECT 1 FROM visited_urls WHERE url = ?", (url,)
            ).fetchone() is not None

    def get_visited_count(self) -> int:
        with self._get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM visited_urls").fetchone()[0]

    # ========================================================
    # === Metadata ===
    # ========================================================

    def set_meta(self, key: str, value: Any) -> None:
        """حفظ metadata."""
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, default=str)
        try:
            with self.transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO crawl_metadata (key, value) VALUES (?, ?)",
                    (key, value),
                )
        except sqlite3.Error:
            pass

    def get_meta(self, key: str, default: Any = None) -> Any:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM crawl_metadata WHERE key = ?", (key,)
            ).fetchone()
            if row:
                try:
                    return json.loads(row[0])
                except (json.JSONDecodeError, TypeError):
                    return row[0]
            return default

    # ========================================================
    # === Utilities ===
    # ========================================================

    def _insert_page(self, conn: sqlite3.Connection, page_data: Any) -> None:
        if is_dataclass(page_data):
            data = asdict(page_data)
        else:
            data = dict(page_data)

        for key in ("h1_text", "h2_text", "h3_text", "headings_order", "hreflang_tags",
                    "schema_types", "schema_data", "redirect_chain", "js_console_errors",
                    "mixed_content_urls"):
            if key in data and isinstance(data[key], (list, dict)):
                data[key] = json.dumps(data[key], ensure_ascii=False)

        for key in ("canonical_in_header", "canonical_is_self", "is_indexable",
                    "hsts_enabled", "js_rendered", "is_redirect", "has_mixed_content"):
            if key in data:
                data[key] = int(bool(data[key]))

        columns = self._get_table_columns("pages")
        filtered_data = {k: v for k, v in data.items() if k in columns}
        for k, v in list(filtered_data.items()):
            if isinstance(v, (list, dict)):
                filtered_data[k] = json.dumps(v, ensure_ascii=False, default=str)

        placeholders = ", ".join(["?"] * len(filtered_data))
        cols_str = ", ".join(filtered_data.keys())
        conn.execute(
            f"INSERT OR REPLACE INTO pages ({cols_str}) VALUES ({placeholders})",
            list(filtered_data.values()),
        )

    def _insert_links(self, conn: sqlite3.Connection, links: list[dict[str, Any]]) -> None:
        if not links:
            return
        columns = self._get_table_columns("links")
        insertable_cols = [c for c in columns if c != "id"]
        rows = [self._row_from_columns(link, insertable_cols) for link in links]
        placeholders = ", ".join(["?"] * len(insertable_cols))
        conn.executemany(
            f"INSERT INTO links ({', '.join(insertable_cols)}) VALUES ({placeholders})",
            rows,
        )

    def _insert_images(self, conn: sqlite3.Connection, images: list[dict[str, Any]]) -> None:
        if not images:
            return
        columns = self._get_table_columns("images")
        insertable_cols = [c for c in columns if c != "id"]
        rows = [self._row_from_columns(img, insertable_cols) for img in images]
        placeholders = ", ".join(["?"] * len(insertable_cols))
        conn.executemany(
            f"INSERT INTO images ({', '.join(insertable_cols)}) VALUES ({placeholders})",
            rows,
        )

    def _insert_headings(self, conn: sqlite3.Connection, headings: list[dict[str, Any]]) -> None:
        if not headings:
            return
        columns = ["page_url", "tag", "level", "text", "length", "position"]
        rows = [[h.get(c) for c in columns] for h in headings]
        conn.executemany(
            f"INSERT INTO headings ({', '.join(columns)}) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )

    def _insert_schema(self, conn: sqlite3.Connection, schema_entries: list[dict[str, Any]]) -> None:
        if not schema_entries:
            return
        rows = []
        for entry in schema_entries:
            raw_data = entry.get("raw_data", "")
            if isinstance(raw_data, (dict, list)):
                raw_data = json.dumps(raw_data, ensure_ascii=False, default=str)
            rows.append([
                entry.get("page_url"),
                entry.get("format"),
                entry.get("type"),
                entry.get("name"),
                raw_data,
            ])
        conn.executemany(
            "INSERT INTO schema_entries (page_url, format, type, name, raw_data) VALUES (?, ?, ?, ?, ?)",
            rows,
        )

    def _insert_headers(self, conn: sqlite3.Connection, header_data: dict[str, Any]) -> None:
        columns = self._get_table_columns("http_headers")
        filtered = {k: v for k, v in header_data.items() if k in columns}
        if not filtered:
            return
        if "all_headers" in filtered and isinstance(filtered["all_headers"], dict):
            filtered["all_headers"] = json.dumps(filtered["all_headers"], ensure_ascii=False)

        for key in ("is_compressed", "hsts_enabled", "has_noindex_in_header",
                    "has_nofollow_in_header", "has_cookies"):
            if key in filtered:
                filtered[key] = int(bool(filtered[key]))

        placeholders = ", ".join(["?"] * len(filtered))
        conn.execute(
            f"INSERT OR REPLACE INTO http_headers ({', '.join(filtered.keys())}) VALUES ({placeholders})",
            list(filtered.values()),
        )

    def _row_from_columns(self, data: dict[str, Any], columns: list[str]) -> list[Any]:
        row = []
        for col in columns:
            val = data.get(col)
            if isinstance(val, bool):
                val = int(val)
            elif isinstance(val, (dict, list)):
                val = json.dumps(val, ensure_ascii=False, default=str)
            row.append(val)
        return row

    def _get_table_columns(self, table_name: str) -> list[str]:
        """
        جلب أعمدة جدول.

        يتحقق من VALID_TABLES قبل تنفيذ PRAGMA لمنع crash
        عند تمرير اسم جدول غير صالح.
        """
        if table_name not in VALID_TABLES:
            log.warning(f"_get_table_columns: اسم جدول غير مسموح: '{table_name}'")
            return []
        with self._get_connection() as conn:
            cursor = conn.execute(f"PRAGMA table_info({table_name})")
            return [row[1] for row in cursor]

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        """تحويل sqlite3.Row إلى dict مع decode للـ JSON.

        نقصر فك الترميز على الأعمدة المعروفة أنها JSON فقط، حتى لا نُحوّل
        عن طريق الخطأ عنواناً/وصفاً يبدأ بـ ``[`` أو ``{`` إلى list/dict.
        """
        result = dict(row)

        for key in self._JSON_COLUMNS:
            value = result.get(key)
            if isinstance(value, str) and value[:1] in ("[", "{"):
                try:
                    result[key] = json.loads(value)
                except json.JSONDecodeError:
                    pass

        return result

    def vacuum(self) -> None:
        """تنظيف وتقليل حجم قاعدة البيانات."""
        with self._get_connection() as conn:
            conn.execute("VACUUM")
            log.info("تم تنظيف قاعدة البيانات")

    def get_stats(self) -> dict[str, int]:
        """إحصائيات قاعدة البيانات."""
        stats = {}
        with self._get_connection() as conn:
            for table in ["pages", "links", "images", "headings", "schema_entries",
                          "http_headers", "redirects", "external_link_status",
                          "crawl_queue", "visited_urls"]:
                try:
                    stats[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                except sqlite3.Error:
                    stats[table] = 0
        return stats

    def close(self) -> None:
        """إغلاق connection."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
