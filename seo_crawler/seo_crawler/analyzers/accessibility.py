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

from pathlib import Path
from typing import Any

from utils.logger import get_logger

log = get_logger(__name__)

_IMPACT_ORDER = {"critical": 0, "serious": 1, "moderate": 2, "minor": 3}

# CDN افتراضي موثوق لمصدر axe-core (يُجلب فقط عند allow_cdn=True صراحةً)
_DEFAULT_CDN = "https://cdn.jsdelivr.net/npm/axe-core@4/axe.min.js"
_MAX_AXE_BYTES = 4 * 1024 * 1024  # سقف حجم ملف axe (~600KB فعلياً)


def load_axe_source(
    local_path: str = "",
    cdn_url: str = "",
    allow_cdn: bool = False,
) -> str:
    """يُحمّل نصّ axe-core JS: من ملف محلي إن وُجد، وإلا من CDN عند السماح صراحةً.

    يعيد "" عند التعذّر (فيُعطَّل فحص الوصولية بسلاسة دون كسر الزحف).
    """
    if local_path:
        try:
            p = Path(local_path)
            if p.is_file():
                return p.read_text(encoding="utf-8")
            log.warning("ملف axe-core غير موجود: %s", local_path)
        except OSError as e:
            log.warning("تعذّر قراءة axe-core المحلي: %s", e)
    if allow_cdn:
        url = cdn_url or _DEFAULT_CDN
        try:
            import requests
            # v1.09-B9: استعمل context manager كي يُغلق الـresponse stream
            # حتّى على نجاح/خطأ — لم يكن يُغلَق في الفرع الناجح ⇒ leak اتصالات.
            with requests.get(url, timeout=30, stream=True) as resp:
                if resp.status_code != 200:
                    log.warning("تعذّر جلب axe-core من CDN (HTTP %s)", resp.status_code)
                    return ""
                chunks, total = [], 0
                for ch in resp.iter_content(8192):
                    if not ch:
                        continue
                    total += len(ch)
                    if total > _MAX_AXE_BYTES:
                        log.warning("ملف axe-core من CDN يتجاوز الحدّ — تخطّي")
                        return ""
                    chunks.append(ch)
                return b"".join(chunks).decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            log.warning("تعذّر جلب axe-core من CDN: %s", e)
    return ""


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
