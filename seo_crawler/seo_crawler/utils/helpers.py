"""
utils/helpers.py
================
دوال مساعدة (Utility functions) تُستخدم في كل أنحاء المشروع.
"""

import hashlib
import re
from typing import Optional
from urllib.parse import urlparse, urlunparse, urljoin, parse_qsl, urlencode

try:
    import tldextract
except ImportError:
    tldextract = None


# ============================================================
# === URL Normalization & Validation ===
# ============================================================


def normalize_url(url: str, base_url: Optional[str] = None) -> str:
    """
    توحيد شكل الـ URL لتجنّب اعتبار نفس الصفحة مختلفة.

    التطبيع يشمل:
    - تحويل الـ scheme و host إلى lowercase
    - إزالة fragment (#section)
    - إزالة trailing slash المتعدد
    - فرز query parameters
    - حل الروابط النسبية إلى مطلقة

    Args:
        url: الرابط المطلوب تطبيعه
        base_url: الرابط الأساسي لحل الروابط النسبية (اختياري)

    Returns:
        str: الـ URL المُطبَّع

    Example:
        >>> normalize_url("HTTP://Example.com/Page/?b=2&a=1#anchor")
        'http://example.com/Page/?a=1&b=2'
    """
    # حل الروابط النسبية
    if base_url:
        url = urljoin(base_url, url)

    parsed = urlparse(url)

    # تحويل scheme و netloc إلى lowercase
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # إزالة المنفذ الافتراضي
    if (scheme == "http" and netloc.endswith(":80")) or (
        scheme == "https" and netloc.endswith(":443")
    ):
        netloc = netloc.rsplit(":", 1)[0]

    # تنظيف الـ path
    path = parsed.path or "/"
    # إزالة slashes المتكررة
    path = re.sub(r"/+", "/", path)

    # فرز query parameters
    query_pairs = parse_qsl(parsed.query, keep_blank_values=False)
    # إزالة معاملات التتبع الشائعة
    tracking_params = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
        "fbclid",
        "gclid",
        "msclkid",
        "ref",
        "ref_src",
    }
    query_pairs = [(k, v) for k, v in query_pairs if k not in tracking_params]
    query = urlencode(sorted(query_pairs))

    # بناء الـ URL النهائي (بدون fragment)
    normalized = urlunparse((scheme, netloc, path, parsed.params, query, ""))

    return normalized


def is_internal_url(
    url: str, primary_domain: str, additional_domains: Optional[list[str]] = None
) -> bool:
    """
    التحقق هل الـ URL داخلي (نفس الموقع).

    Args:
        url: الرابط المطلوب فحصه
        primary_domain: الدومين الأساسي للموقع
        additional_domains: نطاقات إضافية تُعتبر داخلية

    Returns:
        bool: True إذا كان داخلياً
    """
    if not url:
        return False

    parsed = urlparse(url)

    # روابط نسبية = داخلية
    if not parsed.netloc:
        return True

    # تطبيع الدومين
    domain = parsed.netloc.lower()

    # إزالة منفذ
    if ":" in domain:
        domain = domain.split(":")[0]

    # إزالة www.
    primary_clean = primary_domain.lower().replace("www.", "")
    domain_clean = domain.replace("www.", "")

    # التطابق الكامل أو subdomain
    if domain_clean == primary_clean or domain_clean.endswith("." + primary_clean):
        return True

    # نطاقات إضافية
    if additional_domains:
        for extra in additional_domains:
            extra_clean = extra.lower().replace("www.", "")
            if domain_clean == extra_clean or domain_clean.endswith("." + extra_clean):
                return True

    return False


def get_domain(url: str) -> str:
    """استخراج الدومين من URL (مثل: example.com)."""
    if tldextract is not None:
        extracted = tldextract.extract(url)
        if extracted.suffix:
            return f"{extracted.domain}.{extracted.suffix}"
        return extracted.domain

    hostname = urlparse(url).hostname or ""
    hostname = hostname.lower().removeprefix("www.")
    parts = hostname.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return hostname


