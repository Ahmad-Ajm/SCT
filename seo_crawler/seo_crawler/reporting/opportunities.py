"""
reporting/opportunities.py
==========================
محرّك الأولويات المتقاطعة: يرتّب الصفحات حسب (الأثر التجاري × شدّة المشكلة التقنية).

الفكرة: صفحة فيها مشاكل تقنية وتجلب نقرات/جلسات = أولوية قصوى للإصلاح.
"""

from __future__ import annotations

from typing import Any

# وزن شدّة كل مشكلة تقنية (لحساب درجة الشدّة)
_SEVERITY = {
    "broken": 5.0,
    "404_with_inlinks": 5.0,
    "noindex": 4.0,
    "canonical_issue": 3.0,
    "missing_title": 3.0,
    "missing_h1": 2.0,
    "missing_meta": 2.0,
    "thin_critical": 2.5,
    "thin": 1.5,
    "multiple_h1": 1.0,
    "orphan": 2.0,
}

# توصية مختصرة لكل مشكلة
_RECO = {
    "broken": "أصلح الصفحة أو أضف redirect 301",
    "404_with_inlinks": "صفحة 404 لها روابط داخلية — أصلح/حوّل وحدّث الروابط",
    "noindex": "راجع توجيه noindex إن كانت الصفحة مهمة",
    "canonical_issue": "صحّح canonical ليشير لصفحة 200 قابلة للفهرسة",
    "missing_title": "أضف عنواناً فريداً",
    "missing_h1": "أضف H1 واحداً",
    "missing_meta": "أضف وصفاً (meta description)",
    "thin_critical": "وسّع المحتوى (رقيق جداً)",
    "thin": "وسّع المحتوى",
    "multiple_h1": "استخدم H1 واحداً",
    "orphan": "أضف روابط داخلية لهذه الصفحة",
}


def compute_opportunities(
    unified_rows: list[dict[str, Any]],
    top_n: int = 200,
) -> dict[str, Any]:
    """حساب درجة الأولوية لكل صفحة ودمج المشاكل مع الأثر.

    priority_score = impact × severity
      impact   = log-scaled(clicks*2 + impressions*0.05 + sessions)
      severity = مجموع أوزان المشاكل التقنية
    """
    import math

    scored: list[dict[str, Any]] = []
    for r in unified_rows:
        issues = r.get("technical_issues", []) or []
        if not issues:
            continue  # لا مشكلة تقنية ⇒ ليست فرصة إصلاح
        severity = sum(_SEVERITY.get(i, 1.0) for i in issues)
        impact_raw = (
            r.get("clicks", 0) * 2
            + r.get("impressions", 0) * 0.05
            + r.get("sessions", 0) * 1.0
        )
        impact = math.log1p(max(0.0, impact_raw))
        # حتى الصفحات بلا بيانات أداء تأخذ حداً أدنى من الأثر حسب الربط الداخلي
        if impact == 0:
            impact = math.log1p(r.get("internal_links_count", 0)) * 0.3
        score = round(impact * severity, 3)
        scored.append({
            "url": r.get("url"),
            "priority_score": score,
            "tech_issue_count": len(issues),
            "technical_issues": ", ".join(issues),
            "top_fix": _RECO.get(issues[0], ""),
            "clicks": r.get("clicks", 0),
            "impressions": r.get("impressions", 0),
            "ctr": r.get("ctr", 0),
            "position": r.get("position", 0),
            "sessions": r.get("sessions", 0),
            "engagement_rate": r.get("engagement_rate", 0),
        })

    scored.sort(key=lambda x: x["priority_score"], reverse=True)
    return {
        "total_with_issues": len(scored),
        "opportunities": scored[:top_n],
        "summary": {
            "pages_with_issues": len(scored),
            "with_traffic_and_issues": sum(
                1 for s in scored if s["clicks"] or s["impressions"] or s["sessions"]
            ),
        },
    }
