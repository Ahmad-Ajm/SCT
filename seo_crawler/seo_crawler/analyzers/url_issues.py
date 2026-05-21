"""
analyzers/url_issues.py
=======================
Detect URL hygiene issues that commonly affect crawling, sharing, and SEO.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from urllib.parse import parse_qsl, urlparse


TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "fbclid",
    "gclid",
    "msclkid",
    "ref",
    "ref_src",
}


def analyze_url_issues(
    pages: list[Any],
    max_length: int = 115,
    max_query_params: int = 5,
) -> dict[str, Any]:
    """Analyze crawled page URLs for technical SEO hygiene issues."""
    issues = {
        "long_urls": [],
        "uppercase_urls": [],
        "underscore_urls": [],
        "too_many_query_params": [],
        "tracking_params": [],
        "fragment_urls": [],
        "non_ascii_urls": [],
        "duplicate_paths": [],
    }

    path_groups: dict[str, list[str]] = defaultdict(list)

    for page in pages:
        url = _get(page, "url", "")
        status_code = int(_get(page, "status_code", 0) or 0)
        if not url or status_code >= 400:
            continue

        parsed = urlparse(url)
        path = parsed.path or "/"
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        query_keys = {key.lower() for key, _ in query_pairs}

        if len(url) > max_length:
            issues["long_urls"].append(_row(url, length=len(url), max_length=max_length))
        if any(ch.isupper() for ch in path):
            issues["uppercase_urls"].append(_row(url, path=path))
        if "_" in path:
            issues["underscore_urls"].append(_row(url, path=path))
        if len(query_pairs) > max_query_params:
            issues["too_many_query_params"].append(
                _row(url, query_params=len(query_pairs), max_query_params=max_query_params)
            )
        tracking_found = sorted(query_keys & TRACKING_PARAMS)
        if tracking_found:
            issues["tracking_params"].append(_row(url, params=tracking_found))
        if parsed.fragment:
            issues["fragment_urls"].append(_row(url, fragment=parsed.fragment))
        if not _is_ascii(url):
            issues["non_ascii_urls"].append(_row(url))

        normalized_path = path.rstrip("/").lower() or "/"
        path_groups[normalized_path].append(url)

    for normalized_path, urls in sorted(path_groups.items()):
        unique_urls = sorted(set(urls))
        if len(unique_urls) > 1:
            issues["duplicate_paths"].append(
                {
                    "normalized_path": normalized_path,
                    "count": len(unique_urls),
                    "urls": unique_urls,
                }
            )

    counts = {f"{name}_count": len(rows) for name, rows in issues.items()}
    return {
        **issues,
        **counts,
        "total_issues": sum(len(rows) for rows in issues.values()),
    }


def _row(url: str, **extra: Any) -> dict[str, Any]:
    return {"url": url, **extra}


def _get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _is_ascii(value: str) -> bool:
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        return False
    return True