def url_depth(url: str, start_url: str) -> int:
    """
    حساب عمق الـ URL بالنسبة لـ start_url (عدد الـ /).

    Example:
        >>> url_depth("https://example.com/a/b/c", "https://example.com/")
        3
    """
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return 0
    return len([p for p in path.split("/") if p])


# ============================================================
# === Text Processing ===
# ============================================================


def pixel_width_estimate(text: str, font_size: int = 13) -> int:
    """
    تقدير عرض النص بالـ pixels (يستخدمه Google لـ SERP).

    Google يقتطع titles عند ~600 pixel.
    هذه دالة تقريبية، تستخدم متوسط عرض الحرف.

    Args:
        text: النص المطلوب قياسه
        font_size: حجم الخط (افتراضي 13px - مشابه لـ Google)

    Returns:
        int: العرض المقدّر بالـ pixels
    """
    if not text:
        return 0

    # متوسط أعراض الحروف (مبسّط)
    char_widths = {
        # حروف ضيقة
        "i": 0.3, "l": 0.3, "I": 0.3, "j": 0.3, "t": 0.4, "f": 0.4,
        " ": 0.3, ".": 0.3, ",": 0.3,
        # حروف عريضة
        "w": 0.9, "W": 1.1, "m": 0.9, "M": 1.0,
        # عربي (تقدير)
        "ا": 0.4, "ل": 0.4, "م": 0.7,
    }

    total = 0.0
    for char in text:
        total += char_widths.get(char, 0.6) * font_size

    return int(total)


def compute_text_hash(text: str) -> str:
    """
    حساب hash للنص (لكشف المحتوى المكرر).

    يُطبَّق النص أولاً (lowercase + إزالة whitespace زائدة).

    ملاحظة: نستخدم blake2b بدلاً من md5 لأنه:
    - أسرع
    - أكثر أماناً (تشتت أفضل)
    - بنفس طول الـ digest المختصر
    """
    if not text:
        return ""

    # تطبيع
    normalized = re.sub(r"\s+", " ", text.lower().strip())
    # blake2b مع digest_size=16 (32 hex chars) - مكافئ تقريباً لـ md5
    return hashlib.blake2b(normalized.encode("utf-8"), digest_size=16).hexdigest()


def safe_filename(text: str, max_length: int = 100) -> str:
    """
    تحويل نص إلى اسم ملف صالح.

    يزيل الحروف الممنوعة في أنظمة الملفات.
    """
    # استبدال الحروف الممنوعة
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    # إزالة whitespace زائد
    cleaned = re.sub(r"\s+", "_", cleaned).strip("_")
    # تقصير
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned or "untitled"


# ============================================================
# === Formatting ===
# ============================================================


def format_bytes(size_bytes: int) -> str:
    """
    تحويل bytes إلى صيغة مقروءة (KB, MB, GB).

    Example:
        >>> format_bytes(1536)
        '1.5 KB'
    """
    if size_bytes == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    unit_index = 0

    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    return f"{size:.2f} {units[unit_index]}"


def format_duration(seconds: float) -> str:
    """
    تحويل ثوانٍ إلى صيغة مقروءة (1h 23m 45s).
    """
    if seconds < 60:
        return f"{seconds:.1f}s"

    minutes = int(seconds // 60)
    secs = seconds % 60

    if minutes < 60:
        return f"{minutes}m {secs:.0f}s"

    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours}h {minutes}m {secs:.0f}s"


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """تقصير النص مع إضافة "..." عند تجاوز الحد."""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


# ============================================================
# === Pattern Matching ===
# ============================================================


def matches_any_pattern(url: str, patterns: list[str]) -> bool:
    """التحقق هل الـ URL يطابق أي نمط من القائمة."""
    if not patterns:
        return False
    return any(pattern in url for pattern in patterns)
