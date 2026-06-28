"""
reporting/report_join.py
========================
دمج المصادر الثلاثة (تقني + GSC + GA4) في صفوف موحّدة مفتاحها URL مُطبَّع.

- التقني: من صفحات الزحف + مخرجات المحلّلات (per-URL).
- GSC: مطابقة بالـ URL الكامل المُطبَّع.
- GA4: مطابقة بالمسار (path) لأن GA4 يُرجع مسارات لا روابط كاملة.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from utils.helpers import normalize_url


def _get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _path_of(url: str) -> str:
    """مسار مُطبَّع للمطابقة مع GA4 (lowercase، بلا trailing slash عدا الجذر)."""
    try:
        p = urlparse(url).path or "/"
    except ValueError:
        return "/"
    p = p.lower()
    if len(p) > 1:
        p = p.rstrip("/") or "/"
    return p


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


# F27: parsing آمن لقيم GSC/GA4/PageSpeed — استجابات API الخارجية قد تحتوي
# على None أو سلاسل غير رقميّة ("N/A", "", "-") تتسبّب في ValueError وتقتل
# عمليّة الدمج كاملة. هذه الـhelpers تُرجع default بدل الكسر.
def _sf(v: Any, default: float = 0.0) -> float:
    """str/None/خطأ → default. تحويل آمن إلى float."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _si(v: Any, default: int = 0) -> int:
    """تحويل آمن إلى int (يمرّ عبر float للسماح بـ"3.0")."""
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def build_technical_index(
    pages: list[Any], analysis: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """فهرس تقني per-URL: المشاكل + حقول أساسية، مفتاحه URL مُطبَّع."""
    analysis = analysis or {}
    tech: dict[str, dict[str, Any]] = {}

    for p in pages:
        raw_url = _get(p, "url", "")
        if not raw_url:
            continue
        url = normalize_url(raw_url)
        status = _int(_get(p, "status_code", 0))
        issues: list[str] = []
        if status >= 400:
            issues.append("broken")
        if status == 200:
            if not _get(p, "is_indexable", False):
                issues.append("noindex")
            if not _get(p, "title", ""):
                issues.append("missing_title")
            if _int(_get(p, "meta_description_length", 0)) == 0:
                issues.append("missing_meta")
            h1 = _int(_get(p, "h1_count", 0))
            if h1 == 0:
                issues.append("missing_h1")
            elif h1 > 1:
                issues.append("multiple_h1")
        tech[url] = {
            "url": raw_url,
            "path": _path_of(raw_url),
            "status_code": status,
            "is_indexable": bool(_get(p, "is_indexable", False)),
            "title": _get(p, "title", ""),
            "word_count": _int(_get(p, "word_count", 0)),
            "depth": _int(_get(p, "depth", 0)),
            "internal_links_count": _int(_get(p, "internal_links_count", 0)),
            "issues": issues,
        }

    def _add(url_list: list[Any], flag: str) -> None:
        for row in url_list or []:
            u = row.get("url") if isinstance(row, dict) else _get(row, "url", "")
            if not u:
                continue
            key = normalize_url(u)
            entry = tech.get(key)
            if entry is not None and flag not in entry["issues"]:
                entry["issues"].append(flag)

    orphan = analysis.get("orphan_data", {}) or {}
    _add(orphan.get("orphan_pages", []), "orphan")
    thin = analysis.get("thin_content_data", {}) or {}
    _add(thin.get("thin_content_pages", []), "thin")
    _add(thin.get("critical_thin_pages", []), "thin_critical")
    canon = analysis.get("canonical_data", {}) or {}
    for key in ("canonical_loops", "canonical_to_non_200", "canonical_to_non_indexable",
                "canonical_external", "canonical_chains"):
        _add(canon.get(key, []), "canonical_issue")
    broken = analysis.get("broken_data", {}) or {}
    _add(broken.get("pages_404_with_inlinks", []), "404_with_inlinks")

    return tech


def build_unified(
    pages: list[Any],
    analysis: dict[str, Any],
    gsc_pages: list[dict[str, Any]] | None = None,
    ga4_pages: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """صفوف موحّدة تدمج التقني + GSC + GA4 لكل URL."""
    tech = build_technical_index(pages, analysis)

    gsc_by_url: dict[str, dict[str, Any]] = {}
    for g in gsc_pages or []:
        page = g.get("page") or g.get("url") or ""
        if page:
            gsc_by_url[normalize_url(page)] = g

    ga4_by_path: dict[str, dict[str, Any]] = {}
    for a in ga4_pages or []:
        path = a.get("path") or a.get("page_path") or a.get("landing_page") or ""
        if path:
            ga4_by_path[_path_of(path if path.startswith("http") else "http://x" + path)] = a

    rows: list[dict[str, Any]] = []
    for url, t in tech.items():
        g = gsc_by_url.get(url, {})
        a = ga4_by_path.get(t["path"], {})
        rows.append({
            "url": t["url"],
            "status_code": t["status_code"],
            "is_indexable": t["is_indexable"],
            "technical_issues": t["issues"],
            "tech_issue_count": len(t["issues"]),
            "depth": t["depth"],
            "internal_links_count": t["internal_links_count"],
            # GSC
            "clicks": _int(g.get("clicks")),
            "impressions": _int(g.get("impressions")),
            "ctr": _sf(g.get("ctr")),
            "position": _sf(g.get("position")),
            # GA4
            "sessions": _int(a.get("sessions")),
            "users": _int(a.get("users") or a.get("active_users")),
            "engagement_rate": _sf(a.get("engagement_rate")),
        })
    return rows
