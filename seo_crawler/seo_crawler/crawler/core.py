"""
crawler/core.py
================
المحرّك الأساسي للزحف.

يدير:
- حلقة الزحف الرئيسية
- قائمة الانتظار + visited
- استدعاء الـ extractors
- التعامل مع الأخطاء
- حفظ الحالة دورياً
"""

import os
import signal
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urljoin

from tqdm import tqdm

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BeautifulSoup = None
    BS4_AVAILABLE = False

from crawler.http_client import HTTPClient, HTTPResponse
from crawler.js_renderer import JSRenderer
from crawler.robots_parser import RobotsParser
from crawler.sitemap_parser import SitemapParser

from utils.helpers import (
    format_bytes,
    format_duration,
    is_internal_url,
    is_safe_remote_url,
    matches_any_pattern,
    normalize_url,
)
from utils.logger import get_logger
from utils.state_manager import StateManager

# v1.11 (M-9): hoisted from per-page hot-loop in _extract_page_data().
# جميع modules التالية pure-data بلا cycle مع crawler/.
from extractors.canonical_extractor import extract_canonical
from extractors.content_extractor import extract_content
from extractors.custom_extractor import compile_rules, extract_custom
from extractors.headers_extractor import extract_headers
from extractors.headings_extractor import extract_headings
from extractors.hreflang_extractor import extract_hreflang
from extractors.images_extractor import extract_images
from extractors.links_extractor import extract_links
from extractors.meta_extractor import extract_meta
from extractors.mixed_content import detect_mixed_content
from extractors.og_extractor import extract_og_twitter
from extractors.pagination_extractor import extract_pagination
from extractors.resources_extractor import extract_resources
from extractors.schema_extractor import extract_schema

log = get_logger(__name__)


# ============================================================
# === Data Classes ===
# ============================================================


@dataclass
class PageData:
    """
    كل البيانات المُستخرَجة من صفحة واحدة.
    هذا الكائن يحتوي على كل شيء عن الصفحة.
    """

    # === معلومات أساسية ===
    url: str
    final_url: str = ""
    status_code: int = 0
    content_type: str = ""
    size_bytes: int = 0
    response_time_ms: float = 0.0
    encoding: str = ""
    depth: int = 0
    crawled_at: str = ""

    # === Meta data ===
    title: str = ""
    title_length: int = 0
    title_pixel_width: int = 0
    meta_description: str = ""
    meta_description_length: int = 0
    meta_keywords: str = ""
    meta_robots: str = ""
    meta_viewport: str = ""
    meta_charset: str = ""
    meta_generator: str = ""

    # === Headings ===
    h1_count: int = 0
    h1_text: list[str] = field(default_factory=list)
    h2_count: int = 0
    h2_text: list[str] = field(default_factory=list)
    h3_count: int = 0
    h3_text: list[str] = field(default_factory=list)
    headings_order: list[str] = field(default_factory=list)

    # === Canonical ===
    canonical: str = ""
    canonical_in_header: bool = False
    canonical_is_self: bool = False

    # === Hreflang ===
    hreflang_tags: list[dict[str, str]] = field(default_factory=list)

    # === Pagination (rel=next/prev) ===
    pagination_next: str = ""
    pagination_prev: str = ""
    is_paginated: bool = False

    # === Open Graph & Twitter ===
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""
    og_type: str = ""
    og_url: str = ""
    twitter_card: str = ""
    twitter_title: str = ""
    twitter_description: str = ""
    twitter_image: str = ""

    # === Schema.org ===
    schema_count: int = 0
    schema_types: list[str] = field(default_factory=list)
    schema_data: list[dict] = field(default_factory=list)

    # === Content ===
    word_count: int = 0
    character_count: int = 0
    paragraph_count: int = 0
    text_to_html_ratio: float = 0.0
    language: str = ""
    content_hash: str = ""
    content_simhash: str = ""  # بصمة SimHash للتشابه التقريبي

    # === Counts ===
    internal_links_count: int = 0
    external_links_count: int = 0
    images_count: int = 0
    images_without_alt_count: int = 0
    nofollow_links_count: int = 0

    # === Redirects ===
    redirect_chain: list[tuple[str, int]] = field(default_factory=list)
    is_redirect: bool = False

    # === Mixed Content (HTTP في HTTPS) ===
    has_mixed_content: bool = False
    mixed_content_urls: list[str] = field(default_factory=list)
    mixed_content_active_count: int = 0
    mixed_content_passive_count: int = 0
    mixed_content_form_count: int = 0

    # === Indexability ===
    is_indexable: bool = True
    indexability_reason: str = "Indexable"
    x_robots_tag: str = ""

    # === Headers (مختارة) ===
    server: str = ""
    cache_control: str = ""
    content_encoding: str = ""
    hsts_enabled: bool = False

    # === JavaScript Rendering ===
    js_rendered: bool = False
    js_console_errors: list[str] = field(default_factory=list)
    js_network_requests: int = 0

    # === Errors ===
    crawl_error: Optional[str] = None


