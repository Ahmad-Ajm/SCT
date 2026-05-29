"""
reporting/priority_engine.py
============================
محرّك الأولويات v2 (حتمي، بلا ذكاء اصطناعي) — يحوّل قائمة المشاكل إلى خطة إصلاح مرتّبة.

لكل صفحة فيها مشاكل، نحسب درجة أولوية شفّافة تجمع عدّة عوامل:

    priority_score = severity × impact × ease_factor × confidence

حيث:
- **severity** (شدّة): مجموع أوزان المشاكل التقنية للصفحة.
- **impact** (الأثر): الطلب البحثي (GSC) + القيمة التجارية (GA4) + أهمية الصفحة (نوعها/عمقها/
  روابطها الداخلية). يعمل حتى بلا تكاملات (تبقى أهمية الصفحة + الشدّة).
- **ease_factor** (سهولة الإصلاح): يرفع «المكاسب السريعة» قليلاً ويخفض العمل الصعب.
- **confidence** (الثقة): يرتفع بعدد المشاكل وبتوفّر بيانات الأداء.

ثم نصنّف كل صفحة في **لوحة عمل (Action Board)**: افعل الآن / لاحقاً / يحتاج مطوّراً /
يحتاج دعم المنصّة / يحتاج محتوى / منخفض الأثر.

كل الدوال نقية وقابلة للاختبار دون شبكة. تستهلك صفوف `build_unified` الموحّدة.
"""

from __future__ import annotations

import math
from typing import Any, Optional
from urllib.parse import urlparse

# === أوزان شدّة المشاكل (متّسقة مع reporting/opportunities.py) ===
_SEVERITY = {
    "broken": 5.0,
    "404_with_inlinks": 5.0,
    "noindex": 4.0,
    "canonical_issue": 3.0,
    "missing_title": 3.0,
    "thin_critical": 2.5,
    "missing_h1": 2.0,
    "missing_meta": 2.0,
    "orphan": 2.0,
    "thin": 1.5,
    "multiple_h1": 1.0,
}

_RECO = {
    "broken": "أصلح الصفحة أو أضف redirect 301",
    "404_with_inlinks": "صفحة 404 لها روابط داخلية — أصلح/حوّل وحدّث الروابط الداخلية",
    "noindex": "راجع توجيه noindex إن كانت الصفحة مهمة",
    "canonical_issue": "صحّح canonical ليشير لصفحة 200 قابلة للفهرسة",
    "missing_title": "أضف عنواناً فريداً وصفياً",
    "missing_h1": "أضف H1 واحداً واضحاً",
    "missing_meta": "أضف وصف meta جذّاباً",
    "thin_critical": "وسّع المحتوى (رقيق جداً)",
    "thin": "وسّع المحتوى",
    "multiple_h1": "اجعل H1 واحداً",
    "orphan": "أضف روابط داخلية لهذه الصفحة من صفحات ذات صلة",
}

# === صعوبة الإصلاح ومالكه لكل مشكلة: (difficulty, owner) ===
# difficulty ∈ {easy, moderate, hard} · owner ∈ {content, seo, developer}
_EASE = {
    "missing_title": ("easy", "content"),
    "missing_meta": ("easy", "content"),
    "missing_h1": ("easy", "content"),
    "multiple_h1": ("easy", "content"),
    "thin": ("moderate", "content"),
    "thin_critical": ("moderate", "content"),
    "orphan": ("moderate", "seo"),
    "canonical_issue": ("moderate", "developer"),
    "noindex": ("moderate", "developer"),
    "broken": ("hard", "developer"),
    "404_with_inlinks": ("hard", "developer"),
}

_EASE_FACTOR = {"easy": 1.2, "moderate": 1.0, "hard": 0.85}

# أوزان أهمية الصفحة حسب نوعها
_PAGE_TYPE_WEIGHT = {
    "home": 3.0, "category": 2.5, "product": 2.0,
    "blog": 1.5, "static": 1.0, "other": 1.0,
}

# منصّات تُسلَّم فيها مشاكل الترقيم/القوالب لدعم المنصّة لا للمطوّر
_PLATFORM_OWNED_ISSUES = {"404_with_inlinks"}
_PLATFORMS_WITH_SUPPORT = {"zid", "salla", "shopify"}


