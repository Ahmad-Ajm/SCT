"""
analyzers/gsc_insights.py
=========================
تحليلات مبنية على بيانات Google Search Console المجلوبة أصلاً (بلا أي نداء API إضافي):

1) تكلّس الكلمات (Keyword Cannibalization): عدّة صفحات من نفس الموقع تتنافس على نفس
   استعلام البحث — يُشتّت إشارات الترتيب ويُضعف أداء البحث. نكشفه من بيانات (page, query).

2) فُرَص الروابط الداخلية (Internal Link Opportunities): صفحات بظهور/نقرات عالية في البحث
   لكن روابط داخلية واردة قليلة — تقوية روابطها الداخلية تُحسّن اكتشافها وترتيبها. نكشفها بدمج
   صفحات GSC مع درجة الروابط الداخلية (link_score).

لا PII: نتعامل مع روابط صفحات واستعلامات وأرقام مجمّعة فقط.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from utils.helpers import normalize_url


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def detect_cannibalization(
    page_query_rows: list[dict[str, Any]],
    min_impressions: int = 10,
    min_pages: int = 2,
    max_groups: int = 500,
) -> dict[str, Any]:
    """يكشف الاستعلامات التي تتنافس عليها أكثر من صفحة واحدة.

    Args:
        page_query_rows: صفوف GSC ببُعدَي (page, query) — كلٌّ فيه clicks/impressions/position.
        min_impressions: أدنى مجموع ظهور للاستعلام كي يُعتبَر ذا قيمة.
        min_pages: أدنى عدد صفحات متنافسة (≥2).
    """
    by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in page_query_rows or []:
        if not isinstance(r, dict):
            continue
        q = r.get("query")
        pg = r.get("page")
        if not q or not pg:
            continue
        by_query[q].append(r)

    groups: list[dict[str, Any]] = []
    for query, rows in by_query.items():
        # صفحات فريدة فعلاً تتنافس على الاستعلام
        distinct_pages = {r.get("page") for r in rows if r.get("page")}
        total_impr = sum(_num(r.get("impressions")) for r in rows)
        if len(distinct_pages) < min_pages or total_impr < min_impressions:
            continue
        ranked = sorted(rows, key=lambda r: _num(r.get("clicks")), reverse=True)
        groups.append({
            "query": query,
            "pages_count": len(distinct_pages),
            "total_clicks": int(sum(_num(r.get("clicks")) for r in rows)),
            "total_impressions": int(total_impr),
            "competing_pages": [{
                "page": r.get("page"),
                "clicks": int(_num(r.get("clicks"))),
                "impressions": int(_num(r.get("impressions"))),
                "position": round(_num(r.get("position")), 2),
            } for r in ranked[:10]],
        })

    groups.sort(key=lambda g: g["total_impressions"], reverse=True)
    groups = groups[:max_groups]
    return {
        "cannibalization": groups,
        "count": len(groups),
        "summary": {
            "queries_with_cannibalization": len(groups),
            "total_impressions_affected": sum(g["total_impressions"] for g in groups),
        },
    }


def find_internal_link_opportunities(
    gsc_pages: list[dict[str, Any]],
    link_score_pages: list[dict[str, Any]],
    min_impressions: int = 100,
    max_inlinks: int = 2,
    max_rows: int = 500,
) -> dict[str, Any]:
    """صفحات بأداء بحث جيّد وروابط داخلية واردة قليلة (مرشّحة لتقوية الربط الداخلي).

    Args:
        gsc_pages: صفوف GSC ببُعد (page).
        link_score_pages: مخرجات link_score (تحوي internal_inlinks لكل url).
        min_impressions: أدنى ظهور بحث كي تُعتبَر الصفحة ذات قيمة.
        max_inlinks: الحدّ الأقصى للروابط الداخلية الواردة كي تُعتبَر «ضعيفة الربط».
    """
    inlinks_by_url: dict[str, int] = {}
    for p in link_score_pages or []:
        if not isinstance(p, dict):
            continue
        u = p.get("url")
        if u:
            inlinks_by_url[normalize_url(u)] = int(_num(p.get("internal_inlinks")))

    rows: list[dict[str, Any]] = []
    for r in gsc_pages or []:
        if not isinstance(r, dict):
            continue
        page = r.get("page")
        if not page:
            continue
        impressions = _num(r.get("impressions"))
        if impressions < min_impressions:
            continue
        inlinks = inlinks_by_url.get(normalize_url(page))
        if inlinks is None:
            # الصفحة في GSC لكن ليست في الزحف (قد تكون يتيمة فعلاً) — نعدّها 0
            inlinks = 0
        if inlinks > max_inlinks:
            continue
        rows.append({
            "page": page,
            "impressions": int(impressions),
            "clicks": int(_num(r.get("clicks"))),
            "position": round(_num(r.get("position")), 2),
            "internal_inlinks": inlinks,
            "in_crawl": normalize_url(page) in inlinks_by_url,
        })

    # الأولوية: ظهور أعلى وروابط داخلية أقل
    rows.sort(key=lambda x: (-x["impressions"], x["internal_inlinks"]))
    rows = rows[:max_rows]
    return {
        "opportunities": rows,
        "count": len(rows),
        "summary": {
            "high_value_low_link_pages": len(rows),
            "total_impressions": sum(x["impressions"] for x in rows),
        },
    }