@dataclass
class CrawlStats:
    """إحصائيات الزحف الإجمالية."""

    start_time: float = 0.0
    end_time: float = 0.0
    pages_crawled: int = 0
    pages_failed: int = 0
    pages_skipped: int = 0
    fetch_errors: int = 0  # أخطاء جلب مؤقتة (قد تنجح بعد إعادة المحاولة)
    total_internal_links: int = 0
    total_external_links: int = 0
    total_images: int = 0
    total_bytes: int = 0

    status_codes: dict[int, int] = field(default_factory=dict)
    content_types: dict[str, int] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        if self.end_time == 0:
            return time.time() - self.start_time
        return self.end_time - self.start_time

    @property
    def pages_per_second(self) -> float:
        duration = self.duration_seconds
        return self.pages_crawled / duration if duration > 0 else 0


# ============================================================
# === Main Crawler ===
# ============================================================


class Crawler:
    """
    المحرّك الأساسي للزحف.

    Example:
        >>> config = {...}  # من config.yaml
        >>> crawler = Crawler(config)
        >>> crawler.run()
        >>> pages = crawler.get_pages()
        >>> links = crawler.get_links()
    """

    def __init__(self, config: dict[str, Any]):
        """
        Args:
            config: قاموس الإعدادات (محمّل من config.yaml)
        """
        if not BS4_AVAILABLE:
            raise ImportError("bs4 غير مثبت! ثبّت: pip install beautifulsoup4")

        self.config = config
        self.site_config = config["site"]
        self.crawl_config = config["crawl"]
        self.js_config = config.get("javascript", {})
        self.extraction_config = config.get("extraction", {})
        self.filter_config = config.get("filters", {})
        self.state_config = config.get("state", {})
        self.verify_ssl = self.crawl_config.get("verify_ssl", True)
        self.robots_failure_policy = self.crawl_config.get("robots_failure_policy", "allow")
        self.allow_private_hosts = self.crawl_config.get("allow_private_hosts", False)

        # === Domain info ===
        self.start_url = normalize_url(self.site_config["start_url"])
        self.primary_domain = self.site_config["domain"]
        self.additional_domains = self.site_config.get("additional_internal_domains", [])
        # كل روابط الـ sitemaps التي رُئيت (لـ sitemap_diff الكامل)
        self.sitemap_urls_seen: list[str] = []

        # === Custom Extraction (الخطة #5) ===
        ce = config.get("custom_extraction", {}) or {}
        self.custom_rules = compile_rules(ce.get("rules")) if ce.get("enabled") else []
        self._custom_needs_html = any(r.get("type") == "regex" for r in self.custom_rules)
        self.all_custom: list[dict[str, Any]] = []

        # === Resource Inventory (الخطة #3) ===
        self.all_resources: list[dict[str, Any]] = []

        # === Crawl state ===
        self.visited: set[str] = set()
        self.queue: deque[tuple[str, int]] = deque()  # (url, depth)
        self.queued_urls: set[str] = set()  # للتحقق السريع من الوجود في queue
        # v1.13.26 (L4-BUG-3): بذور sitemap مؤجَّلة — لا تُحقَن في الطابور الرئيسيّ
        # عند depth=0 (كان يُفسد تحليل عمق النقرات إذ يبدو كلّ شيء بعمق 0). بدلاً
        # من ذلك تُسحب فقط بعد نضوب اكتشاف BFS كي تأخذ الصفحات عمقها الحقيقيّ من
        # الروابط الداخليّة (نفس تصميم async_core الذي لا يعاني هذا الخلل).
        self._sitemap_seeds: list[str] = []

        # === Results storage ===
        self.pages: list[PageData] = []
        # كل الروابط: from_url, to_url, anchor_text, is_internal, nofollow, etc.
        self.all_links: list[dict[str, Any]] = []
        # كل الصور: page_url, image_src, alt, dimensions, etc.
        self.all_images: list[dict[str, Any]] = []
        # كل headings تفصيلياً
        self.all_headings: list[dict[str, Any]] = []
        # كل schema entries
        self.all_schema: list[dict[str, Any]] = []
        # كل HTTP headers لكل صفحة
        self.all_headers: list[dict[str, Any]] = []
        # كل redirects
        self.all_redirects: list[dict[str, Any]] = []

        # === Statistics ===
        self.stats = CrawlStats()

        # === HTTP client ===
        self.http_client = HTTPClient(
            user_agent=self.crawl_config["user_agent"],
            timeout=self.crawl_config["timeout_seconds"],
            retry_attempts=self.crawl_config["retry_attempts"],
            retry_delay=self.crawl_config["retry_delay_seconds"],
            max_page_size_mb=self.crawl_config["max_page_size_mb"],
            follow_redirects=self.crawl_config["follow_redirects"],
            max_redirects=self.crawl_config["max_redirect_hops"],
            verify_ssl=self.crawl_config.get("verify_ssl", True),
            allow_private_hosts=self.allow_private_hosts,
        )

        # === Robots parser ===
        self.robots: Optional[RobotsParser] = None
        if self.crawl_config["respect_robots"]:
            self.robots = RobotsParser(
                self.start_url,
                self.crawl_config["user_agent"],
                failure_policy=self.robots_failure_policy,
                verify_ssl=self.verify_ssl,
                timeout=self.crawl_config.get("timeout_seconds", 15),
            )

        # === Sitemap parser ===
        self.sitemap_parser = SitemapParser(self.http_client)

        # === JS Renderer (lazy init) ===
        self.js_renderer: Optional[JSRenderer] = None

        # === State manager ===
        self.state_manager = StateManager(self.state_config.get("state_dir", "./state"))

        # === Graceful shutdown ===
        self._stop_requested = False
        self._setup_signal_handlers()

        # === Progress bar ===
        self.progress_bar: Optional[tqdm] = None

    def _setup_signal_handlers(self) -> None:
        """إعداد معالجة Ctrl+C لحفظ الحالة قبل الخروج."""

        def signal_handler(signum, frame):
            log.warning("\nتم استلام إشارة إيقاف. حفظ الحالة...")
            self._stop_requested = True

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    # ========================================================
    # === Public API ===
    # ========================================================

    def run(self) -> None:
        """تشغيل الزحف الكامل."""
        log.info("=" * 60)
        log.info(f"بدء الزحف: {self.start_url}")
        log.info(f"الدومين: {self.primary_domain}")
        log.info(f"الحد الأقصى: {self.crawl_config['max_pages']} صفحة")
        # v1.09-B8: ميزات v1.08 (deferred classifier + Phase 2) غير مدعومة في
        # الزاحف sync — async هو الافتراضي وحيث تُنفَّذ. ننبّه المستخدم بوضوح.
        if (self.crawl_config.get("deferred_crawl", {}) or {}).get("enabled"):
            log.warning(
                "⚠️ deferred_crawl مفعَّل لكنّ الزاحف sync لا يدعمه. الزحفة ستفحص "
                "كلّ الروابط (بما فيها pagination_deep و auth wrappers). استعمل "
                "async (الافتراضي) للحصول على ميزات v1.08."
            )
        log.info("=" * 60)

        self.stats.start_time = time.time()

        try:
            # === مرحلة 1: التحضير ===
            self._prepare()

            # === مرحلة 2: تهيئة JS renderer إذا مطلوب ===
            if self.js_config.get("enabled", False):
                self._start_js_renderer()

            # === مرحلة 3: الزحف ===
            self._crawl_loop()

        finally:
            self.stats.end_time = time.time()
            self._cleanup()
            self._print_summary()

    def get_pages(self) -> list[PageData]:
        """إرجاع كل الصفحات المُزحوفة."""
        return self.pages.copy()

    def get_links(self) -> list[dict[str, Any]]:
        """إرجاع كل الروابط المُكتشفة."""
        return self.all_links.copy()

    def get_images(self) -> list[dict[str, Any]]:
        """إرجاع كل الصور."""
        return self.all_images.copy()

    def get_headings(self) -> list[dict[str, Any]]:
        """إرجاع كل العناوين (H1-H6)."""
        return self.all_headings.copy()

    def get_schema(self) -> list[dict[str, Any]]:
        """إرجاع كل بيانات Schema.org."""
        return self.all_schema.copy()

    def get_headers(self) -> list[dict[str, Any]]:
        """إرجاع كل HTTP headers."""
        return self.all_headers.copy()

    def get_redirects(self) -> list[dict[str, Any]]:
        """إرجاع كل الـ redirects."""
        return self.all_redirects.copy()

    def get_custom_extraction(self) -> list[dict[str, Any]]:
        """إرجاع نتائج الاستخراج المخصّص."""
        return self.all_custom.copy()

    def get_resources(self) -> list[dict[str, Any]]:
        """إرجاع جرد الموارد."""
        return self.all_resources.copy()

    def get_stats(self) -> CrawlStats:
        """إرجاع الإحصائيات."""
        return self.stats

    # ========================================================
    # === Internal Methods ===
    # ========================================================

    def _prepare(self) -> None:
        """التحضير قبل بدء الزحف."""
        # تحميل robots.txt
        if self.robots:
            self.robots.load()

        # استئناف الحالة إن وُجدت
        if (
            self.state_config.get("resume_if_exists", True)
            and self.state_manager.has_saved_session()
        ):
            log.info("استرجاع جلسة محفوظة...")
            visited_loaded, queue_loaded = self.state_manager.load()
            self.visited = visited_loaded
            for url in queue_loaded:
                self.queue.append((url, 0))
                self.queued_urls.add(url)
            log.info(f"تم استرجاع {len(self.visited)} مزحوف، {len(queue_loaded)} في الانتظار")
        else:
            # بدء جديد - مسح أي حالة قديمة
            self.state_manager.clear()

        # إضافة start_url
        if self.start_url not in self.visited and self.start_url not in self.queued_urls:
            self.queue.append((self.start_url, 0))
            self.queued_urls.add(self.start_url)

        # تحميل sitemap وإضافة كل URLs منه
        self._load_sitemaps()

    def _load_sitemaps(self) -> None:
        """تحميل sitemaps وإضافة URLs لقائمة الانتظار."""
        sitemap_urls: list[str] = []

        # من robots.txt
        if self.robots and self.robots.is_loaded():
            sitemap_urls.extend(self.robots.get_sitemaps())

        # المسار الافتراضي
        default_sitemap = urljoin(self.start_url, "/sitemap.xml")
        if default_sitemap not in sitemap_urls:
            sitemap_urls.append(default_sitemap)

        # تحليل كل sitemap
        total_added = 0
        for sitemap_url in sitemap_urls:
            safe, reason = is_safe_remote_url(sitemap_url, self.allow_private_hosts)
            if not safe:
                log.warning(f"تخطّي sitemap غير آمن {sitemap_url}: {reason}")
                continue
            entries = self.sitemap_parser.parse(sitemap_url)
            for entry in entries:
                normalized = normalize_url(entry.url)
                self.sitemap_urls_seen.append(normalized)
                # v1.13.26 (L4-BUG-3): نؤجّل البذور في قائمة منفصلة ولا نضيفها إلى
                # queued_urls — كي يستطيع اكتشاف الروابط الداخليّة (BFS) إدراجها
                # بعمقها الحقيقيّ. تُسحب لاحقاً في _crawl_loop بعد نضوب الطابور فقط
                # لما تبقّى «يتيماً» (غير مكتشَف عبر الروابط).
                if (
                    normalized not in self.visited
                    and not self._should_skip_url(normalized)
                ):
                    self._sitemap_seeds.append(normalized)
                    total_added += 1

        log.info(f"تمّت جدولة {total_added} بذرة sitemap مؤجَّلة")

    def _refill_from_sitemap_seeds(self) -> int:
        """v1.13.26 (L4-BUG-3): سحب بذور sitemap المؤجَّلة إلى الطابور بعد نضوب
        اكتشاف BFS. تُدرَج بعمق 0 (صفحات «يتيمة» لم تُكتشَف عبر الروابط الداخليّة —
        نفس سلوك async_core._refill_from_sitemap). البذور المزحوفة أو المطابِقة
        لأنماط التخطّي تُتجاوز."""
        added = 0
        while self._sitemap_seeds:
            url = self._sitemap_seeds.pop()  # O(1) من النهاية — الترتيب غير مهمّ لليتامى
            if (
                url in self.visited
                or url in self.queued_urls
                or self._should_skip_url(url)
            ):
                continue
            self.queue.append((url, 0))
            self.queued_urls.add(url)
            added += 1
        return added

    def _start_js_renderer(self) -> None:
        """بدء JS Renderer إذا كان مفعّلاً."""
        self.js_renderer = JSRenderer(
            browser=self.js_config.get("browser", "chromium"),
            headless=self.js_config.get("headless", True),
            wait_until=self.js_config.get("wait_until", "networkidle"),
            timeout=self.js_config.get("timeout", 10),
            user_agent=self.crawl_config["user_agent"],
        )
        self.js_renderer.start()

    def _crawl_loop(self) -> None:
        """الحلقة الرئيسية للزحف."""
        max_pages = self.crawl_config["max_pages"]
        max_depth = self.crawl_config["max_depth"]
        delay = self.crawl_config["delay_seconds"]

        # تطبيق Crawl-Delay من robots.txt إذا كان أكبر
        if self.robots:
            robots_delay = self.robots.get_crawl_delay()
            if robots_delay and robots_delay > delay:
                delay = robots_delay
                log.info(f"استخدام Crawl-Delay من robots.txt: {delay}s")

        # شريط التقدم — مُعطّل في وضع الواجهة/بلا طرفية (يتفادى تلويث run.log)
        total_estimate = max_pages if max_pages > 0 else None
        try:
            _is_tty = sys.stdout.isatty()
        except (AttributeError, ValueError):
            _is_tty = False
        quiet_progress = bool(os.environ.get("SCT_PROGRESS_FILE")) or not _is_tty
        self.progress_bar = tqdm(
            total=total_estimate,
            desc="Crawling",
            unit="page",
            dynamic_ncols=True,
            disable=quiet_progress,
        )

        try:
            while not self._stop_requested:
                # v1.13.26 (L4-BUG-3): إن نضب الطابور فقد انتهى اكتشاف BFS —
                # نسحب عندئذٍ بذور sitemap المتبقّية (الصفحات اليتيمة). إن لم
                # يتبقَّ شيء فقد انتهى الزحف.
                if not self.queue:
                    if not self._refill_from_sitemap_seeds():
                        break

                # التحقق من حد الصفحات
                if max_pages > 0 and self.stats.pages_crawled >= max_pages:
                    log.info(f"تم بلوغ الحد الأقصى ({max_pages} صفحة)")
                    break

                url, depth = self.queue.popleft()
                self.queued_urls.discard(url)

                # تخطّي إذا تم زيارته
                if url in self.visited:
                    continue

                # تخطّي إذا تجاوز العمق
                if depth > max_depth:
                    self.stats.pages_skipped += 1
                    continue

                # تخطّي إذا الـ URL في exclude patterns
                if self._should_skip_url(url):
                    self.stats.pages_skipped += 1
                    continue

                # تخطّي إذا robots.txt يمنع
                if self.robots and not self.robots.can_fetch(url):
                    log.debug(f"محظور بـ robots.txt: {url}")
                    self.stats.pages_skipped += 1
                    continue

                # حماية SSRF
                safe, reason = is_safe_remote_url(url, self.allow_private_hosts)
                if not safe:
                    log.debug(f"SSRF blocked {url}: {reason}")
                    self.stats.pages_skipped += 1
                    continue

                # زحف الصفحة
                self._crawl_page(url, depth)
                self.visited.add(url)

                # تحديث progress bar
                self.progress_bar.set_postfix(
                    {
                        "queue": len(self.queue),
                        "ok": sum(1 for p in self.pages if 200 <= p.status_code < 300),
                        "errors": self.stats.pages_failed,
                    }
                )
                self.progress_bar.update(1)

                # حفظ دوري للحالة
                save_interval = self.state_config.get("save_interval", 50)
                if self.stats.pages_crawled % save_interval == 0:
                    self.state_manager.save(self.visited, [u for u, _ in self.queue])

                # تأخير بين الطلبات
                if delay > 0:
                    time.sleep(delay)

        finally:
            if self.progress_bar is not None:
                self.progress_bar.close()

            # حفظ نهائي
            self.state_manager.save(self.visited, [u for u, _ in self.queue])

    def _crawl_page(self, url: str, depth: int) -> None:
        """زحف صفحة واحدة واستخراج كل البيانات."""
        try:
            # === جلب الصفحة ===
            response = self.http_client.get(url)

            # تسجيل status code في الإحصائيات
            self.stats.status_codes[response.status_code] = (
                self.stats.status_codes.get(response.status_code, 0) + 1
            )

            # إذا فشل الطلب
            if response.error:
                self._record_failed_page(url, depth, response)
                self.stats.pages_failed += 1
                return

            # إذا redirect — سجّله ولكن استمر (دلالة موحّدة: to_url = القفزة التالية)
            if response.redirect_chain:
                chain = response.redirect_chain
                for i, (from_url, status) in enumerate(chain):
                    # to_url للقفزة = مصدر القفزة التالية، وآخر قفزة → الوجهة النهائية
                    to_url = chain[i + 1][0] if i + 1 < len(chain) else response.final_url
                    self.all_redirects.append(
                        {
                            "from_url": from_url,
                            "to_url": to_url,
                            "status_code": status,
                            "chain_length": len(chain),
                            "original_url": url,
                        }
                    )

            # لا نتحلّل المحتوى إذا ليس HTML
            if response.content_type and not self._is_html_content(response.content_type):
                self._record_non_html_page(url, depth, response)
                self.stats.pages_crawled += 1
                return

            # === JS Rendering (إذا مفعّل) ===
            html_content = response.text
            js_data = {}
            if self.js_renderer and response.is_success:
                rendered = self.js_renderer.render(url)
                if rendered.is_success:
                    html_content = rendered.html
                    js_data = {
                        "js_rendered": True,
                        "js_console_errors": rendered.console_errors,
                        "js_network_requests": rendered.network_requests,
                    }

            # === تحليل HTML ===
            soup = BeautifulSoup(html_content, "lxml")

            # === استخراج كل البيانات ===
            page_data = self._extract_all(url, depth, response, soup, js_data)
            self.pages.append(page_data)
            self.stats.pages_crawled += 1
            self.stats.total_bytes += response.size_bytes

            # === اكتشاف روابط جديدة وإضافتها للقائمة ===
            self._discover_new_links(page_data, soup, depth)

        except Exception as e:
            log.error(f"خطأ غير متوقع في {url}: {e}", exc_info=True)
            self.stats.pages_failed += 1

    def _extract_all(
        self,
        url: str,
        depth: int,
        response: HTTPResponse,
        soup: BeautifulSoup,
        js_data: dict,
    ) -> PageData:
        """استخراج كل البيانات الممكنة من الصفحة."""
        page = PageData(
            url=url,
            final_url=response.final_url,
            status_code=response.status_code,
            content_type=response.content_type,
            size_bytes=response.size_bytes,
            response_time_ms=response.elapsed_ms,
            encoding=response.encoding,
            depth=depth,
            crawled_at=datetime.now(timezone.utc).isoformat(),  # v1.13.26 (L4-BUG-5): UTC واعٍ بالمنطقة
            redirect_chain=response.redirect_chain,
            is_redirect=bool(response.redirect_chain),
        )

        if self._extract_enabled("meta"):
            meta = extract_meta(soup)
            page.title = meta["title"]
            page.title_length = meta["title_length"]
            page.title_pixel_width = meta["title_pixel_width"]
            page.meta_description = meta["meta_description"]
            page.meta_description_length = meta["meta_description_length"]
            page.meta_keywords = meta["meta_keywords"]
            page.meta_robots = meta["meta_robots"]
            page.meta_viewport = meta["meta_viewport"]
            page.meta_charset = meta["meta_charset"]
            page.meta_generator = meta["meta_generator"]

        if self._extract_enabled("headings"):
            headings = extract_headings(soup)
            page.h1_count = headings["h1_count"]
            page.h1_text = headings["h1_text"]
            page.h2_count = headings["h2_count"]
            page.h2_text = headings["h2_text"]
            page.h3_count = headings["h3_count"]
            page.h3_text = headings["h3_text"]
            page.headings_order = headings["order"]
            for heading in headings["detailed"]:
                self.all_headings.append({"page_url": url, **heading})

        if self._extract_enabled("canonical"):
            canonical_data = extract_canonical(soup, response.headers, url)
            page.canonical = canonical_data["canonical"]
            page.canonical_in_header = canonical_data["in_header"]
            page.canonical_is_self = canonical_data["is_self"]

        if self._extract_enabled("hreflang"):
            page.hreflang_tags = extract_hreflang(soup, response.headers, url)

        if self._extract_enabled("pagination"):
            pg = extract_pagination(soup, response.headers, url)
            page.pagination_next = pg["pagination_next"]
            page.pagination_prev = pg["pagination_prev"]
            page.is_paginated = pg["is_paginated"]

        if self._extract_enabled("og"):
            og_data = extract_og_twitter(soup)
            page.og_title = og_data["og_title"]
            page.og_description = og_data["og_description"]
            page.og_image = og_data["og_image"]
            page.og_type = og_data["og_type"]
            page.og_url = og_data["og_url"]
            page.twitter_card = og_data["twitter_card"]
            page.twitter_title = og_data["twitter_title"]
            page.twitter_description = og_data["twitter_description"]
            page.twitter_image = og_data["twitter_image"]

        if self._extract_enabled("schema"):
            schema_data = extract_schema(soup)
            page.schema_count = schema_data["count"]
            page.schema_types = schema_data["types"]
            page.schema_data = schema_data["raw"]
            for item in schema_data["entries"]:
                self.all_schema.append({"page_url": url, **item})

        if self._extract_enabled("content"):
            content_data = extract_content(soup, response.size_bytes)
            page.word_count = content_data["word_count"]
            page.character_count = content_data["character_count"]
            page.paragraph_count = content_data["paragraph_count"]
            page.text_to_html_ratio = content_data["text_to_html_ratio"]
            page.language = content_data["language"]
            page.content_hash = content_data["content_hash"]
            page.content_simhash = content_data.get("content_simhash", "")

        if self._extract_enabled("images"):
            images = extract_images(soup, url)
            page.images_count = len(images)
            page.images_without_alt_count = sum(1 for img in images if not img["alt"])
            for img in images:
                self.all_images.append({"page_url": url, **img})

        if self._extract_enabled("links"):
            links = extract_links(soup, url, self.primary_domain, self.additional_domains)
            page.internal_links_count = sum(1 for link in links if link["is_internal"])
            page.external_links_count = sum(1 for link in links if not link["is_internal"])
            page.nofollow_links_count = sum(1 for link in links if link["nofollow"])
            for link in links:
                self.all_links.append({"from_url": url, **link})

        self.stats.total_internal_links += page.internal_links_count
        self.stats.total_external_links += page.external_links_count
        self.stats.total_images += page.images_count

        if self._extract_enabled("headers"):
            headers_data = extract_headers(response.headers)
            page.server = headers_data["server"]
            page.cache_control = headers_data["cache_control"]
            page.content_encoding = headers_data["content_encoding"]
            page.hsts_enabled = headers_data["hsts_enabled"]
            page.x_robots_tag = headers_data["x_robots_tag"]
            self.all_headers.append(
                {"page_url": url, "all_headers": dict(response.headers), **headers_data}
            )

        # === Indexability ===
        page.is_indexable, page.indexability_reason = self._check_indexability(
            page.status_code, page.meta_robots, page.x_robots_tag, page.canonical, url
        )

        # === JS data ===
        if js_data:
            page.js_rendered = js_data.get("js_rendered", False)
            page.js_console_errors = js_data.get("js_console_errors", [])
            page.js_network_requests = js_data.get("js_network_requests", 0)

        if self._extract_enabled("mixed_content"):
            mixed = detect_mixed_content(soup, url)
            page.has_mixed_content = mixed["has_mixed_content"]
            page.mixed_content_urls = mixed.get("mixed_urls", [])
            page.mixed_content_active_count = mixed.get("active_count", 0)
            page.mixed_content_passive_count = mixed.get("passive_count", 0)
            page.mixed_content_form_count = mixed.get("form_count", 0)

        # === Custom Extraction (الخطة #5) ===
        if self.custom_rules:
            html_for_rules = str(soup) if self._custom_needs_html else ""
            vals = extract_custom(soup, html_for_rules, self.custom_rules)
            self.all_custom.append({"page_url": url, **vals})

        # === Resource Inventory (الخطة #3) — معطّل افتراضياً ===
        if self.extraction_config.get("extract_resources", False):
            self.all_resources.extend(
                extract_resources(soup, url, self.primary_domain, self.additional_domains)
            )

        return page

    def _discover_new_links(
        self, page: PageData, soup: BeautifulSoup, depth: int
    ) -> None:
        """اكتشاف الروابط الداخلية الجديدة وإضافتها للقائمة."""
        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href", "").strip()
            if not href:
                continue

            # حل URL مطلق
            absolute_url = urljoin(page.final_url or page.url, href)
            normalized = normalize_url(absolute_url)

            # تخطّي إذا غير داخلي
            if not is_internal_url(normalized, self.primary_domain, self.additional_domains):
                continue

            # تخطّي إذا تم زيارته أو في القائمة
            if normalized in self.visited or normalized in self.queued_urls:
                continue

            # تخطّي إذا في exclude patterns
            if self._should_skip_url(normalized):
                continue

            # احترام nofollow إذا كان مطلوباً
            if self.filter_config.get("respect_nofollow", False):
                rel = a_tag.get("rel", [])
                if isinstance(rel, str):
                    rel = rel.split()
                if "nofollow" in rel:
                    continue

            # أضف للقائمة
            self.queue.append((normalized, depth + 1))
            self.queued_urls.add(normalized)

    def _should_skip_url(self, url: str) -> bool:
        """التحقق من exclude/include patterns."""
        exclude = self.filter_config.get("exclude_patterns", [])
        include = self.filter_config.get("include_patterns", [])

        if exclude and matches_any_pattern(url, exclude):
            return True

        if include and not matches_any_pattern(url, include):
            return True

        return False

    def _is_html_content(self, content_type: str) -> bool:
        """التحقق هل النوع HTML."""
        allowed = self.filter_config.get(
            "allowed_content_types", ["text/html", "application/xhtml+xml"]
        )
        return any(ct in content_type for ct in allowed)

    def _extract_enabled(self, name: str) -> bool:
        """هل extractor معيّن مفعّل من config؟"""
        return self.extraction_config.get(f"extract_{name}", True)

    def _check_indexability(
        self,
        status_code: int,
        meta_robots: str,
        x_robots_tag: str,
        canonical: str,
        current_url: str,
    ) -> tuple[bool, str]:
        """تحديد هل الصفحة قابلة للفهرسة وأسباب عدم الفهرسة."""
        if status_code != 200:
            return False, f"Non-200 status: {status_code}"

        combined_robots = (meta_robots + " " + x_robots_tag).lower()
        if "noindex" in combined_robots:
            return False, "Noindex directive"

        if canonical and canonical != current_url and canonical != normalize_url(current_url):
            return True, "Canonicalised"  # قابل لكن يشير لصفحة أخرى

        return True, "Indexable"

    def _record_failed_page(self, url: str, depth: int, response: HTTPResponse) -> None:
        """تسجيل صفحة فشلت."""
        page = PageData(
            url=url,
            status_code=response.status_code,
            depth=depth,
            crawled_at=datetime.now(timezone.utc).isoformat(),  # v1.13.26 (L4-BUG-5): UTC واعٍ بالمنطقة
            crawl_error=response.error,
            is_indexable=False,
            indexability_reason=response.error or f"Status {response.status_code}",
        )
        self.pages.append(page)

    def _record_non_html_page(
        self, url: str, depth: int, response: HTTPResponse
    ) -> None:
        """تسجيل صفحة غير HTML (PDF, image, etc.)."""
        page = PageData(
            url=url,
            final_url=response.final_url,
            status_code=response.status_code,
            content_type=response.content_type,
            size_bytes=response.size_bytes,
            response_time_ms=response.elapsed_ms,
            depth=depth,
            crawled_at=datetime.now(timezone.utc).isoformat(),  # v1.13.26 (L4-BUG-5): UTC واعٍ بالمنطقة
            is_indexable=False,
            indexability_reason=f"Non-HTML: {response.content_type}",
        )
        self.pages.append(page)

    def _cleanup(self) -> None:
        """تنظيف الموارد."""
        if self.js_renderer:
            self.js_renderer.stop()
        self.http_client.close()

    def _print_summary(self) -> None:
        """طباعة ملخص الزحف."""

        log.info("=" * 60)
        log.info("انتهى الزحف")
        log.info("=" * 60)
        log.info(f"المدة:           {format_duration(self.stats.duration_seconds)}")
        log.info(f"الصفحات:         {self.stats.pages_crawled}")
        log.info(f"فاشلة:           {self.stats.pages_failed}")
        log.info(f"متجاهلة:         {self.stats.pages_skipped}")
        log.info(f"السرعة:          {self.stats.pages_per_second:.2f} صفحة/ثانية")
        log.info(f"الروابط الداخلية: {self.stats.total_internal_links}")
        log.info(f"الروابط الخارجية: {self.stats.total_external_links}")
        log.info(f"الصور:           {self.stats.total_images}")
        log.info(f"الحجم الإجمالي:   {format_bytes(self.stats.total_bytes)}")

        log.info("\nتوزيع Status Codes:")
        for status, count in sorted(self.stats.status_codes.items()):
            log.info(f"  {status}: {count}")
        log.info("=" * 60)
