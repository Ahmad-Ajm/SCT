"""
extractors/headers_extractor.py
================================
استخراج HTTP Response Headers المهمة لـ SEO والأمان.
"""

from typing import Any


def extract_headers(headers: dict[str, str]) -> dict[str, Any]:
    """
    استخراج وتحليل HTTP Headers.

    Args:
        headers: HTTP response headers (case-insensitive ideally)

    Returns:
        dict مع كل headers المهمة + تحليلات
    """
    # تطبيع المفاتيح إلى lowercase للبحث case-insensitive
    headers_lower = {k.lower(): v for k, v in headers.items()}

    def get(*keys: str) -> str:
        """البحث عن header بعدة أسماء محتملة."""
        for key in keys:
            value = headers_lower.get(key.lower(), "")
            if value:
                return value
        return ""

    # === Server info ===
    server = get("Server")
    powered_by = get("X-Powered-By")

    # === Caching ===
    cache_control = get("Cache-Control")
    expires = get("Expires")
    etag = get("ETag")
    last_modified = get("Last-Modified")
    age = get("Age")

    # === Compression ===
    content_encoding = get("Content-Encoding")
    is_compressed = bool(content_encoding) and content_encoding != "identity"

    # === Security ===
    hsts = get("Strict-Transport-Security")
    hsts_enabled = bool(hsts)
    x_frame_options = get("X-Frame-Options")
    x_content_type_options = get("X-Content-Type-Options")
    csp = get("Content-Security-Policy")
    referrer_policy = get("Referrer-Policy")
    permissions_policy = get("Permissions-Policy", "Feature-Policy")

    # === SEO ===
    x_robots_tag = get("X-Robots-Tag")
    has_noindex_in_header = "noindex" in x_robots_tag.lower() if x_robots_tag else False
    has_nofollow_in_header = "nofollow" in x_robots_tag.lower() if x_robots_tag else False

    # === Other ===
    content_type = get("Content-Type")
    content_length = get("Content-Length")
    content_language = get("Content-Language")
    vary = get("Vary")
    set_cookie = get("Set-Cookie")

    # === CDN detection ===
    cdn = _detect_cdn(headers_lower)

    return {
        # Server
        "server": server,
        "powered_by": powered_by,
        "cdn": cdn,
        # Caching
        "cache_control": cache_control,
        "expires": expires,
        "etag": etag,
        "last_modified": last_modified,
        "age": age,
        "has_cache_headers": bool(cache_control or expires or etag),
        # Compression
        "content_encoding": content_encoding,
        "is_compressed": is_compressed,
        # Security
        "hsts": hsts,
        "hsts_enabled": hsts_enabled,
        "x_frame_options": x_frame_options,
        "x_content_type_options": x_content_type_options,
        "csp": csp,
        "referrer_policy": referrer_policy,
        "permissions_policy": permissions_policy,
        # SEO
        "x_robots_tag": x_robots_tag,
        "has_noindex_in_header": has_noindex_in_header,
        "has_nofollow_in_header": has_nofollow_in_header,
        # Other
        "content_type": content_type,
        "content_length": content_length,
        "content_language": content_language,
        "vary": vary,
        "has_cookies": bool(set_cookie),
    }


def _detect_cdn(headers_lower: dict[str, str]) -> str:
    """كشف CDN المستخدم من Headers."""
    # CloudFlare
    if "cf-ray" in headers_lower or "cf-cache-status" in headers_lower:
        return "CloudFlare"
    # AWS CloudFront
    if "x-amz-cf-id" in headers_lower or "x-amz-cf-pop" in headers_lower:
        return "CloudFront"
    # Akamai
    if "x-akamai-request-id" in headers_lower:
        return "Akamai"
    # Fastly
    if "x-served-by" in headers_lower and "fastly" in headers_lower.get("x-served-by", "").lower():
        return "Fastly"
    # Sucuri
    if "x-sucuri-id" in headers_lower:
        return "Sucuri"
    # Vercel
    if "x-vercel-id" in headers_lower:
        return "Vercel"
    # Netlify
    if "x-nf-request-id" in headers_lower:
        return "Netlify"
    return ""
