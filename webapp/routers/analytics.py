"""
webapp/routers/analytics.py — قراءة فقط على audit JSON: pages/compare/url-detail/graph/priority.

نُقلت من webapp/app.py في v1.12.5 (REFACTOR-app-routers الخطوة الخامسة).

Endpoints (كلّها read-only — لا تغيّر الحالة):
    GET  /api/jobs/{job_id}/pages       — صفوف الصفحات (للمستكشف)
    GET  /api/jobs/list                  — مهام لها audit JSON (للمقارنة)
    GET  /api/jobs/{job_id}/compare      — مقارنة زمنيّة مع زحف آخر
    GET  /api/jobs/{job_id}/url-detail   — تفاصيل شاملة لرابط واحد
    GET  /api/jobs/{job_id}/graph        — شجرة URL + رسم بياني للروابط
    GET  /api/jobs/{job_id}/priority     — بيانات محرّك الأولويات + لوحة العمل
"""

from __future__ import annotations

import json as _json
import logging
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from webapp.constants import MAX_AUDIT_JSON_MB
from webapp.deps import runner

log = logging.getLogger("sct.webapp")

router = APIRouter()

# الحقول المعروضة في مستكشف الصفحات — هي subset خفيف، تُحدَّد هنا لا في الـpayload.
_PAGE_FIELDS = [
    "url", "status_code", "is_indexable", "depth", "content_type", "title",
    "title_length", "meta_description_length", "h1_count", "canonical",
    "word_count", "internal_links_count", "external_links_count",
]


@router.get("/api/jobs/{job_id}/pages")
async def job_pages(job_id: str):
    """إرجاع صفوف الصفحات (حقول مختارة) للتصفية في المتصفح."""
    meta = runner.meta(job_id)
    json_path = meta.get("result", {}).get("json")
    if not json_path or not Path(json_path).exists():
        return JSONResponse({"pages": [], "error": "no audit json"}, status_code=404)
    size_mb = Path(json_path).stat().st_size / (1024 * 1024)
    if size_mb > MAX_AUDIT_JSON_MB:
        return JSONResponse({
            "pages": [],
            "error": f"audit JSON too large ({size_mb:.0f} MB) to load in the explorer; "
                     f"open output/csv/pages.csv instead",
        }, status_code=413)
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            audit = _json.load(f)
    except (OSError, ValueError):
        return JSONResponse({"pages": [], "error": "read error"}, status_code=500)
    rows = []
    for p in audit.get("pages", []):
        rows.append({k: p.get(k) for k in _PAGE_FIELDS})
    return JSONResponse({"pages": rows, "count": len(rows)})


@router.get("/api/jobs/list")
async def jobs_list_with_audit():
    """قائمة المهام السابقة التي لديها audit JSON — لاختيار «المقارنة مع»."""
    out = []
    for m in runner.list_jobs() or []:
        if not isinstance(m, dict):
            continue
        jid = m.get("job_id") or ""
        json_path = ((m.get("result") or {}) or {}).get("json") or ""
        if not jid or not json_path or not Path(json_path).exists():
            continue
        out.append({
            "job_id": jid,
            "url": m.get("url", ""),
            "mode": m.get("mode", ""),
            "started_at": m.get("started_at", ""),
            "status": m.get("status", ""),
        })
    return JSONResponse({"jobs": out, "count": len(out)})


@router.get("/api/jobs/{job_id}/compare")
async def jobs_compare(job_id: str, with_: str = Query("", alias="with")):
    """مقارنة زمنية بين زحفتين لنفس الموقع (compare_crawls)."""
    other = (with_ or "").strip()
    if not other:
        return JSONResponse({"error": "missing 'with' job id"}, status_code=400)
    meta_a = runner.meta(job_id)
    meta_b = runner.meta(other)
    if not meta_a or not meta_b:
        return JSONResponse({"error": "job not found"}, status_code=404)
    path_a = (meta_a.get("result") or {}).get("json")
    path_b = (meta_b.get("result") or {}).get("json")
    if not path_a or not Path(path_a).exists() or not path_b or not Path(path_b).exists():
        return JSONResponse({"error": "audit json missing for one of the jobs"},
                            status_code=404)
    # حارس الحجم: لا نحمّل ملفات ضخمة
    for p in (path_a, path_b):
        size_mb = Path(p).stat().st_size / (1024 * 1024)
        if size_mb > MAX_AUDIT_JSON_MB:
            return JSONResponse({
                "error": f"audit JSON too large ({size_mb:.0f} MB) — set "
                         f"output.json_full=false to keep it light",
            }, status_code=413)
    try:
        from analyzers.crawl_compare import compare_audit_files
        res = compare_audit_files(path_a, path_b)
    except Exception as e:  # noqa: BLE001
        log.exception("audit compare failed")
        return JSONResponse({"error": str(e)[:300]}, status_code=500)
    res["old"] = {"job_id": job_id, "url": meta_a.get("url", "")}
    res["new"] = {"job_id": other, "url": meta_b.get("url", "")}
    return JSONResponse(res)


