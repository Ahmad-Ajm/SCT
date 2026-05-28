"""
analyzers/redirect_analyzer.py
===============================
تحليل redirects: السلاسل الطويلة، الحلقات، أنواع الـ status codes.
"""

from collections import defaultdict
from typing import Any

from crawler.core import PageData
from utils.helpers import is_internal_url


def _get(item: Any, key: str, default: Any = None) -> Any:
    """Read a field from either a PageData object or a dict row (DB-backed)."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _order_chain(chain: list[dict[str, Any]], origin: str) -> list[dict[str, Any]]:
    """ترتيب سلسلة redirect بتتبّع from_url → to_url (بدل الاعتماد على طول النص)."""
    by_from: dict[str, dict[str, Any]] = {}
    for hop in chain:
        by_from.setdefault(_get(hop, "from_url", ""), hop)
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    current = origin
    while current in by_from and current not in seen:
        hop = by_from[current]
        ordered.append(hop)
        seen.add(current)
        current = _get(hop, "to_url", "")
    # أضف أي قفزات لم تُربط (احتياطاً) للحفاظ على البيانات — تتبّع عبر from_url
    # في set بدل `hop not in ordered` (التي كانت O(n²) على القوائم).
    if len(ordered) < len(chain):
        appended = {_get(h, "from_url", "") for h in ordered}
        for hop in chain:
            frm = _get(hop, "from_url", "")
            if frm not in appended:
                ordered.append(hop)
                appended.add(frm)
    return ordered


def analyze_redirects(
    pages: list[PageData],
    all_redirects: list[dict[str, Any]],
    primary_domain: str = "",
    additional_domains: list[str] | None = None,
) -> dict[str, Any]:
    """
    تحليل كل الـ redirects المكتشفة.

    يكشف:
    - Redirect Chains (>1 hop)
    - Redirect Loops
    - 302 redirects (يجب أن تكون 301)
    - Internal redirects (يجب تحديث الروابط)
    - Mixed protocol redirects (HTTP → HTTPS)

    Returns:
        dict: تقرير شامل عن redirects
    """
    # === تجميع redirects حسب السلسلة الأصلية ===
    chains_by_origin: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for redirect in all_redirects:
        origin = redirect.get("original_url", redirect.get("from_url", ""))
        chains_by_origin[origin].append(redirect)

    # === تحليل كل سلسلة ===
    redirect_chains = []  # سلاسل >1 hop
    redirect_loops = []  # حلقات
    temporary_redirects = []  # 302 يجب أن تكون 301
    internal_redirects = []  # redirects داخلية
    _seen_internal: set[tuple[str, str]] = set()  # لمنع تكرار نفس القفزة الداخلية
    protocol_upgrades = []  # HTTP → HTTPS

    for origin, chain in chains_by_origin.items():
        if not chain:
            continue

        # ترتيب السلسلة بتتبّع الروابط (from → to) بدل طول النص (إصلاح M6)
        chain_sorted = _order_chain(chain, origin)
        final_url = chain_sorted[-1].get("to_url", "")
        chain_length = len(chain)

        # كشف الحلقة: تكرار from_url داخل المسار أو العودة للأصل
        froms = [h.get("from_url", "") for h in chain_sorted]
        has_loop = origin == final_url or final_url in froms or len(set(froms)) < len(froms)

        chain_entry = {
            "original_url": origin,
            "final_url": final_url,
            "chain_length": chain_length,
            "hops": [
                {
                    "from": r.get("from_url", ""),
                    "to": r.get("to_url", ""),
                    "status_code": r.get("status_code", 0),
                }
                for r in chain_sorted
            ],
        }

        # سلسلة طويلة
        if chain_length > 1:
            redirect_chains.append(chain_entry)

        # حلقة
        if has_loop:
            redirect_loops.append(chain_entry)

        # 302 بدلاً من 301
        for hop in chain_sorted:
            if hop.get("status_code") == 302:
                temporary_redirects.append(
                    {
                        "from": hop.get("from_url", ""),
                        "to": hop.get("to_url", ""),
                        "status_code": 302,
                        "recommendation": "غيّر إلى 301 إن كان التحويل دائماً",
                    }
                )

        # Protocol upgrade
        if origin.startswith("http://") and final_url.startswith("https://"):
            protocol_upgrades.append(chain_entry)

        # Redirects داخلية (المصدر والوجهة كلاهما داخل الموقع) — إصلاح M5
        if primary_domain:
            for hop in chain_sorted:
                frm = hop.get("from_url", "")
                to = hop.get("to_url", "")
                if (
                    (frm, to) not in _seen_internal
                    and is_internal_url(frm, primary_domain, additional_domains)
                    and is_internal_url(to, primary_domain, additional_domains)
                ):
                    _seen_internal.add((frm, to))
                    internal_redirects.append(
                        {
                            "from": frm,
                            "to": to,
                            "status_code": hop.get("status_code", 0),
                            "recommendation": "حدّث الروابط الداخلية لتشير مباشرة للوجهة النهائية",
                        }
                    )

    # === Redirects من الصفحات (Pages) ===
    page_redirects = [
        {
            "url": _get(page, "url", ""),
            "final_url": _get(page, "final_url", ""),
            "status_code": _get(page, "status_code", 0),
            "redirect_chain": _get(page, "redirect_chain", []),
        }
        for page in pages
        if _get(page, "is_redirect", False)
    ]

    return {
        "total_redirects": len(all_redirects),
        "pages_redirected": len(page_redirects),
        "redirect_chains": redirect_chains,
        "redirect_chains_count": len(redirect_chains),
        "redirect_loops": redirect_loops,
        "redirect_loops_count": len(redirect_loops),
        "temporary_redirects": temporary_redirects,
        "temporary_redirects_count": len(temporary_redirects),
        "internal_redirects": internal_redirects,
        "internal_redirects_count": len(internal_redirects),
        "protocol_upgrades": protocol_upgrades,
        "protocol_upgrades_count": len(protocol_upgrades),
        "all_redirects_detailed": page_redirects,
    }
