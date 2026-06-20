"""
services/deferred_service.py — تسطيح وتلخيص الروابط المؤجَّلة (v1.08 Phase 2).

نُقل من main.py في v1.12 (Tier 0 leaf — لا يستورد من أيّ service آخر).
الـAPI الجديد بلا underscore (deferred_list / deferred_summary) ويُعاد تصديره
من main.py بأسماء _deferred_list / _deferred_summary للتوافق العكسي.
"""

from __future__ import annotations

from typing import Any


def deferred_list(crawler: Any) -> list[dict[str, Any]]:
    """v1.08: يُسطّح dict الـdeferred إلى قائمة للتصدير في audit JSON و CSV."""
    d = getattr(crawler, "deferred", None) or {}
    out: list[dict[str, Any]] = []
    for url, info in d.items():
        out.append({
            "url": url,
            "kind": info.get("kind", "other"),
            "source_url": info.get("source_url", ""),
            "depth": info.get("depth", ""),
        })
    return out


def deferred_summary(crawler: Any) -> dict[str, Any]:
    """v1.08: ملخّص الـdeferred (counts بحسب kind + 10 أمثلة لكلّ نوع) — هذا ما
    تعرضه واجهة المهمّة في «لوحة الروابط المؤجَّلة» بعد Phase 1."""
    d = getattr(crawler, "deferred", None) or {}
    by_kind: dict[str, int] = {}
    samples: dict[str, list[str]] = {}
    for url, info in d.items():
        k = info.get("kind", "other")
        by_kind[k] = by_kind.get(k, 0) + 1
        s = samples.setdefault(k, [])
        if len(s) < 10:
            s.append(url)
    return {
        "total": len(d),
        "by_kind": by_kind,
        "samples": samples,
        "phase2_available": len(d) > 0,
    }
