"""
analyzers/crawl_compare.py
==========================
مقارنة زمنية بين زحفتين لنفس الموقع (IMP-4) — لإظهار التقدّم بين تقريرين:
أي المشاكل أُصلحت، وأيها جديدة، وأيها باقية، وكيف تغيّر إجمالي الصفحات/المشاكل.

بخلاف وضع المقارنة الحالي (مقارنة منافسين)، هذه مقارنة «قبل/بعد» لنفس الموقع — أساسية
لعروض تقدّم الوكالة. دالّة نقية تعمل على قاموسَي تدقيق (complete_audit.json) أو ملفّيهما.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _issue_counts(audit: dict[str, Any]) -> dict[str, int]:
    """{issue_type: مجموع الصفحات المتأثرة} من seo_issues.all_issues."""
    counts: dict[str, int] = {}
    issues = ((audit or {}).get("seo_issues") or {}).get("all_issues") or []
    for it in issues:
        if not isinstance(it, dict):
            continue
        t = it.get("issue_type")
        if not t:
            continue
        counts[t] = counts.get(t, 0) + int(it.get("affected_count", 0) or 0)
    return counts


def _page_urls(audit: dict[str, Any]) -> set[str]:
    urls: set[str] = set()
    for p in (audit or {}).get("pages") or []:
        u = p.get("url") if isinstance(p, dict) else getattr(p, "url", None)
        if u:
            urls.add(str(u).rstrip("/"))
    return urls


def _total_issues(audit: dict[str, Any]) -> int:
    summary = ((audit or {}).get("seo_issues") or {}).get("summary") or {}
    if "total_issues" in summary:
        return int(summary.get("total_issues", 0) or 0)
    return sum(_issue_counts(audit).values())


def compare_crawls(old_audit: dict[str, Any], new_audit: dict[str, Any]) -> dict[str, Any]:
    """يقارن زحفتين ويُرجع المشاكل المُصلَحة/الجديدة/الباقية وتغيّرات الصفحات."""
    old_counts = _issue_counts(old_audit)
    new_counts = _issue_counts(new_audit)
    old_types, new_types = set(old_counts), set(new_counts)

    fixed = [{"issue_type": t, "old_count": old_counts[t]}
             for t in sorted(old_types - new_types)]
    new_problems = [{"issue_type": t, "new_count": new_counts[t]}
                    for t in sorted(new_types - old_types)]
    persisting = []
    for t in sorted(old_types & new_types):
        persisting.append({
            "issue_type": t,
            "old_count": old_counts[t],
            "new_count": new_counts[t],
            "delta": new_counts[t] - old_counts[t],
        })

    old_urls, new_urls = _page_urls(old_audit), _page_urls(new_audit)
    old_total, new_total = _total_issues(old_audit), _total_issues(new_audit)

    return {
        "fixed_issue_types": fixed,
        "new_issue_types": new_problems,
        "persisting_issue_types": persisting,
        "pages_added": sorted(new_urls - old_urls)[:1000],
        "pages_removed": sorted(old_urls - new_urls)[:1000],
        "summary": {
            "fixed_count": len(fixed),
            "new_count": len(new_problems),
            "persisting_count": len(persisting),
            "old_total_issues": old_total,
            "new_total_issues": new_total,
            "issues_delta": new_total - old_total,
            "old_pages": len(old_urls),
            "new_pages": len(new_urls),
            "pages_added_count": len(new_urls - old_urls),
            "pages_removed_count": len(old_urls - new_urls),
            "improved": new_total < old_total,
        },
    }


def compare_audit_files(old_path: str, new_path: str) -> dict[str, Any]:
    """يحمّل ملفَّي تدقيق JSON ويقارنهما."""
    old = json.loads(Path(old_path).read_text(encoding="utf-8"))
    new = json.loads(Path(new_path).read_text(encoding="utf-8"))
    return compare_crawls(old, new)
