"""
analyzers/security_analyzer.py
==============================
فحوص أمان خفيفة على مستوى الترويسات (headers) لكل صفحة.

نبقي هذا بسيطاً عمداً (HTTPS/HSTS/CSP/X-Frame-Options/...) ونرشد المستخدم
إلى OWASP ZAP للفحص العميق (راجع docs/EXTERNAL_TOOLS_GUIDE).
"""

from __future__ import annotations

from typing import Any

from analyzers._coerce import status_of  # v1.09-B2


def _get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


# الترويسة المفقودة → (مفتاح الترويسة في بيانات الـ headers، شدّة المشكلة)
_HEADER_CHECKS = [
    ("hsts_enabled", "HSTS (Strict-Transport-Security)", "high", True),
    ("csp", "Content-Security-Policy", "medium", False),
    ("x_frame_options", "X-Frame-Options", "medium", False),
    ("x_content_type_options", "X-Content-Type-Options", "low", False),
    ("referrer_policy", "Referrer-Policy", "low", False),
    ("permissions_policy", "Permissions-Policy", "low", False),
]


def analyze_security(
    pages: list[Any],
    headers: list[dict[str, Any]],
) -> dict[str, Any]:
    """تحليل أمان الترويسات لكل صفحة HTML ناجحة.

    Returns dict مع issues (صفوف للتصدير) وعدّادات per-header وملخص.
    """
    headers_by_url: dict[str, dict[str, Any]] = {}
    for h in headers:
        url = _get(h, "page_url", "")
        if url:
            headers_by_url[url] = h

    issues: list[dict[str, Any]] = []
    counts = {label: 0 for _, label, _, _ in _HEADER_CHECKS}
    not_https = 0
    pages_checked = 0

    for page in pages:
        status = status_of(page)
        if status != 200:
            continue
        url = _get(page, "url", "")
        if not url:
            continue
        pages_checked += 1

        # HTTPS
        if not url.lower().startswith("https://"):
            not_https += 1
            issues.append({"url": url, "issue": "Not HTTPS", "severity": "high"})

        hdr = headers_by_url.get(url, {})
        for key, label, severity, is_bool in _HEADER_CHECKS:
            val = _get(hdr, key, None)
            present = bool(val) if is_bool else bool(str(val or "").strip())
            if not present:
                counts[label] += 1
                issues.append({"url": url, "issue": f"Missing {label}", "severity": severity})

        # Mixed content (من الزحف)
        if _get(page, "has_mixed_content", False):
            issues.append({"url": url, "issue": "Mixed Content", "severity": "high"})

    return {
        "pages_checked": pages_checked,
        "not_https_count": not_https,
        "missing_header_counts": counts,
        "issues": issues,
        "total_issues": len(issues),
        "summary": {
            "pages_checked": pages_checked,
            "not_https": not_https,
            **{label: counts[label] for label in counts},
        },
    }