@router.get("/api/jobs/{job_id}/url-detail")
async def job_url_detail(job_id: str, url: str = ""):
    """تفاصيل شاملة لرابط واحد (الزحف + GSC + GA4 + PageSpeed + الأولوية + الوصولية)."""
    if not url.strip():
        return JSONResponse({"error": "missing url"}, status_code=400)
    meta = runner.meta(job_id)
    json_path = meta.get("result", {}).get("json")
    if not json_path or not Path(json_path).exists():
        return JSONResponse({"error": "no audit json"}, status_code=404)
    size_mb = Path(json_path).stat().st_size / (1024 * 1024)
    if size_mb > MAX_AUDIT_JSON_MB:
        return JSONResponse({
            "error": f"audit JSON too large ({size_mb:.0f} MB); open output/csv/pages.csv instead",
        }, status_code=413)
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            audit = _json.load(f)
    except (OSError, ValueError):
        return JSONResponse({"error": "read error"}, status_code=500)
    from reporting.url_detail import build_url_detail
    return JSONResponse(build_url_detail(audit, url.strip()))


@router.get("/api/jobs/{job_id}/graph")
async def jobs_graph(job_id: str):
    """يبني تمثيل شجريّ + توزيعات + قائمة جوار للروابط الداخلية من audit JSON."""
    meta = runner.meta(job_id)
    json_path = (meta.get("result") or {}).get("json")
    if not json_path or not Path(json_path).exists():
        return JSONResponse({"error": "no audit json"}, status_code=404)
    size_mb = Path(json_path).stat().st_size / (1024 * 1024)
    if size_mb > MAX_AUDIT_JSON_MB:
        return JSONResponse({
            "error": f"audit JSON too large ({size_mb:.0f} MB); use pages.csv instead",
        }, status_code=413)
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            audit = _json.load(f)
    except (OSError, ValueError):
        return JSONResponse({"error": "read error"}, status_code=500)

    # v1.13.22: audit JSON يستبعد raw arrays افتراضياً منذ v1.13 (المفتاح
    # raw_arrays_omitted موجود). لكن graph يحتاج links فعلياً — نقرأها من
    # inlinks.csv الذي هو أخف من all_links.csv (يحوي internal فقط بلا images).
    if not audit.get("links"):
        audit["links"] = _load_links_from_csv(Path(json_path).parent / "csv")

    return JSONResponse(_build_graph_payload(audit))


def _load_links_from_csv(csv_dir: Path) -> list[dict[str, Any]]:
    """v1.13.22: يقرأ inlinks.csv (أخف من all_links) لبناء graph payload حين
    audit JSON يستبعد raw arrays. حدّ عملي 5000 صفّ (نفس حدّ _build_graph_payload).
    inlinks.csv يحوي is_internal حقيقي (bool) — يكفي المطابقة مع الشرط الموجود.
    """
    import csv as _csv
    p = csv_dir / "inlinks.csv"
    if not p.exists():
        p = csv_dir / "all_links.csv"
        if not p.exists():
            return []
    out: list[dict[str, Any]] = []
    try:
        with open(p, "r", encoding="utf-8-sig", newline="") as f:
            reader = _csv.DictReader(f)
            for row in reader:
                if len(out) >= 5000:
                    break
                out.append({
                    "from_url": row.get("from_url", ""),
                    "to_url": row.get("to_url", ""),
                    "is_internal": row.get("is_internal", "true"),
                })
    except (OSError, _csv.Error):
        return []
    return out


