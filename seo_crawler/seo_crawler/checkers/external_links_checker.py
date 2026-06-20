"""
checkers/external_links_checker.py
====================================
فحص حالة الروابط الخارجية (هل تعمل أم 404).

يستخدم Async (aiohttp) لفحص آلاف الروابط بسرعة.
يقوم بـ HEAD requests (أسرع من GET، لا يحمّل المحتوى).
"""

import asyncio
from typing import Any, Callable, Optional
from urllib.parse import urlparse

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

from tqdm import tqdm

from utils.logger import get_logger
from utils.monitoring import gauge, increment, span

log = get_logger(__name__)

# حالات تعني "محظور/مُقيَّد" غالباً (حجب bots) لا "مكسور": لا نعدّها أعطالاً
# لأن مواقع مثل twitter.com/linkedin ترفض طلبات الـ bots بـ 403/401/429.
BLOCKED_STATUSES = frozenset({401, 403, 429})


def _is_broken_status(status: int) -> bool:
    return status >= 400 and status not in BLOCKED_STATUSES


class ExternalLinksChecker:
    """
    فاحص الروابط الخارجية باستخدام Async.

    Example:
        >>> checker = ExternalLinksChecker(timeout=10, concurrent=20)
        >>> results = await checker.check_urls(["https://...", ...])
        >>> # كل result: {url, status_code, final_url, error, response_time_ms}
    """

    def __init__(
        self,
        timeout: int = 10,
        concurrent: int = 20,
        user_agent: str = "SEOCrawlerBot/1.0",
        retry_attempts: int = 2,
        verify_ssl: bool = True,
    ):
        """
        Args:
            timeout: المهلة لكل طلب
            concurrent: عدد الطلبات المتزامنة
            user_agent: User-Agent
            retry_attempts: عدد المحاولات
            verify_ssl: التحقق من شهادات HTTPS
        """
        self.timeout = timeout
        self.concurrent = concurrent
        self.user_agent = user_agent
        self.retry_attempts = retry_attempts
        self.verify_ssl = verify_ssl

        if not AIOHTTP_AVAILABLE:
            log.error("aiohttp غير مثبت! ثبّت: pip install aiohttp")

    async def check_urls(
        self,
        urls: list[str],
        progress: bool = True,
        progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> list[dict[str, Any]]:
        """
        فحص قائمة URLs بشكل متزامن.

        Args:
            urls: قائمة الروابط
            progress: عرض progress bar

        Returns:
            list[dict]: كل رابط مع status + معلومات
        """
        if not AIOHTTP_AVAILABLE:
            increment("external_links.aiohttp_missing")
            return [{"url": url, "error": "aiohttp not installed"} for url in urls]

        with span("external_links.check_urls", urls=len(urls), concurrent=self.concurrent):
            # إزالة التكرارات مع الحفاظ على الترتيب
            unique_urls = [
                url for url in dict.fromkeys(urls)
                if self._is_checkable_http_url(url)
            ]
            gauge("external_links.unique_urls", len(unique_urls))
            log.info(f"فحص {len(unique_urls)} رابط خارجي ({self.concurrent} متزامن)")

            # Semaphore للتحكم في عدد الطلبات المتزامنة
            semaphore = asyncio.Semaphore(self.concurrent)

            # Progress bar
            pbar = None
            if progress:
                pbar = tqdm(
                    total=len(unique_urls),
                    desc="External Links",
                    unit="link",
                    dynamic_ncols=True,
                )

            timeout_obj = aiohttp.ClientTimeout(total=self.timeout)
            connector = aiohttp.TCPConnector(
                limit=self.concurrent,
                limit_per_host=5,  # لا نُرهق نفس السيرفر
                enable_cleanup_closed=True,
            )

            async with aiohttp.ClientSession(
                timeout=timeout_obj,
                connector=connector,
                headers={"User-Agent": self.user_agent},
            ) as session:
                tasks = [
                    self._check_one(session, url, semaphore, pbar, progress_callback, len(unique_urls))
                    for url in unique_urls
                ]
                results = await asyncio.gather(*tasks, return_exceptions=False)

            if pbar:
                pbar.close()

            # إحصائيات
            ok_count = sum(1 for r in results if 200 <= r.get("status_code", 0) < 400)
            broken_count = sum(1 for r in results if r.get("is_broken"))
            blocked_count = sum(1 for r in results if r.get("is_blocked"))
            error_count = sum(1 for r in results if r.get("error"))
            gauge("external_links.ok", ok_count)
            gauge("external_links.broken", broken_count)
            gauge("external_links.blocked", blocked_count)
            gauge("external_links.errors", error_count)

            log.info(
                f"✅ نجح: {ok_count} | ❌ مكسور: {broken_count} | "
                f"🚫 محظور (bot): {blocked_count} | ⚠️ خطأ: {error_count}"
            )

            return results

    async def _check_one(
        self,
        session: "aiohttp.ClientSession",
        url: str,
        semaphore: asyncio.Semaphore,
        pbar: Optional[tqdm],
        progress_callback: Optional[Callable[[dict[str, Any]], None]],
        total_urls: int,
    ) -> dict[str, Any]:
        """فحص رابط واحد."""
        import time

        async with semaphore:
            with span("external_link.check_one", url=url):
                result = {
                    "url": url,
                    "status_code": 0,
                    "final_url": "",
                    "response_time_ms": 0.0,
                    "error": None,
                    "is_broken": False,
                    "is_blocked": False,
                    "is_redirect": False,
                }

                for attempt in range(self.retry_attempts + 1):
                    increment("external_links.attempts")
                    try:
                        start = time.time()

                        # محاولة HEAD أولاً (أسرع)
                        async with session.head(
                            url,
                            allow_redirects=True,
                            ssl=self.verify_ssl,
                        ) as response:
                            elapsed = (time.time() - start) * 1000

                            result["status_code"] = response.status
                            result["final_url"] = str(response.url)
                            result["response_time_ms"] = round(elapsed, 2)
                            result["is_redirect"] = result["final_url"] != url
                            result["is_broken"] = _is_broken_status(response.status)
                            result["is_blocked"] = response.status in BLOCKED_STATUSES
                            increment(f"external_links.status.{response.status}")
                            break  # نجح

                    except aiohttp.ClientResponseError as e:
                        # بعض السيرفرات لا تدعم HEAD، جرّب GET
                        if e.status == 405 and attempt == 0:
                            try:
                                start = time.time()
                                async with session.get(
                                    url,
                                    allow_redirects=True,
                                    ssl=self.verify_ssl,
                                    # نقرأ أول KB فقط
                                ) as response:
                                    elapsed = (time.time() - start) * 1000
                                    result["status_code"] = response.status
                                    result["final_url"] = str(response.url)
                                    result["response_time_ms"] = round(elapsed, 2)
                                    result["is_redirect"] = result["final_url"] != url
                                    result["is_broken"] = _is_broken_status(response.status)
                                    result["is_blocked"] = response.status in BLOCKED_STATUSES
                                    increment(f"external_links.status.{response.status}")
                                break
                            except Exception as ge:
                                result["error"] = f"GET failed: {type(ge).__name__}"
                        else:
                            result["error"] = f"HTTP {e.status}: {str(e)[:100]}"
                            result["status_code"] = e.status
                            result["is_broken"] = _is_broken_status(e.status)
                            result["is_blocked"] = e.status in BLOCKED_STATUSES
                            increment(f"external_links.status.{e.status}")

                    except asyncio.TimeoutError:
                        result["error"] = f"Timeout after {self.timeout}s"
                        increment("external_links.timeouts")
                        if attempt < self.retry_attempts:
                            await asyncio.sleep(1)
                            continue
                        result["is_broken"] = True

                    except aiohttp.ClientError as e:
                        result["error"] = f"{type(e).__name__}: {str(e)[:100]}"
                        increment("external_links.client_errors")
                        if attempt < self.retry_attempts:
                            await asyncio.sleep(1)
                            continue
                        result["is_broken"] = True

                    except Exception as e:
                        result["error"] = f"{type(e).__name__}: {str(e)[:100]}"
                        result["is_broken"] = True
                        increment("external_links.unexpected_errors")
                        log.warning("external link check unexpected error %s", url, exc_info=True)

                if pbar:
                    pbar.update(1)
                    # تحديث postfix
                    if result.get("is_broken"):
                        pbar.set_postfix({"last": "❌ broken"})

                if progress_callback:
                    progress_callback({
                        "checked": 1,
                        "total": total_urls,
                        "broken": 1 if result.get("is_broken") else 0,
                        "blocked": 1 if result.get("is_blocked") else 0,
                        "ok": 1 if 200 <= result.get("status_code", 0) < 400 else 0,
                        "errors": 1 if result.get("error") else 0,
                    })

                return result

    @staticmethod
    def _is_checkable_http_url(url: str) -> bool:
        """استبعاد fragments/روابط خاصة لا يجوز فحصها كروابط خارجية."""
        if not url:
            return False
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        if not parsed.netloc:
            return False
        return True

    def check_urls_sync(self, urls: list[str], progress: bool = True) -> list[dict]:
        """
        Wrapper سهل للاستخدام بدون async/await.

        Example:
            >>> checker = ExternalLinksChecker()
            >>> results = checker.check_urls_sync(urls)
        """
        try:
            # محاولة استخدام loop موجود
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # نحن داخل async context
                raise RuntimeError(
                    "استخدم await checker.check_urls() داخل async function"
                )
        except RuntimeError:
            # ننشئ loop جديد
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        try:
            return loop.run_until_complete(self.check_urls(urls, progress))
        finally:
            loop.close()
