"""
analyzers/pagination_analyzer.py
================================
تحليل ترقيم الصفحات (rel=next / rel=prev) على مستوى الموقع.

يكشف:
1. تسلسل غير متبادل: A.next = B لكن B.prev ≠ A (سلسلة مكسورة).
2. هدف next/prev مزحوف لكنه غير سليم (4xx/5xx) أو غير قابل للفهرسة.
3. canonical لا يشير لذاته على صفحة مرقّمة (خطأ شائع: canonical لصفحة 1).

مرجع: ترقيم الصفحات في SEO — كل صفحة في السلسلة يجب أن تكون
قابلة للفهرسة و canonical لذاتها، وروابط next/prev متبادلة.
"""

from typing import Any

from utils.helpers import normalize_url


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """جلب حقل من dict أو dataclass/كائن."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _is_ok_status(status: int) -> bool:
    return 200 <= int(status or 0) < 400


def _is_noindex(page: Any) -> bool:
    robots = (_attr(page, "meta_robots", "") or "")
    x_robots = (_attr(page, "x_robots_tag", "") or "")
    return "noindex" in (str(robots) + " " + str(x_robots)).lower()


def analyze_pagination(pages: list[Any]) -> dict[str, Any]:
    """تحليل صفحات الترقيم وإرجاع ملخص + قائمة مشاكل."""
    by_url: dict[str, Any] = {}
    for page in pages:
        url = _attr(page, "url", "")
        if url:
            by_url[normalize_url(url)] = page

    paginated: list[dict[str, str]] = []
    issues: list[dict[str, str]] = []
    first_pages = 0

    for page in pages:
        if not _attr(page, "is_paginated", False):
            continue

        url = _attr(page, "url", "")
        nxt = _attr(page, "pagination_next", "") or ""
        prev = _attr(page, "pagination_prev", "") or ""
        paginated.append({"url": url, "next": nxt, "prev": prev})

        if nxt and not prev:
            first_pages += 1

        # canonical يجب أن يكون ذاتياً على الصفحات المرقّمة
        canonical = _attr(page, "canonical", "") or ""
        if canonical and normalize_url(canonical) != normalize_url(url):
            issues.append({
                "page_url": url,
                "issue": "non_self_canonical_on_paginated",
                "detail": f"canonical → {canonical} (يُفضّل أن يشير لذات الصفحة)",
            })

        # فحص هدف next: مزحوف وسليم وقابل للفهرسة وتسلسل متبادل
        if nxt:
            target = by_url.get(normalize_url(nxt))
            if target is not None:
                if not _is_ok_status(_attr(target, "status_code", 0)):
                    issues.append({
                        "page_url": url, "issue": "next_target_not_ok",
                        "detail": f"{nxt} → status {_attr(target, 'status_code', 0)}",
                    })
                elif _is_noindex(target):
                    issues.append({
                        "page_url": url, "issue": "next_target_noindex",
                        "detail": f"{nxt} غير قابل للفهرسة",
                    })
                target_prev = _attr(target, "pagination_prev", "") or ""
                if normalize_url(target_prev) != normalize_url(url):
                    issues.append({
                        "page_url": url, "issue": "broken_sequence",
                        "detail": f"next={nxt} لكن prev لديه = {target_prev or '∅'}",
                    })

        # فحص هدف prev (سلامة الحالة فقط)
        if prev:
            target = by_url.get(normalize_url(prev))
            if target is not None and not _is_ok_status(_attr(target, "status_code", 0)):
                issues.append({
                    "page_url": url, "issue": "prev_target_not_ok",
                    "detail": f"{prev} → status {_attr(target, 'status_code', 0)}",
                })

    return {
        "total_paginated": len(paginated),
        "first_pages": first_pages,
        "paginated_pages": paginated,
        "issues": issues,
        "issues_count": len(issues),
        "summary": {
            "total_paginated": len(paginated),
            "issues_count": len(issues),
        },
    }
