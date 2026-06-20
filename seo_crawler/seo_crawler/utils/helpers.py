"""
utils/helpers.py
================
دوال مساعدة (Utility functions) تُستخدم في كل أنحاء المشروع.
"""

import fnmatch
import hashlib
import ipaddress
import posixpath
import re
import socket
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse, urljoin, parse_qsl, urlencode

try:
    import tldextract
except ImportError:
    tldextract = None


def compute_simhash(tokens: list[str], bits: int = 64) -> int:
    """بصمة SimHash للكشف عن التشابه التقريبي بين النصوص (مقاومة للتغييرات الصغيرة).

    نصوص متشابهة تُنتج بصمات متقاربة (مسافة Hamming صغيرة)، بخلاف الـ hash العادي.
    """
    if not tokens:
        return 0
    vector = [0] * bits
    mask = (1 << bits) - 1
    for tok in tokens:
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16) & mask
        for i in range(bits):
            vector[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(bits):
        if vector[i] > 0:
            out |= (1 << i)
    return out


def hamming_distance(a: int, b: int) -> int:
    """عدد البتات المختلفة بين بصمتين (كلّما قلّ زاد التشابه)."""
    return bin(a ^ b).count("1")


# ============================================================
# === URL Normalization & Validation ===
# ============================================================

# معاملات التتبّع الشائعة التي تُزال أثناء التطبيع — ثابت على مستوى الوحدة
# (كان يُعاد بناؤه في كل استدعاء لـ normalize_url داخل حلقات ساخنة).
# v1.07: وسّعنا القائمة من 9 إلى ~30 لتغطية المنصّات الإعلانيّة الكبرى + Google Analytics
# + بريد + شبكات اجتماعية. كلّها آمنة لأنّها لا تُغيّر المحتوى — فقط تتبّع المصدر.
_TRACKING_PARAMS = frozenset({
    # Google Analytics / Ads
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "utm_id", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
    "gclid", "dclid", "gclsrc", "gbraid", "wbraid",
    "_ga", "_gid", "_gac",
    # Microsoft / Bing
    "msclkid",
    # Facebook / Meta
    "fbclid", "_fb", "fb_action_ids", "fb_action_types", "fb_ref",
    # TikTok / Twitter / LinkedIn / Pinterest
    "ttclid", "twclid", "li_fat_id", "epik",
    # Mailchimp / email
    "mc_cid", "mc_eid",
    # Instagram / WhatsApp share
    "igshid",
    # Yandex
    "yclid",
    # Generic referrer / affiliate
    "ref", "ref_src", "ref_url", "referrer", "source", "src",
    "affiliate", "aff", "aff_id", "affiliate_id",
})

# v1.07: معاملات إضافيّة تُحدَّد ديناميكياً (عبر `set_extra_strip_params`) — تُستعمل عند
# تفعيل قالب منصّة معيّنة (Zid/Salla/...) لإزالة sort/order التي تُنتج تكرار محتوى.
# تبقى فارغة افتراضياً (سلوك حالي محافظ على المعلومات).
_EXTRA_STRIP_PARAMS: frozenset[str] = frozenset()


def set_extra_strip_params(params) -> None:
    """v1.07: يُعيّن معاملات إضافيّة تُزال من query string أثناء التطبيع.

    يُستدعى مرّة واحدة من main.py بعد تفعيل platform_preset (إن وُجد). الفائدة:
    تقليل تكرار الـURL في الطابور بسبب فروع لها نفس المحتوى (مثل `?sort_by=price` و
    `?sort_by=name`). كلّ منصّة لها قائمتها (انظر config_presets.PRESETS)."""
    global _EXTRA_STRIP_PARAMS
    _EXTRA_STRIP_PARAMS = frozenset(p.lower() for p in (params or []))


def normalize_url(url: str, base_url: Optional[str] = None) -> str:
    """
    توحيد شكل الـ URL لتجنّب اعتبار نفس الصفحة مختلفة.

    التطبيع يشمل:
    - تحويل الـ scheme و host إلى lowercase
    - إزالة fragment (#section)
    - دمج الشرطات المتكررة وحل segments النسبية (./ و ../)
    - الحفاظ على trailing slash كما هو (لتفادي طلب URL مختلف عن الأصل)
    - فرز query parameters وإزالة معاملات التتبع الشائعة
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
    # حل segments النسبية (./ و ../) مع الحفاظ على trailing slash المقصود
    if "./" in path or path.endswith((".", "..")):
        had_trailing = path.endswith("/") and path != "/"
        path = posixpath.normpath(path)
        if had_trailing and not path.endswith("/"):
            path += "/"

    # فرز query parameters
    query_pairs = parse_qsl(parsed.query, keep_blank_values=False)
    # إزالة معاملات التتبع الشائعة (الثابت معرّف على مستوى الوحدة)
    # v1.07: نُزيل أيضاً معاملات إضافيّة (مثل sort_by) إن فُعِّل platform_preset
    query_pairs = [
        (k, v) for k, v in query_pairs
        if k not in _TRACKING_PARAMS and k.lower() not in _EXTRA_STRIP_PARAMS
    ]
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

    # إزالة www. كبادئة فقط (لا أي ظهور في وسط النطاق)
    primary_clean = _strip_www(primary_domain.lower())
    domain_clean = _strip_www(domain)

    # التطابق الكامل أو subdomain
    if domain_clean == primary_clean or domain_clean.endswith("." + primary_clean):
        return True

    # نطاقات إضافية
    if additional_domains:
        for extra in additional_domains:
            extra_clean = _strip_www(extra.lower())
            if domain_clean == extra_clean or domain_clean.endswith("." + extra_clean):
                return True

    return False


def _strip_www(host: str) -> str:
    """إزالة بادئة www. فقط (وليس أي ظهور للنص في وسط المضيف)."""
    return host[4:] if host.startswith("www.") else host


def is_safe_remote_url(url: str, allow_private: bool = False) -> tuple[bool, str]:
    """
    فحص أمان جلب URL لحماية من SSRF.

    يرفض المخططات غير http/https والمضيفات التي تُحلّ إلى عناوين
    داخلية/loopback/link-local (مثل 169.254.169.254 لميتاداتا السحابة).

    Args:
        url: الرابط المطلوب فحصه
        allow_private: السماح بالعناوين الخاصة (يُستخدم للمواقع الداخلية الموثوقة)

    Returns:
        tuple[bool, str]: (آمن؟, السبب عند الرفض)
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "URL غير صالح"

    if parsed.scheme not in ("http", "https"):
        return False, f"مخطط غير مسموح: {parsed.scheme or 'فارغ'}"

    host = parsed.hostname
    if not host:
        return False, "لا يوجد مضيف"

    if allow_private:
        return True, ""

    # v1.09-B5: تشخيص حرفي للـIP في host (`http://127.0.0.1` لا يحتاج DNS).
    # كان الكود يعتمد فقط على getaddrinfo، والذي قد يرمي الـlookup لـDNS
    # ويفتح ثغرة DNS-rebind. الفحص المباشر يُغلق هذا.
    try:
        # محاولة تفسير host كـIP literal — يلتقط `[::1]` و`127.1` وغيرهما
        ip_literal = ipaddress.ip_address(host.strip("[]"))
        if _is_unsafe_ip(ip_literal):
            return False, f"عنوان داخلي/محجوز: {host}"
    except ValueError:
        pass  # ليس IP literal — نتابع لـDNS resolution

    # حلّ كل عناوين المضيف وافحصها
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        # v1.09-B5: DNS-fails-CLOSED (كان يفشل OPEN — ثغرة أمنيّة).
        # نطاق لا يُحلّ ⇒ نرفض. إن كان النطاق صحيحاً لكنّ الشبكة ساقطة، الخطأ
        # نفسه سيظهر عند الجلب لاحقاً، بدل فتح ثغرة SSRF احتمالاً.
        return False, "تعذّر حلّ المضيف (DNS)"

    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_unsafe_ip(ip):
            return False, f"عنوان داخلي/محجوز: {ip_str}"

    return True, ""


def _is_unsafe_ip(ip: "ipaddress._BaseAddress") -> bool:
    """v1.09-B5: فحص شامل بما في ذلك IPv4-mapped IPv6 (`::ffff:127.0.0.1`).
    الـbypass السابق: `ip.is_loopback` يُرجع False لـmapped IPv6 ⇒ يمرّ ⇒ SSRF.
    """
    # IPv6 يحوي عنوان IPv4 mapped → نفحصه أيضاً
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


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
        if char in char_widths:
            factor = char_widths[char]
        elif "؀" <= char <= "ۿ":
            # نطاق الحروف العربية: تقدير متوسط موحّد
            factor = 0.55
        else:
            factor = 0.6
        total += factor * font_size

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

    # نقرّب للثانية أولاً ثم نحوّل، حتى لا نحصل على "60s" في حقل الثواني
    total_secs = int(round(seconds))
    minutes, secs = divmod(total_secs, 60)

    if minutes < 60:
        return f"{minutes}m {secs}s"

    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m {secs}s"


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


_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def neutralize_formula(value: Any) -> Any:
    """
    تحييد حقن الصيغ (CSV/Excel Formula Injection).

    أي قيمة نصية تبدأ بـ = + - @ أو tab/CR قد تُنفَّذ كصيغة عند فتح الملف
    في Excel/Sheets. نضيف فاصلة عليا بادئة لتعطيلها.
    """
    if isinstance(value, str) and value[:1] in _FORMULA_TRIGGERS:
        return "'" + value
    return value


_GLOB_CHARS = ("*", "?", "[")


def matches_any_pattern(url: str, patterns: list[str]) -> bool:
    """
    التحقق هل الـ URL يطابق أي نمط من القائمة.

    - الأنماط التي تحتوي على أحرف glob (``*``، ``?``، ``[``) تُطابَق بـ glob كامل.
    - الأنماط العادية تُطابَق كاحتواء نصّي (substring) — متوافق مع الإعدادات القديمة.
    """
    if not patterns:
        return False
    for pattern in patterns:
        if any(ch in pattern for ch in _GLOB_CHARS):
            if fnmatch.fnmatch(url, pattern) or fnmatch.fnmatch(url, f"*{pattern}*"):
                return True
        elif pattern in url:
            return True
    return False
