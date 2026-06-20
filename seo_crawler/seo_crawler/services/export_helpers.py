"""
services/export_helpers.py — flatten helpers لتسطيح نتائج التكاملات لصفوف CSV.

نُقلت من main.py في v1.12 (Tier 1 — pure data helpers، لا تستورد أيّ service آخر
أو أيّ شيء غير stdlib + utils.logger).

استخدامها: من export_service.run_export ومن integrations_only_service.
"""

from __future__ import annotations

from typing import Any

from utils.logger import get_logger

log = get_logger(__name__)


def get_value(item: Any, key: str, default: Any = None) -> Any:
    """قراءة قيمة بمفتاح من dict أو من attribute لـobject — يدعم AttrDict."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def flatten_pagespeed(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """تسطيح نتائج PageSpeed إلى صفوف CSV (المقاييس الأساسية + تقييم CrUX)."""
    rows: list[dict[str, Any]] = []
    for r in results or []:
        if not isinstance(r, dict) or r.get("error"):
            if isinstance(r, dict) and r.get("error"):
                rows.append({"url": r.get("url"), "strategy": r.get("strategy"),
                             "error": r.get("error")})
            continue
        def _cat(field: str) -> str:
            v = r.get(field) or {}
            return v.get("category", "") if isinstance(v, dict) else ""
        rows.append({
            "url": r.get("url"),
            "strategy": r.get("strategy"),
            "performance": r.get("performance_score"),
            "accessibility": r.get("accessibility_score"),
            "best_practices": r.get("best_practices_score"),
            "seo": r.get("seo_score"),
            "lcp_lab_ms": r.get("lcp_lab_ms"),
            "cls_lab": r.get("cls_lab"),
            "tbt_lab_ms": r.get("tbt_lab_ms"),
            "crux_overall": r.get("crux_overall"),
            "lcp_field": _cat("lcp_field"),
            "cls_field": _cat("cls_field"),
            "inp_field": _cat("inp_field"),
        })
    return rows


def flatten_pagespeed_opportunities(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """البيانات العميقة: «فرص التحسين» لكل صفحة (ما الذي يُبطئها وكم تُوفّر)."""
    rows: list[dict[str, Any]] = []
    for r in results or []:
        if not isinstance(r, dict) or r.get("error"):
            continue
        url, strat = r.get("url"), r.get("strategy")
        for o in r.get("opportunities", []) or []:
            rows.append({
                "url": url,
                "strategy": strat,
                "opportunity": o.get("title"),
                "savings_ms": o.get("savings_ms"),
                "savings_kb": round((o.get("savings_bytes") or 0) / 1024, 1),
                "id": o.get("id"),
                "description": o.get("description"),
            })
    return rows


def flatten_pagespeed_table(results: list[dict[str, Any]], table: str) -> list[dict[str, Any]]:
    """يجمع صفوف جدول Lighthouse منظّم (audits/network_requests/js_treemap) عبر كل النتائج."""
    rows: list[dict[str, Any]] = []
    for r in results or []:
        if isinstance(r, dict):
            rows.extend((r.get("lighthouse_tables") or {}).get(table) or [])
    return rows


def flatten_pagespeed_failed_audits(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """يجمع التدقيقات الفاشلة (مشاكل حقيقية) عبر كل النتائج."""
    rows: list[dict[str, Any]] = []
    for r in results or []:
        if isinstance(r, dict):
            rows.extend(r.get("failed_audits") or [])
    return rows


def export_pagespeed_tables(ps_data, exporter, files: dict, log_each: bool = False) -> None:
    """يصدّر الجداول المنظّمة الأربعة لـ PageSpeed كملفات CSV (IMP-17أ)."""
    table_files = [
        ("pagespeed_audits", "audits"),
        ("pagespeed_network_requests", "network_requests"),
        ("pagespeed_js_treemap", "js_treemap"),
    ]
    for key, table in table_files:
        rows = flatten_pagespeed_table(ps_data, table)
        if rows:
            files[key] = exporter._export(f"{key}.csv", rows)
            if log_each:
                log.info(f"  ✓ {key}.csv ({len(rows)} صفوف)")
    failed = flatten_pagespeed_failed_audits(ps_data)
    if failed:
        files["pagespeed_failed_audits"] = exporter._export(
            "pagespeed_failed_audits.csv", failed)
        if log_each:
            log.info(f"  ✓ pagespeed_failed_audits.csv ({len(failed)} صفوف)")


def flatten_accessibility(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ملخّص الوصولية لكل صفحة: عدد المخالفات + توزيعها حسب الأثر."""
    rows: list[dict[str, Any]] = []
    for s in items or []:
        if not isinstance(s, dict):
            continue
        bi = s.get("by_impact", {}) or {}
        rows.append({
            "url": s.get("url"),
            "violations": s.get("violations_count", 0),
            "nodes": s.get("nodes_total", 0),
            "critical": bi.get("critical", 0),
            "serious": bi.get("serious", 0),
            "moderate": bi.get("moderate", 0),
            "minor": bi.get("minor", 0),
        })
    return rows


def flatten_accessibility_issues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """كل مخالفة وصولية على حدة (صف لكل قاعدة axe فاشلة لكل صفحة)."""
    rows: list[dict[str, Any]] = []
    for s in items or []:
        if isinstance(s, dict):
            rows.extend(s.get("violations", []) or [])
    return rows


def flatten_cannibalization(cann: dict[str, Any]) -> list[dict[str, Any]]:
    """يحوّل مجموعات تكلّس الكلمات إلى صف لكل (استعلام، صفحة متنافِسة)."""
    rows: list[dict[str, Any]] = []
    for g in (cann or {}).get("cannibalization", []) or []:
        for p in g.get("competing_pages", []) or []:
            rows.append({
                "query": g.get("query"),
                "competing_pages_count": g.get("pages_count"),
                "query_total_impressions": g.get("total_impressions"),
                "page": p.get("page"),
                "clicks": p.get("clicks"),
                "impressions": p.get("impressions"),
                "position": p.get("position"),
            })
    return rows


def integrations_for_json(integrations: dict[str, Any]) -> dict[str, Any]:
    """نسخة من التكاملات بلا الجداول الكبيرة (lighthouse_tables) لإبقاء JSON خفيفاً.

    الجداول الكاملة في CSV؛ نُبقي failed_audits (صغير ومفيد للوحة/التقرير)."""
    if not isinstance(integrations, dict) or not integrations.get("pagespeed"):
        return integrations
    lean = dict(integrations)
    lean["pagespeed"] = [
        ({k: v for k, v in r.items() if k != "lighthouse_tables"}
         if isinstance(r, dict) else r)
        for r in integrations["pagespeed"]
    ]
    return lean


def flatten_hreflang_issues(hv: dict[str, Any]) -> list[dict[str, Any]]:
    """تحويل نتائج التحقق من hreflang إلى صفوف CSV موحّدة (عمود issue + التفاصيل)."""
    categories = (
        "non_reciprocal", "points_to_404", "points_to_noindex", "invalid_format",
        "missing_self_reference", "missing_x_default", "duplicated_languages",
        "lang_mismatch",
    )
    rows: list[dict[str, Any]] = []
    for category in categories:
        for item in hv.get(category, []) or []:
            rows.append({"issue": category, **item})
    return rows
