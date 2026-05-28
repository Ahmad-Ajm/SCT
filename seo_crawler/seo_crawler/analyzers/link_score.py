"""
analyzers/link_score.py
=======================
درجة الروابط الداخلية (PageRank داخلي) — تقيس «أهمية» كل صفحة بحسب بنية الربط
الداخلي للموقع: الصفحات التي تتلقّى روابط أكثر (ومن صفحات مهمة) تحصل على درجة أعلى.

تُحسب على رسم الروابط الداخلية بين الصفحات المزحوفة فقط (خوارزمية PageRank التكرارية
مع damping وتعامل صحيح مع الصفحات بلا روابط صادرة «dangling»). الدرجة تُطبَّع 0–100
نسبةً لأعلى صفحة لتسهيل القراءة.
"""

from __future__ import annotations

from typing import Any

from utils.helpers import normalize_url


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def compute_link_score(
    pages: list[Any],
    links: list[dict[str, Any]],
    damping: float = 0.85,
    iterations: int = 30,
) -> dict[str, Any]:
    """يحسب درجة الروابط الداخلية لكل صفحة مزحوفة."""
    norm_to_url: dict[str, str] = {}
    for p in pages:
        u = _get(p, "url", "")
        if u:
            norm_to_url[normalize_url(u)] = u
    nodes = set(norm_to_url)
    if not nodes:
        return {"pages": [], "count": 0, "summary": {}}

    # إزالة تكرار الحواف الداخلية: روابط التنقّل/التذييل تتكرر عبر كل صفحة،
    # وحسابها مرّات متعدّدة يضخّم PageRank بشكل مصطنع. نحتفظ بحافة واحدة لكل (من، إلى).
    edge_set: set[tuple[str, str]] = set()
    for link in links:
        if not link.get("is_internal"):
            continue
        frm = normalize_url(link.get("from_url", ""))
        to = normalize_url(link.get("to_url_normalized") or link.get("to_url", ""))
        if frm in nodes and to in nodes and frm != to:
            edge_set.add((frm, to))

    out_edges: dict[str, list[str]] = {n: [] for n in nodes}
    in_deg: dict[str, int] = {n: 0 for n in nodes}
    for frm, to in edge_set:
        out_edges[frm].append(to)
        in_deg[to] += 1

    n = len(nodes)
    pr = {node: 1.0 / n for node in nodes}
    dangling = [node for node in nodes if not out_edges[node]]

    for _ in range(max(1, iterations)):
        dangling_mass = damping * sum(pr[d] for d in dangling) / n
        base = (1.0 - damping) / n + dangling_mass
        new_pr = {node: base for node in nodes}
        for node in nodes:
            outs = out_edges[node]
            if outs:
                share = damping * pr[node] / len(outs)
                for target in outs:
                    new_pr[target] += share
        pr = new_pr

    max_pr = max(pr.values()) if pr else 0.0
    rows: list[dict[str, Any]] = []
    for node in nodes:
        rows.append({
            "url": norm_to_url[node],
            "link_score": round(pr[node] / max_pr * 100, 2) if max_pr else 0.0,
            "raw_pagerank": round(pr[node], 8),
            "internal_inlinks": in_deg[node],
            "internal_outlinks": len(out_edges[node]),
        })
    rows.sort(key=lambda r: -r["link_score"])

    no_inlinks = sum(1 for r in rows if r["internal_inlinks"] == 0)
    return {
        "pages": rows,
        "count": len(rows),
        "summary": {
            "total_pages": len(rows),
            "pages_with_no_internal_inlinks": no_inlinks,
            "top": rows[:10],
            "weakest": [r for r in rows[-10:]][::-1],
        },
    }
