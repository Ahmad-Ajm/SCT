"""
crawler/http_client.py
=======================
عميل HTTP موحّد مع:
- إعادة المحاولة عند الفشل (retry with backoff)
- إدارة جلسة (Session) لإعادة استخدام الاتصالات
- معالجة Redirects بشكل صريح
- حدود حجم الصفحة
- timeout مرن
"""

import time
from dataclasses import dataclass, field
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class HTTPResponse:
    """
    نتيجة طلب HTTP موحّدة.

    Attributes:
        url: الرابط الأصلي
        final_url: الرابط النهائي (بعد redirects)
        status_code: كود الحالة
        content: محتوى الصفحة (bytes)
        text: المحتوى كنص
        headers: HTTP headers
        elapsed_ms: زمن الاستجابة بالمللي ثانية
        content_type: نوع المحتوى
        size_bytes: حجم المحتوى
        encoding: ترميز النص
        redirect_chain: سلسلة redirects (URLs + status codes)
        error: رسالة خطأ إن وُجدت
        is_success: هل الطلب نجح؟
    """

    url: str
    final_url: str = ""
    status_code: int = 0
    content: bytes = b""
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    content_type: str = ""
    size_bytes: int = 0
    encoding: str = ""
    redirect_chain: list[tuple[str, int]] = field(default_factory=list)
    error: Optional[str] = None
    is_success: bool = False