def _build_graph_payload(audit: dict[str, Any]) -> dict[str, Any]:
    """v1.04: يحوّل audit JSON إلى:
    - tree: شجرة URL هرميّة من مسارات pages (الأنفع للمستخدم العام)
    - by_depth / by_status: توزيع للرسم البياني
    - graph: nodes+edges للروابط الداخلية (يُحدّ على 500 عقدة للحفاظ على أداء المتصفّح)
    """
    pages = audit.get("pages") or []
    links = audit.get("links") or []
    site_url = (audit.get("site_config") or {}).get("start_url", "")
    domain = urlparse(site_url).netloc or ""

    # --- توزيعات depth + status ---
    by_depth: Counter = Counter()
    by_status: Counter = Counter()
    for p in pages:
        d = p.get("depth") if isinstance(p, dict) else getattr(p, "depth", None)
        s = p.get("status_code") if isinstance(p, dict) else getattr(p, "status_code", None)
        if d is not None:
            by_depth[int(d)] += 1
        if s is not None:
            by_status[str(s)] += 1

    # --- شجرة URL هرميّة (path segments) ---
    root: dict[str, Any] = {"name": "/", "count": 0, "status": None, "children": {}}
    for p in pages:
        url = p.get("url") if isinstance(p, dict) else getattr(p, "url", "")
        status = p.get("status_code") if isinstance(p, dict) else getattr(p, "status_code", None)
        parsed = urlparse(url)
        segments = [s for s in parsed.path.split("/") if s]
        cur = root
        cur["count"] += 1
        for seg in segments:
            children = cur["children"]
            if seg not in children:
                children[seg] = {"name": seg, "count": 0, "status": None, "children": {}}
            cur = children[seg]
            cur["count"] += 1
            # نُسجّل الحالة الأسوأ في الفرع (404 يُحجب الفرع كأحمر)
            if status:
                cur_st = cur["status"]
                if not cur_st or (isinstance(status, int) and status >= 400 and
                                  (not isinstance(cur_st, int) or status > cur_st)):
                    cur["status"] = status
        # ورقة: نضع الـURL الكامل عند نهاية المسار
        cur["url"] = url
        cur["status"] = status

    def _to_array(node):
        children = node.pop("children", {}) or {}
        node["children"] = sorted(
            (_to_array(c) for c in children.values()),
            key=lambda x: (-x["count"], x["name"]),
        )
        return node
    tree = _to_array(root)

    # --- قائمة جوار للروابط الداخلية (محدودة للحفاظ على أداء المتصفّح) ---
    MAX_GRAPH_NODES = 500
    nodes_idx: dict[str, int] = {}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, int]] = []
    truncated = False

    def _ensure_node(url: str, status=None, depth=None) -> int:
        if url in nodes_idx:
            return nodes_idx[url]
        if len(nodes) >= MAX_GRAPH_NODES:
            return -1
        nodes_idx[url] = len(nodes)
        nodes.append({
            "id": len(nodes),
            "url": url,
            "label": (urlparse(url).path or "/")[:40],
            "status": status,
            "depth": depth,
        })
        return nodes_idx[url]

    # نُضيف صفحات الزحف أوّلاً (الأولوية للأكثر إنلِنكاً)
    for p in pages[:MAX_GRAPH_NODES]:
        url = p.get("url") if isinstance(p, dict) else getattr(p, "url", "")
        if url:
            _ensure_node(
                url,
                p.get("status_code") if isinstance(p, dict) else getattr(p, "status_code", None),
                p.get("depth") if isinstance(p, dict) else getattr(p, "depth", None),
            )
    if len(pages) > MAX_GRAPH_NODES:
        truncated = True

    for link in (links or [])[:5000]:
        if not isinstance(link, dict):
            continue
        if link.get("is_internal") in (False, "False", "false", 0, "0"):
            continue
        src = link.get("from_url") or link.get("source_url")
        dst = link.get("to_url") or link.get("target_url")
        if not src or not dst:
            continue
        si = nodes_idx.get(src)
        di = nodes_idx.get(dst)
        if si is None or di is None:
            continue
        edges.append({"s": si, "t": di})

    return {
        "domain": domain,
        "total_pages": len(pages),
        "by_depth": dict(sorted(by_depth.items())),
        "by_status": dict(sorted(by_status.items())),
        "tree": tree,
        "graph": {
            "nodes": nodes,
            "edges": edges,
            "truncated": truncated,
            "max_nodes": MAX_GRAPH_NODES,
        },
    }


@router.get("/api/jobs/{job_id}/priority")
async def job_priority(job_id: str):
    """إرجاع بيانات محرّك الأولويات (الصفحات + ملخّص لوحة العمل) للعرض في المتصفح."""
    meta = runner.meta(job_id)
    json_path = meta.get("result", {}).get("json")
    if not json_path or not Path(json_path).exists():
        return JSONResponse({"pages": [], "error": "no audit json"}, status_code=404)
    size_mb = Path(json_path).stat().st_size / (1024 * 1024)
    if size_mb > MAX_AUDIT_JSON_MB:
        return JSONResponse({
            "pages": [],
            "error": f"audit JSON too large ({size_mb:.0f} MB); "
                     f"open output/csv/page_priority.csv instead",
        }, status_code=413)
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            audit = _json.load(f)
    except (OSError, ValueError):
        return JSONResponse({"pages": [], "error": "read error"}, status_code=500)
    prio = audit.get("priority", {}) or {}
    pages = prio.get("pages", []) or []
    return JSONResponse({
        "pages": pages,
        "summary": prio.get("summary", {}) or {},
        "count": len(pages),
    })
