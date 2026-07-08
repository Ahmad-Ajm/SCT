"""
crawler/async_core.py
======================
نسخة Async من الـ Crawler - أسرع 5-10x من الـ sync.

الفرق الرئيسي:
- يستخدم aiohttp بدلاً من requests
- يفحص عدة URLs بشكل متزامن (concurrent)
- يحترم rate limits لكل host
- متوافق مع SQLite database

يستخدم نفس الـ Extractors والـ Analyzers والـ Exporters.
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from tqdm import tqdm

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

from crawler.core import PageData, CrawlStats
from crawler.robots_parser import RobotsParser
from crawler.sitemap_parser import SitemapParser
from crawler.http_client import HTTPClient  # للـ sitemap parser

from extractors.canonical_extractor import extract_canonical
from extractors.content_extractor import extract_content
from extractors.headers_extractor import extract_headers
from extractors.headings_extractor import extract_headings
from extractors.hreflang_extractor import extract_hreflang
from extractors.images_extractor import extract_images
from extractors.links_extractor import extract_links
from extractors.meta_extractor import extract_meta
from extractors.mixed_content import detect_mixed_content
from extractors.custom_extractor import extract_custom
from extractors.og_extractor import extract_og_twitter
from extractors.pagination_extractor import extract_pagination
from extractors.resources_extractor import extract_resources
from extractors.schema_extractor import extract_schema

from storage.database import CrawlDatabase

from utils.helpers import (
    is_internal_url,
    is_safe_remote_url,
    matches_any_pattern,
    normalize_url,
)
from utils.logger import get_logger
from utils.monitoring import event, gauge, increment, span

log = get_logger(__name__)


class AsyncCrawler:
    """
    Crawler غير متزامن - أسرع بكثير من النسخة sync.

    Example:
        >>> crawler = AsyncCrawler(config, db=database)
        >>> asyncio.run(crawler.run())

    أو من main:
        >>> import asyncio
        >>> asyncio.run(crawler.run())
    """

    def __init__(self, config: dict[str, Any], db: Optional[CrawlDatabase] = None):
        """
        Args:
            config: الإعدادات من config.yaml
            db: اختياري - قاعدة بيانات للحفظ المباشر
        """
        if not AIOHTTP_AVAILABLE:
            raise ImportError(
                "aiohttp غير مثبت! ثبّت: pip install aiohttp"
            )

        self.config = config
        self.site_config = config["site"]
        self.crawl_config = config["crawl"]
        self.js_config = config.get("javascript", {})
        self.extraction_config = config.get("extraction", {})
        self.filter_config = config.get("filters", {})

        # === Custom Extraction (الخطة #5) ===
        from extractors.custom_extractor import compile_rules
        ce = config.get("custom_extraction", {}) or {}
        self.custom_rules = compile_rules(ce.get("rules")) if ce.get("enabled") else []
        # str(soup) مكلف؛ لا نحتاجه إلا لقواعد regex (CSS تعمل على soup مباشرة)
        self._custom_needs_html = any(r.get("type") == "regex" for r in self.custom_rules)
        self.all_custom: list[dict[str, Any]] = []

        # === Resource Inventory (الخطة #3) ===
        self.all_resources: list[dict[str, Any]] = []
        self._resources_cap = 300000

        # === JS Rendering async (الخطة #4) ===
        _js = self.js_config
        self.js_enabled = bool(_js.get("enabled", False))
        self.js_mode = str(_js.get("mode", "all")).lower()       # all | sample | on_empty_content
        self.js_max_pages = int(_js.get("max_pages", 100) or 0)  # 0 = بلا حد
        self.js_empty_threshold = int(_js.get("empty_content_words", 50) or 50)
        self.js_renderer = None
        self.all_js_diff: list[dict[str, Any]] = []
        self._js_rendered_count = 0
        self._js_sem = asyncio.Semaphore(max(1, int(_js.get("concurrency", 2) or 2)))
        # فحص الوصولية (axe-core) — اختياري، يحتاج تصيير JS
        self.a11y_config = config.get("accessibility", {}) or {}
        self.all_accessibility: list[dict[str, Any]] = []
        # F05/F06: سقوف قابلة للضبط لمنع نموّ غير محدود في زحوف ضخمة
        self._js_diff_cap = int(config.get("js_diff_max_entries", 100000))
        self._a11y_cap = int(config.get("accessibility_max_entries", 50000))
        self._js_diff_dropped = 0
        self._a11y_dropped = 0
        self._js_diff_cap_warned = False
        self._a11y_cap_warned = False

        # v1.13.25: سطر النشاط الحيّ — الرابط الجاري زحفه/تصييره الآن. يظهر في
        # الواجهة تحت الحالة كي لا يبدو الزحف معلّقاً. الكتابة على القرص مُخنَّقة
        # بـ250ms (بوّابة زمنيّة) لتفادي إرهاق I/O عند التزامن العالي.
        self._current_url = ""
        self._last_progress_write = 0.0

        # === Domain info ===
        self.start_url = normalize_url(self.site_config["start_url"])
        self.primary_domain = self.site_config["domain"]
        self.additional_domains = self.site_config.get("additional_internal_domains", [])

        # === Async settings ===
        self.concurrent_requests = self.crawl_config.get("concurrent_requests", 5)
        self.per_host_limit = max(1, self.concurrent_requests // 2)
        # تحكّم تكيّفي بالسرعة (IMP-10) — مطفأ افتراضياً
        from crawler.adaptive_throttle import AdaptiveThrottle
        self.adaptive = AdaptiveThrottle.from_config(self.crawl_config)
        self.verify_ssl = self.crawl_config.get("verify_ssl", True)
        self.robots_failure_policy = self.crawl_config.get("robots_failure_policy", "allow")
        # استراتيجية البذور: homepage | sitemap | hybrid (الافتراضي)
        self.seed_strategy = str(self.crawl_config.get("seed_strategy", "hybrid")).lower()
        if self.seed_strategy not in ("homepage", "sitemap", "hybrid"):
            self.seed_strategy = "hybrid"

        # === Crawl state ===
        self.visited: set[str] = set()
        self.queue: asyncio.Queue = asyncio.Queue()
        self.queued_urls: set[str] = set()

        # Lock لحماية visited set من race conditions بين workers
        # (check-then-add غير atomic بدون lock)
        self._visited_lock: asyncio.Lock = asyncio.Lock()

        # عدّاد Workers المشغولة فعلياً بمعالجة صفحة (للكشف الصحيح عن الانتهاء)
        self._busy_workers: int = 0
        self._busy_lock: asyncio.Lock = asyncio.Lock()

        # v1.13.26 (L8-SOFTCAP-05): عدّاد فتحات محجوزة لجعل max_pages دقيقاً —
        # يُزاد ذرّياً قبل جلب كل صفحة ويُقارن بـ max_pages بدل فحص pages_crawled
        # بعد الجلب (الذي كان يسمح بتجاوز يصل concurrency-1 صفحة).
        self._pages_claimed: int = 0

        # تتبّع عمق كل URL في الطابور (لاستئناف صحيح + snapshot)
        self._url_depth: dict[str, int] = {}

        # كل روابط الـ sitemaps التي رُئيت (لـ sitemap_diff الكامل)
        self.sitemap_urls_seen: list[str] = []

        # روابط مُستبعَدة أثناء الزحف مع السبب (تقرير Excluded URLs)
        self.excluded: list[dict[str, str]] = []
        self.excluded_counts: dict[str, int] = {}
        self._excluded_cap = 10000

        # v1.08: روابط مُؤجَّلة (pagination عميق، redirect_wrapper، filter combos).
        # تُكتَشف لكن لا تُضاف للطابور في Phase 1. تُحفَظ مع نوعها ومصدرها كي
        # يُظهرها التقرير ويستطيع المستخدم تشغيل Phase 2 عليها لاحقاً.
        from utils.url_classifier import UrlClassifier
        deferred_cfg = self.crawl_config.get("deferred_crawl", {}) or {}
        self.deferred_enabled = bool(deferred_cfg.get("enabled", True))
        self.deferred: dict[str, dict[str, str]] = {}
        self._deferred_cap = int(deferred_cfg.get("max_tracked", 50000))
        # F02: lock لحماية check+cap+write على deferred dict من race بين workers
        self._deferred_lock: asyncio.Lock = asyncio.Lock()
        # في Phase 2: classifier يُمرَّر له `phase2=True` فيُعطّل التأجيل
        self.phase2_mode = bool(deferred_cfg.get("phase2", False))
        self.classifier = UrlClassifier(
            sitemap_urls=None,  # تُعبَّأ بعد قراءة sitemap
            navigation_urls=None,
            pagination_max=int(deferred_cfg.get("pagination_max", 3)),
            filter_max=int(deferred_cfg.get("filter_max", 1)),
        )

        # بذور sitemap مؤجَّلة: لا نُغرق بها الطابور؛ نزحف الصفحة الرئيسية
        # والروابط المكتشفة (BFS) أولاً، ثم نسحب من البذور دفعات عند نضوب الطابور.
        self.sitemap_seeds: list[str] = []
        self._seed_index: int = 0
        self._seed_lock: asyncio.Lock = asyncio.Lock()

        # === Database (optional) ===
        self.db = db
        self.use_db = db is not None

        # كاش للـ getters المعتمدة على DB: بعد انتهاء الزحف تكون القاعدة ثابتة،
        # فنتفادى إعادة تنفيذ SELECT * وإعادة بناء dicts في كل مرحلة (تحليل/تصدير/تكامل).
        self._getter_cache: dict[str, list[Any]] = {}

        # === In-memory storage (إذا لا يوجد DB) ===
        self.pages: list[PageData] = []
        self.all_links: list[dict[str, Any]] = []
        self.all_images: list[dict[str, Any]] = []
        self.all_headings: list[dict[str, Any]] = []
        self.all_schema: list[dict[str, Any]] = []
        self.all_headers: list[dict[str, Any]] = []
        self.all_redirects: list[dict[str, Any]] = []

        # === Statistics ===
        self.stats = CrawlStats()

        # === Robots & Sitemap ===
        self.robots: Optional[RobotsParser] = None
        if self.crawl_config["respect_robots"]:
            self.robots = RobotsParser(
                self.start_url,
                self.crawl_config["user_agent"],
                failure_policy=self.robots_failure_policy,
                verify_ssl=self.verify_ssl,
                timeout=self.crawl_config.get("timeout_seconds", 15),
            )

        # نستخدم sync HTTPClient فقط لقراءة sitemap
        self.sync_http = HTTPClient(
            user_agent=self.crawl_config["user_agent"],
            timeout=self.crawl_config["timeout_seconds"],
        )
        self.sitemap_parser = SitemapParser(self.sync_http)

        # === Async session (يُنشَأ في run) ===
        self.session: Optional[aiohttp.ClientSession] = None

        # === Stop signal ===
        self._stop_requested = False
        self._external_stop = False  # إيقاف بطلب المستخدم/إشارة (يميّز عن الانتهاء الطبيعي)
        self._reached_max_pages = False  # توقّف بسبب بلوغ max_pages (نتيجة جزئية)

        # === Resume / state ===
        self.state_config = config.get("state", {})
        self.resume_if_exists = self.state_config.get("resume_if_exists", True)
        self.save_interval = max(1, int(self.state_config.get("save_interval", 50)))
        # snapshot الطابور مكلف (يُعيد كتابة كل الطابور) → فترة أكبر لتقليل I/O
        self.snapshot_interval = max(self.save_interval, 200)
        self._persisted_visited: set[str] = set()  # لكتابة الفرق فقط
        # حجم الدفعة المسحوبة من بذور sitemap عند نضوب الطابور
        self.sitemap_batch = max(self.concurrent_requests * 4, 20)
        # السماح بعناوين داخلية (للمواقع الداخلية الموثوقة فقط)
        self.allow_private_hosts = self.crawl_config.get("allow_private_hosts", False)
        self._pages_since_snapshot = 0

        # === Progress callback (للواجهة المرئية / المتابعة المباشرة) ===
        # دالة تُستدعى دورياً بإحصائيات التقدّم؛ تُضبط من الخارج.
        self.progress_callback = None
        # عند تشغيل عبر subprocess (الواجهة) نكتب التقدّم لملف عبر متغيّر بيئة
        self._progress_file = os.environ.get("SCT_PROGRESS_FILE") or None
        if self._progress_file:
            self.progress_callback = self._write_progress_file

        # === Progress bar ===
        self.progress_bar: Optional[tqdm] = None
        gauge("crawler.concurrent_requests", self.concurrent_requests)
        gauge("crawler.per_host_limit", self.per_host_limit)
        gauge("crawler.verify_ssl", self.verify_ssl)

    # ========================================================
    # === Public API ===
    # ========================================================

    async def run(self) -> None:
        """تشغيل الزحف الكامل."""
        with span("crawler.async.run", url=self.start_url):
            log.info("=" * 60)
            log.info(f"🚀 بدء Async Crawler: {self.start_url}")
            log.info(f"   التزامن: {self.concurrent_requests} طلب متوازي")
            log.info(f"   لكل host: {self.per_host_limit}")
            log.info("=" * 60)

            self.stats.start_time = time.time()
            self._install_signal_handlers()

            try:
                # === التحضير ===
                await self._prepare()

                # === بدء مُصيّر JS (الخطة #4) إن كان مفعّلاً ===
                if self.js_enabled:
                    from crawler.js_renderer import JSRendererAsync
                    # فحص الوصولية يحتاج تصيير JS؛ نحمّل مصدر axe مرّة واحدة
                    axe_source = ""
                    if self.a11y_config.get("enabled"):
                        from analyzers.accessibility import load_axe_source
                        axe_source = load_axe_source(
                            self.a11y_config.get("axe_source", ""),
                            self.a11y_config.get("cdn_url", ""),
                            bool(self.a11y_config.get("allow_cdn", False)),
                        )
                        if not axe_source:
                            log.warning(
                                "فحص الوصولية مفعّل لكن تعذّر تحميل axe-core "
                                "(حدّد accessibility.axe_source محلياً أو فعّل allow_cdn)")
                    renderer = JSRendererAsync(
                        browser=self.js_config.get("browser", "chromium"),
                        headless=self.js_config.get("headless", True),
                        wait_until=self.js_config.get("wait_until", "networkidle"),
                        timeout=self.js_config.get("timeout", 15),
                        user_agent=self.crawl_config["user_agent"],
                        block_resource_types=self.js_config.get("block_resource_types"),
                        axe_source=axe_source,
                        axe_max=int(self.a11y_config.get("max_pages", 50) or 0),
                        # F04: مرّر إعداد SSRF كي يُطابق فحص JS رينديرر سلوك aiohttp
                        allow_private_hosts=self.allow_private_hosts,
                    )
                    if await renderer.start():
                        self.js_renderer = renderer
                    else:
                        log.warning("تعذّر تفعيل تصيير JS — متابعة بـ HTML الخام")

                # === إنشاء aiohttp session ===
                timeout = aiohttp.ClientTimeout(total=self.crawl_config["timeout_seconds"])
                connector = aiohttp.TCPConnector(
                    limit=self.concurrent_requests,
                    limit_per_host=self.per_host_limit,
                    enable_cleanup_closed=True,
                )

                headers = {
                    "User-Agent": self.crawl_config["user_agent"],
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ar,en;q=0.9",
                    # لا نُعلن br (brotli) لأن aiohttp لا يفكّه بدون مكتبة إضافية؛
                    # gzip/deflate يفكّهما aiohttp محلياً.
                    "Accept-Encoding": "gzip, deflate",
                }

                async with aiohttp.ClientSession(
                    timeout=timeout,
                    connector=connector,
                    headers=headers,
                ) as session:
                    self.session = session
                    await self._crawl_loop()

            finally:
                self.stats.end_time = time.time()
                if self.js_renderer is not None:
                    await self.js_renderer.stop()
                    self.js_renderer = None
                self._snapshot_state(force=True)
                self.sync_http.close()
                self._remove_signal_handlers()
                # حالة غير-نهائية: ما زالت هناك مراحل (تحليل/روابط خارجية/تصدير)
                # تتولّى main.py كتابة الحالة النهائية بعد التصدير.
                self._emit_progress(status="post_crawl")
                self._print_summary()

    @staticmethod
    def _stop_signals():
        """الإشارات التي نلتقطها للإيقاف النظيف (SIGBREAK مهمّة على ويندوز
        لأن واجهة التشغيل ترسل CTRL_BREAK_EVENT)."""
        import signal as _signal
        sigs = [_signal.SIGINT, _signal.SIGTERM]
        if hasattr(_signal, "SIGBREAK"):  # ويندوز
            sigs.append(_signal.SIGBREAK)
        return sigs

    def _install_signal_handlers(self) -> None:
        """تثبيت معالجات الإيقاف النظيف (SIGINT/SIGTERM/SIGBREAK)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        import signal as _signal

        self._prev_handlers = {}
        for sig in self._stop_signals():
            try:
                loop.add_signal_handler(sig, self._request_stop)
            except (NotImplementedError, RuntimeError, ValueError):
                # ويندوز لا يدعم add_signal_handler للوب — fallback لمعالج عادي
                try:
                    self._prev_handlers[sig] = _signal.getsignal(sig)
                    _signal.signal(sig, lambda *_: self._request_stop())
                except (ValueError, OSError):
                    pass

    def _remove_signal_handlers(self) -> None:
        # v1.13.15 (A2-2): استعد المعالجات المحفوظة على Windows أيضاً —
        # كانت تبقى مُعدَّلة وتؤثّر على عمليّات لاحقة في نفس process.
        import signal as _signal
        try:
            loop = asyncio.get_running_loop()
            for sig in self._stop_signals():
                try:
                    loop.remove_signal_handler(sig)
                except (NotImplementedError, RuntimeError, ValueError):
                    pass
        except RuntimeError:
            pass
        for sig, prev in (getattr(self, "_prev_handlers", {}) or {}).items():
            try:
                _signal.signal(sig, prev)
            except (ValueError, OSError):
                pass
        self._prev_handlers = {}

    def _request_stop(self) -> None:
        """طلب إيقاف نظيف للزحف (من المستخدم/إشارة)."""
        if not self._stop_requested:
            log.warning("\n⚠️  تم استلام إشارة إيقاف — حفظ الحالة والخروج بأمان...")
        self._external_stop = True
        self._stop_requested = True

    # ========================================================
    # === Preparation ===
    # ========================================================

    async def _prepare(self) -> None:
        """التحضير قبل الزحف."""
        with span("crawler.async.prepare", url=self.start_url):
            loop = asyncio.get_running_loop()

            # تحميل robots.txt (sync) في executor حتى لا يجمّد حلقة الأحداث
            if self.robots:
                with span("crawler.robots.load", url=self.start_url):
                    await loop.run_in_executor(None, self.robots.load)

            # استئناف الحالة من قاعدة البيانات إن وُجدت
            await self._restore_state()

            # تحميل sitemaps (sync) في executor
            sitemap_urls = []
            if self.robots and self.robots.is_loaded():
                sitemap_urls.extend(self.robots.get_sitemaps())

            default_sitemap = urljoin(self.start_url, "/sitemap.xml")
            if default_sitemap not in sitemap_urls:
                sitemap_urls.append(default_sitemap)

            # الصفحة الرئيسية تُزحف أولاً في وضعَي homepage و hybrid
            include_homepage = self.seed_strategy in ("homepage", "hybrid", "sitemap")
            if include_homepage and (
                self.start_url not in self.queued_urls
                and self.start_url not in self.visited
            ):
                # v1.09-B1: start_url يجب أن يُزحَف دائماً حتّى لو طابق نمطاً
                # مؤجَّلاً (مثل موقع رئيسيّته `?page=N` غير معتاد).
                await self._enqueue(self.start_url, 0, bypass_classifier=True)

            # في وضع homepage لا نقرأ sitemap كبذور إطلاقاً،
            # لكننا ما زلنا نحلّله لأجل sitemap_diff فقط.
            sitemap_flood = 0
            seen_seed: set[str] = set()
            for sitemap_url in sitemap_urls:
                # حماية SSRF لروابط sitemap المعلنة
                safe, reason = is_safe_remote_url(sitemap_url, self.allow_private_hosts)
                if not safe:
                    log.warning(f"تخطّي sitemap غير آمن {sitemap_url}: {reason}")
                    continue
                with span("crawler.sitemap.parse", url=sitemap_url):
                    entries = await loop.run_in_executor(
                        None, self.sitemap_parser.parse, sitemap_url
                    )
                gauge("crawler.sitemap.entries_last", len(entries))
                for entry in entries:
                    normalized = normalize_url(entry.url)
                    self.sitemap_urls_seen.append(normalized)
                    if normalized in seen_seed:
                        continue
                    seen_seed.add(normalized)
                    if self.seed_strategy == "sitemap":
                        # وضع sitemap: نُدخل الكل في الطابور مباشرة (بعد الرئيسية)
                        if (
                            normalized not in self.visited
                            and normalized not in self.queued_urls
                            and not self._should_skip_url(normalized)
                        ):
                            # v1.09-B1: روابط sitemap أساسيّة بحكم التعريف ⇒ تجاوز
                            # classifier (sitemap هو مصدر «الحقيقة» للصفحات الفعليّة).
                            await self._enqueue(normalized, 0, bypass_classifier=True)
                            sitemap_flood += 1
                    elif self.seed_strategy == "hybrid":
                        # بذور مؤجَّلة: تُسحب بعد نضوب الروابط المكتشفة
                        self.sitemap_seeds.append(normalized)
                    # homepage: نتجاهل البذور تماماً

            # حفظ روابط sitemap في DB لـ analyze-only
            if self.use_db and self.db and self.sitemap_urls_seen:
                try:
                    self.db.set_meta("sitemap_urls", sorted(set(self.sitemap_urls_seen)))
                except Exception as e:
                    log.debug(f"تعذّر حفظ sitemap_urls: {e}")

            # v1.08: نُغذّي المصنّف بروابط sitemap (تُعتبر «أساسيّة» مهما كانت بنيتها)
            if self.deferred_enabled and self.sitemap_urls_seen:
                self.classifier.update_sitemap(self.sitemap_urls_seen)
                # رابط البداية أيضاً «navigation» (Phase 1 يحتفظ به دائماً)
                if self.start_url:
                    self.classifier.update_navigation([self.start_url])

            gauge("crawler.initial_queue_size", self.queue.qsize())
            gauge("crawler.sitemap_seeds", len(self.sitemap_seeds))
            log.info(
                f"استراتيجية الزحف: {self.seed_strategy} | الطابور الأولي={self.queue.qsize()} "
                f"| بذور sitemap مؤجَّلة={len(self.sitemap_seeds)}"
            )

    async def _refill_from_sitemap(self) -> int:
        """سحب دفعة من بذور sitemap إلى الطابور عند نضوب الروابط المكتشفة.

        v1.09-B1: bypass_classifier=True — sitemap_seeds مصدرها sitemap (= أساسي)،
        كذلك v1.08 Phase 2 يحقن `deferred_urls` السابقة في sitemap_seeds (يجب فحصها)."""
        added = 0
        async with self._seed_lock:
            while self._seed_index < len(self.sitemap_seeds):
                url = self.sitemap_seeds[self._seed_index]
                self._seed_index += 1
                if (
                    url in self.visited
                    or url in self.queued_urls
                    or self._should_skip_url(url)
                ):
                    continue
                await self._enqueue(url, 0, bypass_classifier=True)
                added += 1
                if added >= self.sitemap_batch:
                    break
        if added:
            increment("crawler.sitemap_refill", added)
        return added

    async def _enqueue(
        self, url: str, depth: int, source_url: str = "",
        bypass_classifier: bool = False,
    ) -> None:
        """إضافة URL للطابور مع تتبّع العمق. v1.08: قبل الإضافة، يُستشار المصنّف:
        إن كان الرابط من نوع «مؤجَّل» يُحفَظ في `self.deferred` بدل الطابور (للتقرير
        + Phase 2). يُعطَّل التأجيل في phase2_mode أو إن deferred_enabled=False.

        v1.09-B1: `bypass_classifier=True` يفرض تجاوز classifier — يُستعمل لـ:
        - start_url (يجب أن يُزحَف دائماً حتّى لو طابق نمطاً مؤجَّلاً)
        - URLs المُستأنَفة من DB (سبق أن نوينا زحفها — لا تُؤجَّل صامتاً)
        - sitemap-flood (sitemap URLs أساسيّة بحكم التعريف)
        """
        if self.deferred_enabled and not self.phase2_mode and not bypass_classifier:
            kind, is_deferred = self.classifier.classify(url)
            if is_deferred:
                # F02: check+cap+write atomic لمنع تجاوز السقف وكتابة مزدوجة
                async with self._deferred_lock:
                    if url in self.deferred:
                        return
                    if len(self.deferred) >= self._deferred_cap:
                        # v1.09-B1: لا نسقط بصمت — نسجّل تحذيراً واحداً عند بلوغ الحدّ
                        if not getattr(self, "_deferred_cap_warned", False):
                            log.warning(
                                f"⚠️ deferred URL cap ({self._deferred_cap}) reached — "
                                f"إضافيات لن تُسجَّل. ارفع crawl.deferred_crawl.max_tracked إن لزم.")
                            self._deferred_cap_warned = True
                        increment("crawler.deferred.cap_dropped")
                        return
                    self.deferred[url] = {
                        "kind": kind,
                        "source_url": source_url or "",
                        "depth": str(depth),
                    }
                return
        await self.queue.put((url, depth))
        self.queued_urls.add(url)
        self._url_depth[url] = depth

    async def _restore_state(self) -> None:
        """استئناف visited + الطابور من قاعدة البيانات (إن مُفعّل)."""
        if not (self.use_db and self.db and self.resume_if_exists):
            return
        try:
            visited = self.db.get_visited_all()
            queued = self.db.get_queue_all()
        except Exception as e:
            log.debug(f"تعذّر استئناف الحالة: {e}")
            return
        if not visited and not queued:
            return
        self.visited |= visited
        self._persisted_visited |= visited  # سبق حفظها — لا نُعيد كتابتها
        restored = 0
        for url, depth in queued:
            if url not in self.visited and url not in self.queued_urls:
                # v1.09-B1: URLs المُستأنَفة من DB سبق أن نوينا زحفها — لا نسمح
                # للـclassifier بإلقائها في self.deferred صامتاً (كان bug خطير قبل v1.09).
                await self._enqueue(url, depth, bypass_classifier=True)
                restored += 1
        log.info(f"♻️  استئناف: {len(visited)} مزحوف، {restored} في الانتظار")

    def _snapshot_state(self, force: bool = False) -> None:
        """حفظ snapshot للحالة (visited + الطابور) في قاعدة البيانات للاستئناف."""
        if not (self.use_db and self.db):
            return
        if not force:
            self._pages_since_snapshot += 1
            if self._pages_since_snapshot < self.snapshot_interval:
                return
        self._pages_since_snapshot = 0
        try:
            # نكتب فقط الـ visited الجديدة منذ آخر snapshot (تقليل I/O)
            new_visited = self.visited - self._persisted_visited
            if new_visited:
                self.db.mark_visited_many(list(new_visited))
                self._persisted_visited |= new_visited
            queue_items = [(u, self._url_depth.get(u, 0)) for u in self.queued_urls]
            self.db.replace_queue(queue_items)
        except Exception:
            log.warning("تعذّر حفظ snapshot", exc_info=True)

    # ========================================================
    # === Main Crawl Loop ===
    # ========================================================

    async def _crawl_loop(self) -> None:
        """الحلقة الرئيسية - تشغّل workers متوازية."""
        with span("crawler.async.loop", workers=self.concurrent_requests):
            max_pages = self.crawl_config["max_pages"]
            total_estimate = max_pages if max_pages > 0 else None

            # نُعطّل شريط tqdm في وضع الواجهة/العملية الفرعية (SCT_PROGRESS_FILE مضبوط)
            # أو عند عدم وجود طرفية تفاعلية، كي لا تتلوّث run.log بأشرطة التقدّم.
            # الواجهة تعتمد على progress.json للتقدّم الحيّ بأي حال.
            try:
                _is_tty = sys.stdout.isatty()
            except (AttributeError, ValueError):
                _is_tty = False
            quiet_progress = bool(os.environ.get("SCT_PROGRESS_FILE")) or not _is_tty

            self.progress_bar = tqdm(
                total=total_estimate,
                desc="Async Crawling",
                unit="page",
                dynamic_ncols=True,
                disable=quiet_progress,
            )

            # إنشاء workers
            workers = [
                asyncio.create_task(self._worker(worker_id))
                for worker_id in range(self.concurrent_requests)
            ]

            try:
                # ننتظر انتهاء كل الـ workers ذاتياً (لا نعتمد على queue.join()
                # الذي يتعلّق لو خرج worker تاركاً عناصر في الطابور — إصلاح C1)
                await asyncio.gather(*workers)
            finally:
                # ضمان توقف الجميع ثم انتظارهم
                self._stop_requested = True
                await asyncio.gather(*workers, return_exceptions=True)

                if self.progress_bar is not None:
                    self.progress_bar.close()

    async def _worker(self, worker_id: int) -> None:
        """Worker واحد يعالج URLs من القائمة."""
        max_pages = self.crawl_config["max_pages"]
        max_depth = self.crawl_config["max_depth"]
        delay = self.crawl_config["delay_seconds"]

        # تطبيق Crawl-Delay من robots.txt
        if self.robots:
            robots_delay = self.robots.get_crawl_delay()
            if robots_delay and robots_delay > delay:
                delay = robots_delay

        worker_pages = 0
        try:
            while not self._stop_requested:
                # حد الصفحات: نطلب إيقافاً نظيفاً للجميع (إصلاح C1: لا break يترك
                # عناصر معلّقة في الطابور تُسبّب تعليق الإنهاء).
                if max_pages > 0 and self.stats.pages_crawled >= max_pages:
                    self._reached_max_pages = True
                    self._stop_requested = True
                    break

                # جلب URL من القائمة (مع timeout للكشف عن الانتهاء)
                try:
                    url, depth = await asyncio.wait_for(self.queue.get(), timeout=0.5)
                    # v1.13.26 (L8-RACE-01): نُعلّم أنفسنا مشغولين فوراً بعد السحب من
                    # الطابور وقبل أيّ await — وإلّا يرى worker آخر (busy==0 && empty)
                    # في الفجوة فيُعلن انتهاء الزحف مُسقطاً عنصراً مسحوباً لكن غير
                    # محسوب بعد. (asyncio أُحاديّ الخيط: زيادة int بلا await ذرّيّة.)
                    self._busy_workers += 1
                except asyncio.TimeoutError:
                    # نضب الطابور: إن لم يكن أحد مشغولاً والطابور فارغ، فقد انتهى
                    # الزحف بالروابط (BFS). عندها نسحب دفعة من بذور sitemap.
                    async with self._busy_lock:
                        idle_and_empty = self._busy_workers == 0 and self.queue.empty()
                    if idle_and_empty:
                        if await self._refill_from_sitemap():
                            continue
                        # لا روابط مكتشفة ولا بذور متبقية ⇒ انتهينا
                        self._stop_requested = True
                        break
                    continue
                except asyncio.CancelledError:
                    break

                # من هنا حصلنا على عنصر: نضمن task_done() مرة واحدة بالضبط
                # (عدّاد busy زِيدَ أعلاه ذرّياً مع السحب — إصلاح L8-RACE-01).
                try:
                    self.queued_urls.discard(url)
                    self._url_depth.pop(url, None)

                    # check-and-add atomic لتفادي زحف مزدوج
                    async with self._visited_lock:
                        if url in self.visited:
                            continue
                        self.visited.add(url)

                    if depth > max_depth:
                        self.stats.pages_skipped += 1
                        increment("crawler.skipped.max_depth")
                        self._record_excluded(url, "max_depth")
                        continue

                    if self._should_skip_url(url):
                        self.stats.pages_skipped += 1
                        increment("crawler.skipped.filters")
                        self._record_excluded(url, "filters")
                        continue

                    if self.robots and not self.robots.can_fetch(url):
                        log.debug(f"Worker {worker_id}: robots blocked {url}")
                        self.stats.pages_skipped += 1
                        increment("crawler.skipped.robots")
                        self._record_excluded(url, "robots")
                        continue

                    # حماية SSRF (مهمة لأوضاع المنافسة/المقارنة)
                    safe, reason = is_safe_remote_url(url, self.allow_private_hosts)
                    if not safe:
                        log.debug(f"Worker {worker_id}: SSRF blocked {url} ({reason})")
                        self.stats.pages_skipped += 1
                        increment("crawler.skipped.ssrf")
                        self._record_excluded(url, f"ssrf:{reason}")
                        continue

                    # === زحف الصفحة ===
                    # v1.13.26 (L8-SOFTCAP-05): نحجز فتحة max_pages ذرّياً قبل الجلب
                    # عبر عدّاد claimed تحت القفل — بدل فحص pages_crawled بعد الجلب
                    # الذي كان يسمح بتجاوز يصل concurrency-1 صفحة (السلوك السابق).
                    if max_pages > 0:
                        async with self._busy_lock:
                            if self._pages_claimed >= max_pages:
                                self._reached_max_pages = True
                                self._stop_requested = True
                                continue
                            self._pages_claimed += 1
                    # v1.13.25: نسجّل الرابط الحاليّ (O(1)، بلا I/O) قبل الجلب
                    # كي يظهر في سطر النشاط الحيّ بالواجهة.
                    self._current_url = url
                    await self._crawl_page(url, depth)
                    worker_pages += 1
                    self._snapshot_state()

                    if self.progress_bar is not None:
                        self.progress_bar.update(1)
                        ok_count = sum(
                            cnt for status, cnt in self.stats.status_codes.items()
                            if 200 <= status < 300
                        )
                        self.progress_bar.set_postfix({
                            "queue": self.queue.qsize(),
                            "ok": ok_count,
                            "errors": self.stats.pages_failed,
                        })

                    self._emit_progress()

                    effective_delay = delay + self.adaptive.delay()
                    if effective_delay > 0:
                        await asyncio.sleep(effective_delay)

                except asyncio.CancelledError:
                    # الـ finally سيستدعي task_done() ويُنقص العدّاد مرة واحدة
                    break
                except Exception as e:
                    log.error(f"Worker {worker_id} error: {e}", exc_info=True)
                finally:
                    self.queue.task_done()
                    async with self._busy_lock:
                        self._busy_workers -= 1
        finally:
            event("crawler.worker", "done", worker_id=worker_id, pages=worker_pages)

    def _record_excluded(self, url: str, reason: str) -> None:
        """تسجيل رابط مُستبعَد مع السبب (مع سقف لحجم القائمة)."""
        key = reason.split(":", 1)[0]
        self.excluded_counts[key] = self.excluded_counts.get(key, 0) + 1
        if len(self.excluded) < self._excluded_cap:
            self.excluded.append({"url": url, "reason": reason})

    def get_excluded(self) -> list[dict[str, str]]:
        return self.excluded.copy()

    def _final_status(self) -> str:
        """تحديد حالة الانتهاء النهائية بدقّة."""
        if self._external_stop:
            return "stopped"
        if self._reached_max_pages:
            return "partial_max_pages"
        remaining = self.queue.qsize() + max(0, len(self.sitemap_seeds) - self._seed_index)
        return "partial" if remaining > 0 else "complete"

    def _emit_progress(self, status: str = "running") -> None:
        """استدعاء progress_callback إن وُجد (للواجهة المرئية).

        v1.13.25: الكتابة مُخنَّقة بـ250ms أثناء 'running' فقط — حالة running
        عالية التردّد (لكل صفحة، آلاف/دقيقة) فلا داعي لكتابة القرص كل مرّة.
        أيّ حالة نهائيّة/غير-running تُكتب فوراً (force). النتيجة: I/O أقلّ من
        السابق (كان يكتب لكل صفحة بلا خنق) + سطر نشاط حيّ يُظهر الرابط الحاليّ.
        """
        if self.progress_callback is None:
            return
        # بوّابة زمنيّة: نتخطّى كتابة running المتكرّرة خلال 250ms من الأخيرة.
        if status == "running":
            now = time.time()
            if now - self._last_progress_write < 0.25:
                return
            self._last_progress_write = now
        try:
            remaining_seeds = max(0, len(self.sitemap_seeds) - self._seed_index)
            cur = self._current_url or ""
            max_pages = self.crawl_config.get("max_pages", 0) or 0
            detail = f"[{self.stats.pages_crawled}/{max_pages or '∞'}] {cur}" if cur else ""
            self.progress_callback({
                "pages_crawled": self.stats.pages_crawled,
                "pages_failed": self.stats.pages_failed,
                "pages_skipped": self.stats.pages_skipped,
                "queue_size": self.queue.qsize() + remaining_seeds,
                "elapsed_seconds": round(self.stats.duration_seconds, 1),
                "pages_per_second": round(self.stats.pages_per_second, 2),
                "status": status,
                # v1.13.25: سطر النشاط الحيّ — الرابط الجاري زحفه الآن
                "phase_label": "crawling",
                "phase_detail": detail,
                "phase_current_url": cur,
                # v1.04: نُبلِّغ الواجهة فور بلوغ الحدّ كي تُخفي عدّاد الطابور المضلّل
                # (يبقى الطابور يحوي مئات الآلاف من الروابط المكتشفة لكنّها لن تُزحف)
                "reached_max_pages": bool(self._reached_max_pages),
            })
        except Exception as e:
            log.debug(f"progress_callback error: {e}")

    def _write_progress_file(self, data: dict[str, Any]) -> None:
        """كتابة التقدّم لملف JSON بشكل ذرّي (للمتابعة المباشرة عبر subprocess)."""
        if not self._progress_file:
            return
        try:
            tmp = self._progress_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self._progress_file)
        except OSError as e:
            log.debug(f"progress file write error: {e}")

    # ========================================================
    # === Page Crawling ===
    # ========================================================

    async def _crawl_page(self, url: str, depth: int) -> None:
        """زحف صفحة واحدة (async) مع retry logic."""
        with span("crawler.async.page", url=url, depth=depth):
            retry_attempts = self.crawl_config.get("retry_attempts", 3)
            retry_delay = self.crawl_config.get("retry_delay_seconds", 2)

            last_error: Optional[str] = None
            result: dict[str, Any] = {}

            for attempt in range(retry_attempts + 1):
                increment("crawler.fetch.attempts")
                if attempt > 0:
                    increment("crawler.fetch.retries")
                    backoff = retry_delay * (2 ** (attempt - 1))  # exponential backoff
                    log.debug(f"Retry {attempt}/{retry_attempts} for {url} (wait {backoff:.1f}s)")
                    await asyncio.sleep(backoff)

                result = await self._fetch_page(url, depth)

                if result.get("success"):
                    increment("crawler.pages.success")
                    return  # نجح

                last_error = result.get("error", "Unknown error")

                # بعض الأخطاء لا تستحق إعادة المحاولة
                if result.get("no_retry"):
                    increment("crawler.fetch.no_retry")
                    break

            # فشلت كل المحاولات
            if last_error:
                increment("crawler.pages.failed")
                self.stats.pages_failed += 1
                self._record_failed_page(
                    url, depth, last_error, result.get("status_code", 0),
                    result.get("redirects", []),
                )

    async def _fetch_page(self, url: str, depth: int) -> dict[str, Any]:
        """
        محاولة جلب صفحة واحدة.

        Returns:
            dict: {"success": bool, "error": str | None, "no_retry": bool, "status_code": int}
        """
        with span("crawler.async.fetch", url=url, depth=depth):
            return await self._fetch_page_impl(url, depth)

    async def _fetch_page_impl(self, url: str, depth: int) -> dict[str, Any]:
        """Implementation separated so the public fetch span stays small."""
        try:
            start_time = time.time()
            response_text = ""
            response_status = 0
            response_headers: dict[str, str] = {}
            final_url = url
            content_type = ""
            redirect_chain: list[tuple[str, int]] = []
            page_redirects: list[dict[str, Any]] = []
            error: Optional[str] = None
            size_bytes = 0

            try:
                # تتبع redirects يدوياً
                current_url = url
                visited_urls = set()
                max_redirects = self.crawl_config.get("max_redirect_hops", 5)

                for hop in range(max_redirects + 1):
                    if current_url in visited_urls:
                        error = f"Redirect loop at {current_url}"
                        break
                    visited_urls.add(current_url)

                    async with self.session.get(
                        current_url,
                        allow_redirects=False,
                        ssl=self.verify_ssl,
                    ) as response:
                        # عدّاد خام لكل استجابة HTTP (مراقبة فقط). توزيع الصفحات حسب
                        # الحالة (stats.status_codes) يُحسب مرة واحدة لكل صفحة محفوظة
                        # أدناه، كي يطابق ملخّص اللوغ عدد الصفحات فعلاً (لا قفزات/إعادات).
                        increment(f"http.status.{response.status}")

                        if 300 <= response.status < 400:
                            # Redirect
                            redirect_chain.append((current_url, response.status))
                            next_url = response.headers.get("Location")
                            if not next_url:
                                break
                            next_url = urljoin(current_url, next_url)

                            # حماية SSRF على وجهة الـ redirect
                            safe, reason = is_safe_remote_url(next_url, self.allow_private_hosts)
                            if not safe:
                                error = f"Redirect to unsafe URL: {reason}"
                                break

                            # احترام robots على وجهة الـ redirect (إصلاح H1)
                            if self.robots and not self.robots.can_fetch(next_url):
                                error = "Redirect target blocked by robots.txt"
                                break

                            # سجل الـ redirect محلياً (to_url = الوجهة المباشرة)
                            page_redirects.append({
                                "from_url": current_url,
                                "to_url": next_url,
                                "status_code": response.status,
                                "chain_length": 0,  # تُضبط بعد اكتمال السلسلة
                                "original_url": url,
                            })
                            increment("crawler.redirects")

                            current_url = next_url
                            continue

                        # الوجهة النهائية
                        final_url = current_url
                        response_status = response.status
                        response_headers = dict(response.headers)
                        content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
                        event(
                            "crawler.http_response",
                            "ok",
                            url=url,
                            final_url=final_url,
                            http_status=response_status,
                            content_type=content_type,
                        )

                        # قراءة المحتوى
                        # list + join بدلاً من bytes += لتجنب O(N²) copies
                        # قياس: 8.4x أسرع لـ 100 chunk
                        max_size = self.crawl_config.get("max_page_size_mb", 10) * 1024 * 1024
                        chunks: list[bytes] = []
                        total_bytes = 0
                        async for chunk in response.content.iter_chunked(8192):
                            chunks.append(chunk)
                            total_bytes += len(chunk)
                            if total_bytes > max_size:
                                error = "Page too large"
                                break
                        content = b"".join(chunks)
                        size_bytes = len(content)

                        # decode
                        encoding = response.charset or "utf-8"
                        try:
                            response_text = content.decode(encoding, errors="replace")
                        except (LookupError, TypeError):
                            response_text = content.decode("utf-8", errors="replace")

                        break
                else:
                    # for/else: الحلقة لم تُكسَر = تجاوزنا الحد
                    error = f"Too many redirects (>{max_redirects})"

            except asyncio.TimeoutError:
                # إصلاح double-increment: نُسجّل الخطأ فقط، لا نزيد stats هنا
                # الزيادة تحدث في مكان واحد فقط: في _crawl_page بعد كل المحاولات
                error = "Timeout"
            except aiohttp.ClientError as e:
                error = f"{type(e).__name__}: {str(e)[:100]}"
            except Exception as e:
                error = f"Unexpected: {type(e).__name__}: {str(e)[:100]}"

            # ضبط طول السلسلة لكل سجلات redirect لهذه الصفحة (دلالة موحّدة مع sync)
            for rec in page_redirects:
                rec["chain_length"] = len(page_redirects)

            elapsed_ms = (time.time() - start_time) * 1000
            gauge("crawler.last_response_time_ms", round(elapsed_ms, 2))

            if error:
                increment("crawler.fetch.errors")
                self.stats.fetch_errors += 1
                event("crawler.fetch", "error", url=url, error=error, http_status=response_status)
                # لا نزيد stats هنا — _crawl_page يُقرر بعد كل المحاولات
                # no_retry=True للأخطاء الدائمة مثل "page too large"
                no_retry = (
                    error == "Page too large"
                    or "Redirect loop" in error
                    or "unsafe URL" in error
                    or "blocked by robots" in error
                )
                return {
                    "success": False,
                    "error": error,
                    "status_code": response_status,
                    "no_retry": no_retry,
                    "redirects": page_redirects,
                }

            # غير HTML؟
            if content_type and not self._is_html_content(content_type):
                increment("crawler.non_html")
                self._record_non_html_page(
                    url, depth, response_status, content_type, size_bytes, elapsed_ms,
                    final_url, page_redirects
                )
                self.stats.pages_crawled += 1
                self.stats.status_codes[response_status] = (
                    self.stats.status_codes.get(response_status, 0) + 1
                )
                self.adaptive.record(response_status, elapsed_ms)
                return {"success": True, "error": None, "status_code": response_status}

            # تحليل HTML الخام
            soup = BeautifulSoup(response_text, "lxml")

            # === تصيير JS (الخطة #4): قد يستبدل soup بالنسخة المُصيَّرة ===
            js_data = {}
            if self.js_renderer is not None:
                soup, js_data = await self._maybe_render(url, soup, response_text)

            # استخراج كل البيانات — يُرجع (page, pre_extracted) لتجنب double-call
            page_data, pre_extracted = self._extract_all(
                url, depth, final_url, response_status, response_headers,
                content_type, size_bytes, elapsed_ms, redirect_chain, soup
            )
            if js_data:
                page_data.js_rendered = True
                page_data.js_console_errors = js_data.get("console_errors", [])
                page_data.js_network_requests = js_data.get("network_requests", 0)

            # حفظ — نمرر pre_extracted لتجنب إعادة extract_headings/extract_schema
            self._save_page_data(page_data, soup, url, response_headers, pre_extracted, page_redirects)

            self.stats.pages_crawled += 1
            self.stats.status_codes[response_status] = (
                self.stats.status_codes.get(response_status, 0) + 1
            )
            self.adaptive.record(response_status, elapsed_ms)
            self.stats.total_bytes += size_bytes
            increment("crawler.bytes", size_bytes)
            gauge("crawler.queue_size", self.queue.qsize())

            # اكتشاف روابط جديدة
            await self._discover_new_links(page_data, soup, depth)

            return {"success": True, "error": None, "status_code": response_status}

        except Exception as e:
            log.error(f"خطأ غير متوقع في {url}: {e}", exc_info=True)
            increment("crawler.fetch.unexpected_errors")
            return {
                "success": False,
                "error": f"Unexpected: {type(e).__name__}: {str(e)[:100]}",
                "status_code": 0,
                "no_retry": False,
            }

    # ========================================================
    # === Data Extraction ===
    # ========================================================

    def _extract_all(
        self,
        url: str,
        depth: int,
        final_url: str,
        status_code: int,
        headers: dict[str, str],
        content_type: str,
        size_bytes: int,
        elapsed_ms: float,
        redirect_chain: list[tuple[str, int]],
        soup: BeautifulSoup,
    ) -> tuple[PageData, dict[str, Any]]:
        """
        استخراج كل البيانات.

        Returns:
            tuple[PageData, dict]: الصفحة + بيانات مُستخرجة قابلة لإعادة الاستخدام
            نُرجع dict لتجنب إعادة استدعاء extract_headings/extract_schema
        """
        with span("crawler.extract.all", url=url, status=status_code, bytes=size_bytes):
            page = PageData(
                url=url,
                final_url=final_url,
                status_code=status_code,
                content_type=content_type,
                size_bytes=size_bytes,
                response_time_ms=elapsed_ms,
                depth=depth,
                crawled_at=datetime.now(timezone.utc).isoformat(),  # v1.13.26 (L4-BUG-5): UTC واعٍ بالمنطقة
                redirect_chain=redirect_chain,
                is_redirect=bool(redirect_chain),
            )

            if self._extract_enabled("meta"):
                with span("crawler.extract.meta", url=url):
                    meta = extract_meta(soup)
                for key, val in meta.items():
                    if hasattr(page, key):
                        setattr(page, key, val)

            if self._extract_enabled("headings"):
                with span("crawler.extract.headings", url=url):
                    headings = extract_headings(soup)
                page.h1_count = headings["h1_count"]
                page.h1_text = headings["h1_text"]
                page.h2_count = headings["h2_count"]
                page.h2_text = headings["h2_text"]
                page.h3_count = headings["h3_count"]
                page.h3_text = headings["h3_text"]
                page.headings_order = headings["order"]
            else:
                headings = {"detailed": []}

            if self._extract_enabled("canonical"):
                with span("crawler.extract.canonical", url=url):
                    canonical_data = extract_canonical(soup, headers, url)
                page.canonical = canonical_data["canonical"]
                page.canonical_in_header = canonical_data["in_header"]
                page.canonical_is_self = canonical_data["is_self"]

            if self._extract_enabled("hreflang"):
                with span("crawler.extract.hreflang", url=url):
                    page.hreflang_tags = extract_hreflang(soup, headers, url)

            if self._extract_enabled("pagination"):
                with span("crawler.extract.pagination", url=url):
                    pg = extract_pagination(soup, headers, url)
                page.pagination_next = pg["pagination_next"]
                page.pagination_prev = pg["pagination_prev"]
                page.is_paginated = pg["is_paginated"]

            if self._extract_enabled("og"):
                with span("crawler.extract.og", url=url):
                    og_data = extract_og_twitter(soup)
                for key in ["og_title", "og_description", "og_image", "og_type", "og_url",
                            "twitter_card", "twitter_title", "twitter_description", "twitter_image"]:
                    setattr(page, key, og_data.get(key, ""))

            if self._extract_enabled("schema"):
                with span("crawler.extract.schema", url=url):
                    schema_data = extract_schema(soup)
                page.schema_count = schema_data["count"]
                page.schema_types = schema_data["types"]
                page.schema_data = schema_data["raw"]
            else:
                schema_data = {"entries": []}

            if self._extract_enabled("content"):
                with span("crawler.extract.content", url=url):
                    content_data = extract_content(soup, size_bytes)
                page.word_count = content_data["word_count"]
                page.character_count = content_data["character_count"]
                page.paragraph_count = content_data["paragraph_count"]
                page.text_to_html_ratio = content_data["text_to_html_ratio"]
                page.language = content_data["language"]
                page.content_hash = content_data["content_hash"]
                page.content_simhash = content_data.get("content_simhash", "")

            if self._extract_enabled("headers"):
                with span("crawler.extract.headers", url=url):
                    headers_data = extract_headers(headers)
                page.server = headers_data["server"]
                page.cache_control = headers_data["cache_control"]
                page.content_encoding = headers_data["content_encoding"]
                page.hsts_enabled = headers_data["hsts_enabled"]
                page.x_robots_tag = headers_data["x_robots_tag"]

            # Indexability
            page.is_indexable, page.indexability_reason = self._check_indexability(
                page.status_code, page.meta_robots, page.x_robots_tag, page.canonical, url
            )

            # نُرجع البيانات المُستخرَجة لإعادة الاستخدام (تجنب double-call)
            pre_extracted = {
                "headings": headings,
                "schema": schema_data,
            }
            increment("crawler.extracted.pages")

            return page, pre_extracted

    def _save_page_data(
        self,
        page: PageData,
        soup: BeautifulSoup,
        url: str,
        response_headers: dict[str, str],
        pre_extracted: dict[str, Any],
        redirects: list[dict[str, Any]] | None = None,
    ) -> None:
        """
        حفظ كل البيانات المستخرَجة (DB أو memory).

        pre_extracted: بيانات استُخرِجت مسبقاً في _extract_all
                       لتجنب إعادة استدعاء نفس extractors (double-call bug fix)
        """
        with span("crawler.save_page_data", url=url):
            # === Custom Extraction (الخطة #5) ===
            if self.custom_rules:
                html_for_rules = str(soup) if self._custom_needs_html else ""
                vals = extract_custom(soup, html_for_rules, self.custom_rules)
                self.all_custom.append({"page_url": url, **vals})

            # === Resource Inventory (الخطة #3) ===
            if self.extraction_config.get("extract_resources", False) and \
                    len(self.all_resources) < self._resources_cap:
                self.all_resources.extend(
                    extract_resources(soup, url, self.primary_domain, self.additional_domains)
                )

            # === Headings تفصيلية — من pre_extracted (مرة واحدة!) ===
            headings_result = pre_extracted["headings"]
            headings_detailed = headings_result["detailed"]
            headings_with_url = [{"page_url": url, **h} for h in headings_detailed]

            # === Schema تفصيلية — من pre_extracted (مرة واحدة!) ===
            schema_result = pre_extracted["schema"]
            schema_entries = schema_result["entries"]
            schema_with_url = [{"page_url": url, **s} for s in schema_entries]

            if self._extract_enabled("images"):
                with span("crawler.extract.images", url=url):
                    images = extract_images(soup, url)
                page.images_count = len(images)
                page.images_without_alt_count = sum(1 for img in images if not img["alt"])
                images_with_url = [{"page_url": url, **img} for img in images]
            else:
                images_with_url = []

            if self._extract_enabled("links"):
                with span("crawler.extract.links", url=url):
                    links = extract_links(soup, url, self.primary_domain, self.additional_domains)
                page.internal_links_count = sum(1 for link in links if link["is_internal"])
                page.external_links_count = sum(1 for link in links if not link["is_internal"])
                page.nofollow_links_count = sum(1 for link in links if link["nofollow"])
                links_with_url = [{"from_url": url, **link} for link in links]
            else:
                links_with_url = []

            if self._extract_enabled("headers"):
                with span("crawler.extract.headers_detail", url=url):
                    headers_data = extract_headers(response_headers)
                headers_entry = {
                    "page_url": url,
                    "all_headers": dict(response_headers),
                    **headers_data,
                }
            else:
                headers_entry = {}

            if self._extract_enabled("mixed_content"):
                with span("crawler.extract.mixed_content", url=url):
                    mixed = detect_mixed_content(soup, url)
                page.has_mixed_content = mixed["has_mixed_content"]
                page.mixed_content_urls = mixed.get("mixed_urls", [])
                page.mixed_content_active_count = mixed.get("active_count", 0)
                page.mixed_content_passive_count = mixed.get("passive_count", 0)
                page.mixed_content_form_count = mixed.get("form_count", 0)

            redirects = redirects or []

            # === حفظ ===
            if self.use_db and self.db:
                # حفظ مباشر في DB (مع redirects ضمن نفس الحزمة/الـ transaction)
                self.db.save_page_bundle(
                    page,
                    links=links_with_url,
                    images=images_with_url,
                    headings=headings_with_url,
                    schema_entries=schema_with_url,
                    header_data=headers_entry,
                    redirects=redirects,
                )
            else:
                # حفظ في الذاكرة
                self.pages.append(page)
                self.all_links.extend(links_with_url)
                self.all_images.extend(images_with_url)
                self.all_headings.extend(headings_with_url)
                self.all_schema.extend(schema_with_url)
                self.all_redirects.extend(redirects)
                if headers_entry:
                    self.all_headers.append(headers_entry)

            increment("crawler.saved.pages")
            increment("crawler.saved.links", len(links_with_url))
            increment("crawler.saved.images", len(images_with_url))
            increment("crawler.saved.headings", len(headings_with_url))
            increment("crawler.saved.schema_entries", len(schema_with_url))

            # تحديث stats
            self.stats.total_internal_links += page.internal_links_count
            self.stats.total_external_links += page.external_links_count
            self.stats.total_images += page.images_count

    # ========================================================
    # === Link Discovery ===
    # ========================================================

    async def _discover_new_links(
        self, page: PageData, soup: BeautifulSoup, depth: int
    ) -> None:
        """اكتشاف الروابط الجديدة وإضافتها للقائمة."""
        with span("crawler.discover_links", url=page.url, depth=depth):
            discovered = 0
            for a_tag in soup.find_all("a", href=True):
                href = a_tag.get("href", "").strip()
                if not href:
                    continue

                absolute_url = urljoin(page.final_url or page.url, href)
                normalized = normalize_url(absolute_url)

                if not is_internal_url(normalized, self.primary_domain, self.additional_domains):
                    continue

                if self._should_skip_url(normalized):
                    continue

                if self.filter_config.get("respect_nofollow", False):
                    rel = a_tag.get("rel", [])
                    if isinstance(rel, str):
                        rel = rel.split()
                    if "nofollow" in rel:
                        continue

                # v1.08: نُمرّر الـURL الأصل ليُحفَظ مع المؤجَّل (يُساعد التشخيص:
                # «من أيّ صفحة جاء هذا الرابط المؤجَّل؟»). v1.08.1: استعمل page.url
                # — المتغيّر `url` لا يوجد في هذه الـscope (parameter اسمه `page`).
                # F01: check + enqueue atomic تحت visited_lock لمنع workers من
                # إضافة نفس الرابط مرّتين (race: check→pass→enqueue يتداخل بين 2+).
                # _enqueue لا يأخذ visited_lock داخلياً ⇒ آمن (لا deadlock).
                async with self._visited_lock:
                    if normalized in self.visited or normalized in self.queued_urls:
                        continue
                    await self._enqueue(normalized, depth + 1, source_url=page.url)
                discovered += 1
            increment("crawler.discovered_links", discovered)
            gauge("crawler.queue_size", self.queue.qsize())

    # ========================================================
    # === Helpers ===
    # ========================================================

    def _should_skip_url(self, url: str) -> bool:
        exclude = self.filter_config.get("exclude_patterns", [])
        include = self.filter_config.get("include_patterns", [])

        if exclude and matches_any_pattern(url, exclude):
            return True
        if include and not matches_any_pattern(url, include):
            return True
        return False

    def _is_html_content(self, content_type: str) -> bool:
        allowed = self.filter_config.get(
            "allowed_content_types", ["text/html", "application/xhtml+xml"]
        )
        return any(ct in content_type for ct in allowed)

    def _extract_enabled(self, name: str) -> bool:
        return self.extraction_config.get(f"extract_{name}", True)

    def _check_indexability(
        self,
        status_code: int,
        meta_robots: str,
        x_robots_tag: str,
        canonical: str,
        current_url: str,
    ) -> tuple[bool, str]:
        if status_code != 200:
            return False, f"Non-200 status: {status_code}"

        combined_robots = (meta_robots + " " + x_robots_tag).lower()
        if "noindex" in combined_robots:
            return False, "Noindex directive"

        if canonical and canonical != current_url and canonical != normalize_url(current_url):
            return True, "Canonicalised"

        return True, "Indexable"

    def _record_failed_page(
        self, url: str, depth: int, error: str, status: int,
        redirects: list[dict[str, Any]] | None = None,
    ) -> None:
        page = PageData(
            url=url,
            status_code=status,
            depth=depth,
            crawled_at=datetime.now(timezone.utc).isoformat(),  # v1.13.26 (L4-BUG-5): UTC واعٍ بالمنطقة
            crawl_error=error,
            is_indexable=False,
            indexability_reason=error,
        )
        redirects = redirects or []
        if self.use_db and self.db:
            self.db.save_page(page, redirects=redirects)
        else:
            self.pages.append(page)
            self.all_redirects.extend(redirects)

    def _record_non_html_page(
        self, url: str, depth: int, status: int, content_type: str,
        size: int, elapsed: float, final_url: str,
        redirects: list[dict[str, Any]] | None = None,
    ) -> None:
        page = PageData(
            url=url,
            final_url=final_url,
            status_code=status,
            content_type=content_type,
            size_bytes=size,
            response_time_ms=elapsed,
            depth=depth,
            crawled_at=datetime.now(timezone.utc).isoformat(),  # v1.13.26 (L4-BUG-5): UTC واعٍ بالمنطقة
            is_indexable=False,
            indexability_reason=f"Non-HTML: {content_type}",
        )
        redirects = redirects or []
        if self.use_db and self.db:
            self.db.save_page(page, redirects=redirects)
        else:
            self.pages.append(page)
            self.all_redirects.extend(redirects)

    # ========================================================
    # === Public Getters (compatibility مع sync version) ===
    # ========================================================

    def _memo_db(self, key: str, builder) -> list[Any]:
        """يبني القائمة من DB مرة واحدة ويخزّنها؛ يعيد نسخة سطحية لكل مستدعٍ."""
        cached = self._getter_cache.get(key)
        if cached is None:
            cached = builder()
            self._getter_cache[key] = cached
        return list(cached)

    def get_pages(self) -> list[PageData]:
        if self.use_db and self.db:
            return self._memo_db("pages", lambda: list(self.db.get_all_pages()))
        return self.pages.copy()

    def get_links(self) -> list[dict[str, Any]]:
        if self.use_db and self.db:
            return self._memo_db("links", lambda: list(self.db.get_all_links()))
        return self.all_links.copy()

    def get_images(self) -> list[dict[str, Any]]:
        if self.use_db and self.db:
            return self._memo_db("images", lambda: list(self.db.get_all_images()))
        return self.all_images.copy()

    def get_headings(self) -> list[dict[str, Any]]:
        if self.use_db and self.db:
            return self._memo_db("headings", lambda: list(self.db.get_all_headings()))
        return self.all_headings.copy()

    def get_schema(self) -> list[dict[str, Any]]:
        if self.use_db and self.db:
            return self._memo_db("schema", lambda: list(self.db.get_all_schema()))
        return self.all_schema.copy()

    def get_headers(self) -> list[dict[str, Any]]:
        if self.use_db and self.db:
            return self._memo_db("headers", lambda: list(self.db.get_all_headers()))
        return self.all_headers.copy()

    def get_redirects(self) -> list[dict[str, Any]]:
        if self.use_db and self.db:
            return self._memo_db("redirects", lambda: list(self.db.get_all_redirects()))
        return self.all_redirects.copy()

    def get_custom_extraction(self) -> list[dict[str, Any]]:
        return self.all_custom.copy()

    def get_resources(self) -> list[dict[str, Any]]:
        return self.all_resources.copy()

    def get_js_diff(self) -> list[dict[str, Any]]:
        return self.all_js_diff.copy()

    def get_accessibility(self) -> list[dict[str, Any]]:
        return self.all_accessibility.copy()

    @staticmethod
    def _quick_seo(soup: BeautifulSoup) -> dict[str, Any]:
        """قراءة سريعة لحقول SEO للمقارنة raw↔rendered."""
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        md = ""
        m = soup.find("meta", attrs={"name": "description"})
        if m:
            md = (m.get("content") or "").strip()
        canon = ""
        c = soup.select_one("link[rel=canonical]")
        if c:
            canon = (c.get("href") or "").strip()
        return {
            "title": title,
            "meta_description": md,
            "canonical": canon,
            "h1_count": len(soup.find_all("h1")),
            "link_count": len(soup.find_all("a", href=True)),
            "word_count": len(soup.get_text(" ", strip=True).split()),
        }

    def _should_render(self, raw_soup: BeautifulSoup) -> bool:
        if self.js_max_pages and self._js_rendered_count >= self.js_max_pages:
            return False
        if self.js_mode == "on_empty_content":
            words = len(raw_soup.get_text(" ", strip=True).split())
            return words < self.js_empty_threshold
        # all | sample → نصيّر ضمن الحد
        return True

    async def _maybe_render(self, url: str, raw_soup: BeautifulSoup, raw_html: str):
        """تصيير الصفحة وإرجاع (soup, js_data)؛ يسجّل diff بين raw وrendered."""
        if not self._should_render(raw_soup):
            return raw_soup, {}
        async with self._js_sem:
            if self.js_max_pages and self._js_rendered_count >= self.js_max_pages:
                return raw_soup, {}
            # v1.13.25: نُظهر الرابط الجاري تصييره في سطر النشاط الحيّ —
            # التصيير قد يأخذ ثوانٍ (networkidle) فيبدو معلّقاً بلا هذا.
            if self.progress_callback is not None:
                cap = self.js_max_pages or "∞"
                try:
                    self.progress_callback({
                        "status": "running",
                        "phase_label": "rendering_js",
                        "phase_detail": f"[{self._js_rendered_count + 1}/{cap}] {url}",
                        "phase_current_url": url,
                        "pages_crawled": self.stats.pages_crawled,
                        "pages_failed": self.stats.pages_failed,
                        "pages_skipped": self.stats.pages_skipped,
                    })
                except Exception as e:  # noqa: BLE001
                    log.debug(f"render progress emit error: {e}")
            rendered = await self.js_renderer.render(url)
            self._js_rendered_count += 1
        if not rendered.is_success or not rendered.html:
            increment("crawler.js.render_failed")
            return raw_soup, {}

        # جمع ملخّص الوصولية (axe-core) إن توفّر للصفحة المُصيَّرة
        # F06: سقف قابل للضبط (accessibility_max_entries) — نسقط الزائد ونحذّر مرة واحدة
        if getattr(rendered, "accessibility", None):
            if len(self.all_accessibility) < self._a11y_cap:
                self.all_accessibility.append(rendered.accessibility)
            else:
                self._a11y_dropped += 1
                if not self._a11y_cap_warned:
                    log.warning(
                        f"⚠️ accessibility entries cap ({self._a11y_cap}) reached — "
                        f"إضافيات لن تُسجَّل. ارفع accessibility_max_entries إن لزم.")
                    self._a11y_cap_warned = True
                increment("crawler.accessibility.cap_dropped")

        rendered_soup = BeautifulSoup(rendered.html, "lxml")
        raw = self._quick_seo(raw_soup)
        ren = self._quick_seo(rendered_soup)
        # F05: سقف قابل للضبط (js_diff_max_entries) — نسقط الزائد ونحذّر مرة واحدة
        if len(self.all_js_diff) < self._js_diff_cap:
            self.all_js_diff.append({
                "page_url": url,
                "raw_words": raw["word_count"], "rendered_words": ren["word_count"],
                "words_added": ren["word_count"] - raw["word_count"],
                "raw_links": raw["link_count"], "rendered_links": ren["link_count"],
                "links_added": ren["link_count"] - raw["link_count"],
                "raw_empty": raw["word_count"] < self.js_empty_threshold,
                "title_changed": raw["title"] != ren["title"],
                "meta_changed": raw["meta_description"] != ren["meta_description"],
                "canonical_changed": raw["canonical"] != ren["canonical"],
                "console_errors": len(rendered.console_errors or []),
            })
        else:
            self._js_diff_dropped += 1
            if not self._js_diff_cap_warned:
                log.warning(
                    f"⚠️ js_diff entries cap ({self._js_diff_cap}) reached — "
                    f"إضافيات لن تُسجَّل. ارفع js_diff_max_entries إن لزم.")
                self._js_diff_cap_warned = True
            increment("crawler.js_diff.cap_dropped")
        increment("crawler.js.rendered")
        # نستخدم النسخة المُصيَّرة للاستخراج واكتشاف الروابط (قيمة JS الحقيقية)
        return rendered_soup, {
            "console_errors": rendered.console_errors or [],
            "network_requests": rendered.network_requests,
        }

    def get_stats(self) -> CrawlStats:
        return self.stats

    def _print_summary(self) -> None:
        from utils.helpers import format_bytes, format_duration

        log.info("=" * 60)
        log.info("✅ انتهى Async Crawler")
        log.info("=" * 60)
        log.info(f"المدة:           {format_duration(self.stats.duration_seconds)}")
        log.info(f"الصفحات:         {self.stats.pages_crawled}")
        log.info(f"فاشلة:           {self.stats.pages_failed}")
        log.info(f"متجاهلة:         {self.stats.pages_skipped}")
        # أخطاء جلب مؤقتة (شبكة/مهلة) أُعيدت المحاولة لها — مرئية في اللوغ كتحذير
        # كي يعرف المستخدم أنها حدثت حتى لو نجحت الصفحات في النهاية.
        if self.stats.fetch_errors:
            log.warning(
                f"⚠️ أخطاء جلب مؤقتة (أُعيدت المحاولة): {self.stats.fetch_errors} "
                f"— راجع metrics.json (crawler.fetch.errors)"
            )
        log.info(f"السرعة:          {self.stats.pages_per_second:.2f} صفحة/ثانية")
        log.info(f"الروابط الداخلية: {self.stats.total_internal_links}")
        log.info(f"الروابط الخارجية: {self.stats.total_external_links}")
        log.info(f"الصور:           {self.stats.total_images}")
        log.info(f"الحجم الإجمالي:   {format_bytes(self.stats.total_bytes)}")

        log.info("\nتوزيع Status Codes:")
        for status, count in sorted(self.stats.status_codes.items()):
            log.info(f"  {status}: {count}")
        log.info("=" * 60)
