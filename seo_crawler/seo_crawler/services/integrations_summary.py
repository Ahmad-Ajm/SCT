"""
services/integrations_summary.py — ملخّصات GSC + GA4 لاستخدامها في التقارير.

نُقل من main.py في v1.12 (Tier 0 — pure data helpers، لا تعتمد على شيء داخلي).
يُستخدم من export_service و integrations_only_service.
"""

from __future__ import annotations

from typing import Any


def gsc_summary(integrations: dict[str, Any]) -> dict[str, Any]:
    """ملخّص GSC للتقرير (إجماليات + أعلى الصفحات/الاستعلامات)."""
    pages = (integrations or {}).get("gsc_pages") or []
    queries = (integrations or {}).get("gsc_queries") or []
    if not pages and not queries:
        return {}
    total_clicks = sum(int(p.get("clicks", 0) or 0) for p in pages)
    total_impr = sum(int(p.get("impressions", 0) or 0) for p in pages)
    avg_ctr = round(total_clicks / total_impr * 100, 2) if total_impr else 0
    avg_pos = round(sum(float(p.get("position", 0) or 0) for p in pages) / len(pages), 2) if pages else 0
    return {
        "total_clicks": total_clicks,
        "total_impressions": total_impr,
        "avg_ctr": avg_ctr,
        "avg_position": avg_pos,
        "pages_count": len(pages),
        "top_pages": sorted(pages, key=lambda x: int(x.get("clicks", 0) or 0), reverse=True)[:20],
        "top_queries": sorted(queries, key=lambda x: int(x.get("clicks", 0) or 0), reverse=True)[:20],
    }


def ga4_summary(integrations: dict[str, Any]) -> dict[str, Any]:
    """ملخّص GA4 للتقرير (إجماليات + أعلى صفحات الهبوط + القنوات)."""
    landing = (integrations or {}).get("ga4_landing_pages") or []
    channels = (integrations or {}).get("ga4_channels") or []
    if not landing and not channels:
        return {}
    total_sessions = sum(int(p.get("sessions", 0) or 0) for p in landing)
    total_users = sum(int(p.get("users", 0) or 0) for p in landing)
    return {
        "total_sessions": total_sessions,
        "total_users": total_users,
        "landing_pages_count": len(landing),
        "top_landing_pages": sorted(landing, key=lambda x: int(x.get("sessions", 0) or 0), reverse=True)[:20],
        "channels": sorted(channels, key=lambda x: int(x.get("sessions", 0) or 0), reverse=True),
    }