class HTTPClient:
    """
    عميل HTTP محسّن للزحف.

    Example:
        >>> client = HTTPClient(user_agent="MyBot/1.0", timeout=10)
        >>> response = client.get("https://example.com")
        >>> if response.is_success:
        ...     print(response.text)
    """

    def __init__(
        self,
        user_agent: str = "SEOCrawlerBot/1.0",
        timeout: int = 15,
        retry_attempts: int = 3,
        retry_delay: int = 2,
        max_page_size_mb: int = 10,
        follow_redirects: bool = True,
        max_redirects: int = 5,
        verify_ssl: bool = True,
        allow_private_hosts: bool = False,
    ):
        """
        Args:
            user_agent: السلسلة المُعرِّفة للزاحف
            timeout: المهلة الزمنية بالثواني
            retry_attempts: عدد محاولات إعادة الطلب
            retry_delay: التأخير بين المحاولات
            max_page_size_mb: الحد الأقصى لحجم الصفحة
            follow_redirects: تتبع redirects تلقائياً
            max_redirects: الحد الأقصى لعدد redirects
            verify_ssl: التحقق من شهادات HTTPS
        """
        self.user_agent = user_agent
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.max_page_size = max_page_size_mb * 1024 * 1024
        self.follow_redirects = follow_redirects
        self.max_redirects = max_redirects
        self.verify_ssl = verify_ssl
        self.allow_private_hosts = allow_private_hosts

        # إنشاء جلسة دائمة لإعادة استخدام الاتصالات (أسرع)
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """إنشاء جلسة HTTP مع retry adapter."""
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "ar,en;q=0.9",
                # نتجنّب br (brotli) لضمان فك الترميز محلياً (gzip/deflate فقط)
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
            }
        )

        # إعداد retry strategy على مستوى الجلسة
        retry_strategy = Retry(
            total=self.retry_attempts,
            backoff_factor=self.retry_delay,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def get(self, url: str, stream: bool = False) -> HTTPResponse:
        """
        إرسال طلب GET.

        Args:
            url: الرابط
            stream: هل نحمّل المحتوى دفعة واحدة أم تدريجياً

        Returns:
            HTTPResponse: النتيجة الموحّدة
        """
        result = HTTPResponse(url=url)

        try:
            start_time = time.time()

            # تتبع redirect chain يدوياً (للحصول على كل step)
            redirect_chain = []
            current_url = url
            visited_urls = set()

            for hop in range(self.max_redirects + 1):
                if current_url in visited_urls:
                    result.error = f"Redirect loop detected at: {current_url}"
                    log.warning(result.error)
                    return result

                visited_urls.add(current_url)

                # طلب بدون auto-follow لنتتبع كل خطوة
                # stream=True دائماً لقراءة المحتوى تدريجياً مع سقف حجم (إصلاح L2)
                response = self.session.get(
                    current_url,
                    timeout=self.timeout,
                    allow_redirects=False,
                    stream=True,
                    verify=self.verify_ssl,
                )

                # إذا كان redirect
                if 300 <= response.status_code < 400 and self.follow_redirects:
                    redirect_chain.append((current_url, response.status_code))
                    next_url = response.headers.get("Location")
                    if not next_url:
                        # redirect بلا Location: نتركه للمعالجة النهائية (ستغلقه)
                        break
                    # حل redirect نسبي
                    from urllib.parse import urljoin
                    next_url = urljoin(current_url, next_url)
                    # حماية SSRF على وجهة الـ redirect
                    from utils.helpers import is_safe_remote_url
                    safe, ssrf_reason = is_safe_remote_url(next_url, self.allow_private_hosts)
                    # تحرير اتصال الـ redirect الوسيط قبل الانتقال للقفزة التالية
                    # (stream=True يُبقي الاتصال مفتوحاً حتى نقرأ المحتوى أو نُغلق)
                    response.close()
                    if not safe:
                        result.error = f"Redirect to unsafe URL: {ssrf_reason}"
                        log.warning(f"{url}: {result.error}")
                        return result
                    current_url = next_url
                    continue

                # وصلنا للوجهة النهائية
                break
            else:
                # تجاوز عدد redirects المسموح
                result.error = f"Too many redirects (>{self.max_redirects})"
                log.warning(f"{url}: {result.error}")
                return result

            # === معالجة الاستجابة النهائية ===
            elapsed_ms = (time.time() - start_time) * 1000

            # التحقق من حجم الصفحة عبر Content-Length إن وُجد
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > self.max_page_size:
                result.error = f"Page too large: {content_length} bytes"
                log.warning(f"{url}: {result.error}")
                result.status_code = response.status_code
                response.close()
                return result

            # قراءة المحتوى تدريجياً مع سقف حجم (حماية من الاستجابات chunked الضخمة)
            chunks: list[bytes] = []
            total = 0
            too_large = False
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total > self.max_page_size:
                    too_large = True
                    break
            response.close()
            if too_large:
                result.error = f"Page too large (>{self.max_page_size} bytes)"
                log.warning(f"{url}: {result.error}")
                result.status_code = response.status_code
                return result
            content = b"".join(chunks)

            # تحديد الترميز
            encoding = response.encoding or "utf-8"
            try:
                text = content.decode(encoding, errors="replace")
            except (LookupError, TypeError):
                text = content.decode("utf-8", errors="replace")
                encoding = "utf-8"

            # تعبئة النتيجة
            result.final_url = current_url
            result.status_code = response.status_code
            result.content = content
            result.text = text
            result.headers = dict(response.headers)
            result.elapsed_ms = elapsed_ms
            result.content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
            result.size_bytes = len(content)
            result.encoding = encoding
            result.redirect_chain = redirect_chain
            result.is_success = 200 <= response.status_code < 400

        except requests.exceptions.Timeout:
            result.error = f"Timeout after {self.timeout}s"
            log.warning(f"{url}: {result.error}")

        except requests.exceptions.ConnectionError as e:
            result.error = f"Connection error: {type(e).__name__}"
            log.warning(f"{url}: {result.error}")

        except requests.exceptions.RequestException as e:
            result.error = f"Request failed: {type(e).__name__}: {str(e)[:100]}"
            log.warning(f"{url}: {result.error}")

        except Exception as e:
            result.error = f"Unexpected error: {type(e).__name__}: {str(e)[:100]}"
            log.error(f"{url}: {result.error}")

        return result

    def head(self, url: str) -> HTTPResponse:
        """
        طلب HEAD - يجلب headers فقط بدون body.
        مفيد للتحقق من status codes للروابط الخارجية.

        v1.09-B5: حماية SSRF عبر إعادة التوجيه — `allow_redirects=True` الافتراضي
        يتبع 3xx Location إلى أيّ مضيف، بما فيه `169.254.169.254` (cloud metadata).
        نتبع redirects يدوياً ونفحص كلّ hop بـ`is_safe_remote_url`.
        """
        result = HTTPResponse(url=url)

        # v1.09-B5: نُغلق auto-redirect ونديره يدوياً مع فحص أمنيّ على كلّ hop
        from utils.helpers import is_safe_remote_url
        try:
            start_time = time.time()
            current_url = url
            response = None
            for _hop in range(6):  # أقصى 5 redirects (نفس قاعدة المتصفّحات)
                safe, reason = is_safe_remote_url(current_url, False)
                if not safe:
                    result.error = f"SSRF-blocked redirect: {reason}"
                    result.elapsed_ms = (time.time() - start_time) * 1000
                    return result
                response = self.session.head(
                    current_url,
                    timeout=self.timeout,
                    allow_redirects=False,  # B5: نديره يدوياً
                    verify=self.verify_ssl,
                )
                if not self.follow_redirects:
                    break
                if 300 <= response.status_code < 400 and response.headers.get("Location"):
                    from urllib.parse import urljoin
                    current_url = urljoin(current_url, response.headers["Location"])
                    continue
                break
            if response is None:
                result.error = "no response"
                return result
            result.elapsed_ms = (time.time() - start_time) * 1000
            result.status_code = response.status_code
            result.final_url = current_url
            result.headers = dict(response.headers)
            result.content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
            result.is_success = 200 <= response.status_code < 400

        except requests.exceptions.RequestException as e:
            # بعض السيرفرات لا تدعم HEAD، نُسقط بهدوء
            result.error = f"HEAD failed: {type(e).__name__}"
            log.debug(f"{url}: {result.error}")

        return result

    def close(self) -> None:
        """إغلاق الجلسة لتحرير الموارد."""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
