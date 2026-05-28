"""
analyzers/resources_analyzer.py
===============================
ملخّص جرد الموارد: العدد حسب النوع، داخلي/خارجي، المحتوى المختلط،
والموارد المكسورة (4xx/5xx) إن توفّرت حالتها.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def analyze_resources(resources: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: Counter = Counter()
    internal = external = mixed = 0
    unique_urls: set[str] = set()
    mixed_list: list[dict[str, Any]] = []
    broken_list: list[dict[str, Any]] = []
    external_list: list[dict[str, Any]] = []

    for r in resources:
        by_type[r.get("resource_type", "other")] += 1
        unique_urls.add(r.get("url", ""))
        if r.get("is_internal"):
            internal += 1
        else:
            external += 1
            external_list.append(r)
        if r.get("is_mixed_content"):
            mixed += 1
            mixed_list.append(r)
        status = r.get("status_code")
        if isinstance(status, int) and status >= 400:
            broken_list.append(r)

    return {
        "total": len(resources),
        "unique": len(unique_urls),
        "by_type": dict(by_type),
        "internal_count": internal,
        "external_count": external,
        "mixed_content_count": mixed,
        "broken_count": len(broken_list),
        "mixed_content": mixed_list[:500],
        "broken_resources": broken_list[:500],
        "external_resources_sample": external_list[:200],
        "summary": {
            "total": len(resources),
            "unique": len(unique_urls),
            "internal": internal,
            "external": external,
            "mixed_content": mixed,
            "broken": len(broken_list),
            **{f"type_{k}": v for k, v in by_type.items()},
        },
    }
