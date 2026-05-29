"""
crawler/js_renderer.py
=======================
تشغيل JavaScript للحصول على HTML الكامل بعد تنفيذ JS.

يستخدم Playwright (Chromium headless).
مهم لمواقع زد لأن جزءاً من المحتوى يُحمَّل ديناميكياً.

تثبيت إضافي مطلوب:
    pip install playwright
    playwright install chromium
"""

from dataclasses import dataclass
from typing import Optional

from utils.logger import get_logger

log = get_logger(__name__)

# Lazy import - لا نُحمّل Playwright إلا عند الحاجة
_playwright_available: Optional[bool] = None


def _check_playwright() -> bool:
    """التحقق من توفّر Playwright."""
    global _playwright_available
    if _playwright_available is None:
        try:
            import playwright.sync_api  # noqa: F401
            _playwright_available = True
        except ImportError:
            _playwright_available = False
            log.warning(
                "Playwright غير مثبت. للتفعيل: pip install playwright && playwright install chromium"
            )
    return _playwright_available


@dataclass
class RenderedPage:
    """نتيجة Rendering مع JavaScript."""

    url: str
    final_url: str = ""
    html: str = ""
    status_code: int = 0
    console_errors: list[str] = None
    network_requests: int = 0
    load_time_ms: float = 0.0
    error: Optional[str] = None
    is_success: bool = False
    accessibility: Optional[dict] = None  # ملخّص axe-core عند تفعيله

    def __post_init__(self):
        if self.console_errors is None:
            self.console_errors = []


class JSRenderer:
    """
    مُنفّذ JavaScript للصفحات.

    يستخدم Playwright لتحميل الصفحة في متصفح Chromium حقيقي،
    ثم يُرجع الـ HTML بعد تنفيذ كل JS.

    Example:
        >>> with JSRenderer() as renderer:
        ...     result = renderer.render("https://example.com/")
        ...     if result.is_success:
        ...         print(result.html)
    """

    def __init__(
        self,
        browser: str = "chromium",
        headless: bool = True,
        wait_until: str = "networkidle",
        timeout: int = 10,
        user_agent: Optional[str] = None,
    ):
        """
        Args:
            browser: نوع المتصفح (chromium / firefox / webkit)
            headless: تشغيل بدون واجهة
            wait_until: متى نعتبر الصفحة جاهزة (load / domcontentloaded / networkidle)
            timeout: المهلة بالثواني
            user_agent: User-Agent مخصص (اختياري)
        """
        self.browser_type = browser
        self.headless = headless
        self.wait_until = wait_until
        self.timeout = timeout * 1000  # Playwright يستخدم ms
        self.user_agent = user_agent

        self._playwright = None
        self._browser = None
        self._context = None

        if not _check_playwright():
            log.error("Playwright غير مثبت — JS Rendering معطّل")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def start(self) -> bool:
        """بدء المتصفح."""
        if not _check_playwright():
            return False

        try:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            browser_launcher = getattr(self._playwright, self.browser_type)
            self._browser = browser_launcher.launch(headless=self.headless)

            context_options = {}
            if self.user_agent:
                context_options["user_agent"] = self.user_agent

            self._context = self._browser.new_context(**context_options)

            log.info(f"تم بدء Playwright {self.browser_type}")
            return True

        except Exception as e:
            log.error(f"فشل بدء Playwright: {e}")
            return False

    def stop(self) -> None:
        """إيقاف المتصفح."""
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
            log.info("تم إيقاف Playwright")
        except Exception as e:
            log.debug(f"خطأ عند إيقاف Playwright: {e}")

    def render(self, url: str) -> RenderedPage:
        """
        تحميل صفحة وتنفيذ JS.

        Args:
            url: الرابط

        Returns:
            RenderedPage: النتيجة مع HTML الكامل
        """
        result = RenderedPage(url=url)

        if not self._context:
            result.error = "Playwright not started"
            return result

        try:
            import time

            page = self._context.new_page()

            # جمع console errors
            console_errors = []
            page.on(
                "pageerror",
                lambda exc: console_errors.append(f"Page error: {exc}"),
            )
            page.on(
                "console",
                lambda msg: console_errors.append(f"Console {msg.type}: {msg.text}")
                if msg.type in ("error", "warning")
                else None,
            )

            # عداد الطلبات
            request_count = [0]
            page.on("request", lambda r: request_count.__setitem__(0, request_count[0] + 1))

            # تحميل الصفحة
            start_time = time.time()
            response = page.goto(url, wait_until=self.wait_until, timeout=self.timeout)
            load_time = (time.time() - start_time) * 1000

            if response is None:
                result.error = "No response"
                page.close()
                return result

            # استخراج البيانات
            result.final_url = page.url
            result.html = page.content()
            result.status_code = response.status
            result.console_errors = [e for e in console_errors if e]
            result.network_requests = request_count[0]
            result.load_time_ms = load_time
            result.is_success = 200 <= response.status < 400

            page.close()

        except Exception as e:
            result.error = f"Render failed: {type(e).__name__}: {str(e)[:200]}"
            log.warning(f"{url}: {result.error}")

        return result