def classify_page_type(url: str, schema_types: Optional[list[str]] = None) -> str:
    """يصنّف نوع الصفحة (home/category/product/blog/static/other).

    أقوى إشارة هي schema (Product/Article…)، ثم أنماط المسار. حتمي بالكامل.
    """
    types_lower = {str(t).lower() for t in (schema_types or [])}
    if types_lower:
        if "product" in types_lower:
            return "product"
        if {"article", "blogposting", "newsarticle"} & types_lower:
            return "blog"
        if {"collectionpage", "itemlist"} & types_lower:
            return "category"

    try:
        path = (urlparse(url).path or "/").lower().rstrip("/") or "/"
    except ValueError:
        path = "/"

    if path == "/":
        return "home"
    segments = [s for s in path.split("/") if s]
    has_product_seg = any(s in ("product", "products", "p", "item", "items") for s in segments)
    has_category_seg = any(
        s in ("category", "categories", "collection", "collections", "c", "cat", "tag", "tags")
        for s in segments
    )
    # منتج مفرد عادةً: قطعة منتج + معرّف/شريحة بعدها
    if has_product_seg and len(segments) >= 2 and segments[-1] not in ("products", "product"):
        return "product"
    if has_category_seg or segments[-1] in ("products", "product", "shop", "store"):
        return "category"
    if any(s in ("blog", "blogs", "article", "articles", "news", "post", "posts") for s in segments):
        return "blog"
    if any(s in ("about", "contact", "privacy", "terms", "faq", "pages", "page", "policy") for s in segments):
        return "static"
    return "other"


def page_importance(page_type: str, depth: int, internal_links: int) -> float:
    """أهمية الصفحة: وزن النوع + إشارة الروابط الداخلية − عقوبة العمق. ≥ 0."""
    base = _PAGE_TYPE_WEIGHT.get(page_type, 1.0)
    link_signal = min(2.0, math.log1p(max(0, internal_links)) * 0.6)
    depth_penalty = min(1.0, max(0, depth) * 0.1)
    return round(max(0.0, base + link_signal - depth_penalty), 3)


def ease_of_fix(issues: list[str], platform: str = "") -> tuple[str, str]:
    """يحدّد صعوبة الإصلاح ومالكه من «أصعب» مشكلة في الصفحة.

    Returns: (difficulty, owner) — owner قد يكون "platform_support" عند منصّات معروفة.
    """
    if not issues:
        return ("easy", "content")
    rank = {"easy": 0, "moderate": 1, "hard": 2}
    hardest = ("easy", "content")
    for issue in issues:
        diff, owner = _EASE.get(issue, ("moderate", "developer"))
        if rank[diff] >= rank[hardest[0]]:
            hardest = (diff, owner)
    difficulty, owner = hardest
    platform = (platform or "").lower()
    # مشاكل الترقيم/القوالب على منصّات SaaS تُسلَّم لدعم المنصّة
    if platform in _PLATFORMS_WITH_SUPPORT and (set(issues) & _PLATFORM_OWNED_ISSUES):
        owner = "platform_support"
    return (difficulty, owner)


def _severity(issues: list[str]) -> float:
    return sum(_SEVERITY.get(i, 1.0) for i in issues)


def _demand(row: dict[str, Any]) -> float:
    raw = row.get("clicks", 0) * 2 + row.get("impressions", 0) * 0.05
    return math.log1p(max(0.0, raw))


def _business(row: dict[str, Any]) -> float:
    sessions = row.get("sessions", 0) or 0
    eng = float(row.get("engagement_rate", 0) or 0)
    return math.log1p(max(0.0, sessions * (1.0 + eng / 100.0)))


def _confidence(issue_count: int, has_traffic: bool) -> float:
    conf = 0.7 + min(0.2, 0.05 * issue_count)
    if has_traffic:
        conf += 0.1
    return round(min(1.0, conf), 3)


def _action_group(band: str, owner: str, issues: list[str]) -> str:
    if band == "low":
        return "low_impact"
    if owner == "platform_support":
        return "needs_platform"
    if owner == "developer":
        return "needs_developer"
    if owner == "content" and ({"thin", "thin_critical"} & set(issues)):
        return "needs_content"
    if band == "high":
        return "do_now"
    return "do_later"


