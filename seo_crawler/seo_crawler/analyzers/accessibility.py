"""
analyzers/accessibility.py
==========================
فحص الوصولية (Accessibility / WCAG) عبر axe-core (IMP-7) — اختياري، مطفأ افتراضياً.

يُحقَن axe-core في صفحة Playwright المُصيَّرة (نفس المتصفّح المُستخدَم لتصيير JS) ويُجمَّع
الناتج. هنا نوفّر:
- `summarize_axe_results`: دالّة نقية تحوّل ناتج axe إلى ملخّص + صفوف (قابلة للاختبار بلا متصفّح).
- `run_axe_on_page`: مُساعد يُشغّل axe على صفحة Playwright حيّة (يتطلّب playwright + مصدر axe).

التصميم متدرّج السلوك: عند غياب المتصفّح/axe يُعيد نتيجة فارغة دون أن يكسر الزحف.
"""

from __future__ import annotations

from typing import Any

_IMPACT_ORDER = {"critical": 0, "serious": 1, "moderate": 2, "minor": 3}


def summarize_axe_results(axe_json: dict[str, Any], url: str = "") -> dict[str, Any]:
    """يحوّل ناتج axe.run() إلى ملخّص + صفوف مخالفات مسطّحة. دالّة نقية."""
    violations = (axe_json or {}).get("violations") or []
    rows: list[dict[str, Any]] = []
    by_impact: dict[str, int] = {}
    for v in violations:
        if not isinstance(v, dict):
            continue
        impact = v.get("impact") or "minor"
        nodes = v.get("nodes") or []
        by_impact[impact] = by_impact.get(impact, 0) + 1
        rows.append({
            "url": url,
            "rule_id": v.get("id", ""),
            "impact": impact,
            "help": v.get("help", ""),
            "description": (v.get("description", "") or "")[:300],
            "nodes_count": len(nodes),
            "help_url": v.get("helpUrl", ""),
        })
    rows.sort(key=lambda r: _IMPACT_ORDER.get(r["impact"], 9))
    return {
        "url": url,
        "violations": rows,
        "violations_count": len(rows),
        "nodes_total": sum(r["nodes_count"] for r in rows),
        "by_impact": by_impact,
    }


def run_axe_on_page(page: Any, axe_source: str) -> dict[str, Any]:
    """يُشغّل axe-core على صفحة Playwright حيّة ويعيد ملخّص المخالفات.

    Args:
        page: صفحة Playwright (sync API).
        axe_source: محتوى axe.min.js (نصّ JavaScript).
    """
    if page is None or not axe_source:
        return summarize_axe_results({}, "")
    try:
        page.add_script_tag(content=axe_source)
        result = page.evaluate("async () => await axe.run()")
        url = getattr(page, "url", "") or ""
        return summarize_axe_results(result, url)
    except Exception:  # noqa: BLE001
        return summarize_axe_results({}, getattr(page, "url", "") or "")