def _check_playwright_async() -> bool:
    """التحقق من توفّر Playwright (async API)."""
    try:
        import playwright.async_api  # noqa: F401
        return True
    except ImportError:
        log.warning(
            "Playwright غير مثبت. للتفعيل: pip install playwright && playwright install chromium"
        )
        return False


class JSRendererAsync:
    """
    مُصيّر JavaScript غير متزامن (Playwright async) — للزاحف async.

    يُشغّل متصفحاً مشتركاً واحداً ويعيد استخدامه عبر صفحات متعددة.
    آمن عند غياب Playwright (is_available=False فيُتخطّى التصيير).
    """

    def __init__(
        self,
        browser: str = "chromium",
        headless: bool = True,
        wait_until: str = "networkidle",
        timeout: int = 15,
        user_agent: str = "SEOCrawlerBot/1.0",
        block_resource_types: Optional[list[str]] = None,
        axe_source: str = "",
        axe_max: int = 0,
    ):
        self.browser_name = browser
        self.headless = headless
        self.wait_until = wait_until
        self.timeout_ms = int(timeout) * 1000
        self.user_agent = user_agent
        self.block_resource_types = set(block_resource_types or [])
        # فحص الوصولية (axe-core) — اختياري؛ يعمل عند توفّر مصدر axe وسقف موجب
        self.axe_source = axe_source or ""
        self.axe_max = int(axe_max or 0)
        self._axe_count = 0
        self._pw = None
        self._browser = None
        self._context = None

    def is_available(self) -> bool:
        return _check_playwright_async()

    async def start(self) -> bool:
        if not self.is_available():
            return False
        try:
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
            launcher = getattr(self._pw, self.browser_name, self._pw.chromium)
            self._browser = await launcher.launch(headless=self.headless)
            self._context = await self._browser.new_context(user_agent=self.user_agent)
            log.info("✅ بدأ مُصيّر JS (async): %s", self.browser_name)
            return True
        except Exception as e:
            log.error("فشل بدء مُصيّر JS: %s", e)
            await self.stop()
            return False

    async def render(self, url: str) -> "RenderedPage":
        result = RenderedPage(url=url)
        if not self._context:
            result.error = "renderer not started"
            return result
        page = None
        try:
            page = await self._context.new_page()
            console_errors: list[str] = []
            requests_count = {"n": 0}
            page.on("console", lambda m: console_errors.append(m.text)
                    if m.type == "error" else None)
            page.on("request", lambda _r: requests_count.__setitem__("n", requests_count["n"] + 1))

            if self.block_resource_types:
                async def _route(route):
                    if route.request.resource_type in self.block_resource_types:
                        await route.abort()
                    else:
                        await route.continue_()
                await page.route("**/*", _route)

            resp = await page.goto(url, wait_until=self.wait_until, timeout=self.timeout_ms)
            html = await page.content()
            result.html = html
            result.final_url = page.url
            result.status_code = resp.status if resp else 0
            result.console_errors = console_errors
            result.network_requests = requests_count["n"]
            result.is_success = True

            # فحص الوصولية (axe-core) على الصفحة الحيّة ضمن السقف
            if self.axe_source and (self.axe_max <= 0 or self._axe_count < self.axe_max):
                try:
                    await page.add_script_tag(content=self.axe_source)
                    axe_raw = await page.evaluate("async () => await axe.run()")
                    from analyzers.accessibility import summarize_axe_results
                    result.accessibility = summarize_axe_results(axe_raw, page.url)
                    self._axe_count += 1
                except Exception as ax:  # noqa: BLE001
                    log.debug("axe-core فشل على %s: %s", url, ax)
        except Exception as e:
            result.error = f"Render failed: {type(e).__name__}: {str(e)[:200]}"
            log.debug("%s: %s", url, result.error)
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass
        return result

    async def stop(self) -> None:
        for obj, closer in ((self._context, "close"), (self._browser, "close"), (self._pw, "stop")):
            if obj is not None:
                try:
                    await getattr(obj, closer)()
                except Exception:
                    pass
        self._context = self._browser = self._pw = None