def compute_priority(
    unified_rows: list[dict[str, Any]],
    platform: str = "",
    page_types: Optional[dict[str, str]] = None,
    top_n: int = 500,
) -> dict[str, Any]:
    """يحسب الأولوية المتعددة العوامل لكل صفحة فيها مشاكل، ويبني لوحة العمل.

    Args:
        unified_rows: مخرجات build_unified (تقني + GSC + GA4).
        platform: قالب المنصّة (zid/salla/...) لتحديد مالك مشاكل القوالب.
        page_types: تصنيف نوع الصفحة الجاهز لكل URL (اختياري؛ وإلا يُشتقّ من الرابط).
    """
    scored: list[dict[str, Any]] = []
    for r in unified_rows or []:
        issues = r.get("technical_issues", []) or []
        if not issues:
            continue
        url = r.get("url", "")
        ptype = (page_types or {}).get(url) or classify_page_type(url)
        sev = _severity(issues)
        demand = _demand(r)
        business = _business(r)
        importance = page_importance(
            ptype, r.get("depth", 0), r.get("internal_links_count", 0))
        impact = demand + business + importance
        difficulty, owner = ease_of_fix(issues, platform)
        ease_factor = _EASE_FACTOR.get(difficulty, 1.0)
        has_traffic = bool(r.get("clicks") or r.get("impressions") or r.get("sessions"))
        confidence = _confidence(len(issues), has_traffic)
        score = round(sev * impact * ease_factor * confidence, 3)
        primary = max(issues, key=lambda i: _SEVERITY.get(i, 1.0))
        scored.append({
            "url": url,
            "page_type": ptype,
            "priority_score": score,
            "owner": owner,
            "ease": difficulty,
            "tech_issue_count": len(issues),
            "technical_issues": ", ".join(issues),
            "top_fix": _RECO.get(primary, ""),
            "clicks": r.get("clicks", 0),
            "impressions": r.get("impressions", 0),
            "ctr": r.get("ctr", 0),
            "position": r.get("position", 0),
            "sessions": r.get("sessions", 0),
            # تفكيك العوامل للشفافية
            "factor_severity": round(sev, 3),
            "factor_demand": round(demand, 3),
            "factor_business": round(business, 3),
            "factor_importance": importance,
            "factor_ease": ease_factor,
            "factor_confidence": confidence,
        })

    scored.sort(key=lambda x: x["priority_score"], reverse=True)

    # نطاقات الأولوية نسبية لأعلى درجة (شفّافة وثابتة عبر المواقع)
    max_score = scored[0]["priority_score"] if scored else 0.0
    for s in scored:
        ratio = (s["priority_score"] / max_score) if max_score else 0.0
        band = "high" if ratio >= 0.5 else ("medium" if ratio >= 0.2 else "low")
        s["priority_band"] = band
        issues_list = [i.strip() for i in s["technical_issues"].split(",") if i.strip()]
        s["action_group"] = _action_group(band, s["owner"], issues_list)
        s["reason"] = (
            f"صفحة {s['page_type']} — {s['tech_issue_count']} مشكلة تقنية، "
            f"ظهور {s['impressions']}، نقرات {s['clicks']}، جلسات {s['sessions']}"
        )

    scored = scored[:top_n]
    bands = {"high": 0, "medium": 0, "low": 0}
    groups: dict[str, int] = {}
    for s in scored:
        bands[s["priority_band"]] += 1
        groups[s["action_group"]] = groups.get(s["action_group"], 0) + 1

    return {
        "pages": scored,
        "count": len(scored),
        "summary": {
            "pages_with_issues": len(scored),
            "by_band": bands,
            "by_action_group": groups,
            "do_now": groups.get("do_now", 0),
        },
    }


# ترتيب عرض مجموعات لوحة العمل
_GROUP_ORDER = ["do_now", "needs_content", "needs_developer", "needs_platform",
                "do_later", "low_impact"]


def build_action_board(priority: dict[str, Any]) -> list[dict[str, Any]]:
    """يُسطّح نتائج الأولوية إلى صفوف لوحة عمل مرتّبة (المجموعة ثم الدرجة)."""
    pages = (priority or {}).get("pages", []) or []
    order = {g: i for i, g in enumerate(_GROUP_ORDER)}
    rows = sorted(
        pages,
        key=lambda p: (order.get(p.get("action_group"), 99), -p.get("priority_score", 0)),
    )
    return [{
        "action_group": p.get("action_group"),
        "priority_band": p.get("priority_band"),
        "url": p.get("url"),
        "page_type": p.get("page_type"),
        "owner": p.get("owner"),
        "ease": p.get("ease"),
        "priority_score": p.get("priority_score"),
        "top_fix": p.get("top_fix"),
        "technical_issues": p.get("technical_issues"),
        "reason": p.get("reason"),
    } for p in rows]
