"""
analyzers/canonical_analyzer.py
===============================
Canonical diagnostics for crawled pages.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from utils.helpers import normalize_url


def analyze_canonicals(
    pages: list[Any],
    primary_domain: str = "",
    additional_domains: list[str] | None = None,
) -> dict[str, Any]:
    """Detect common canonical implementation problems."""
    additional_domains = additional_domains or []
    by_url = {normalize_url(_get(page, "url", "")): page for page in pages if _get(page, "url", "")}

    missing = []
    canonicalized = []
    canonical_to_non_200 = []
    canonical_to_non_indexable = []
    canonical_external = []
    canonical_loops = []
    canonical_chains = []

    for page in pages:
        url = normalize_url(_get(page, "url", ""))
        if not url:
            continue
        status_code = int(_get(page, "status_code", 0) or 0)
        is_indexable = bool(_get(page, "is_indexable", False))
        canonical = normalize_url(_get(page, "canonical", "") or "") if _get(page, "canonical", "") else ""

        if status_code == 200 and is_indexable and not canonical:
            missing.append({"url": url})
            continue

        if not canonical:
            continue

        if canonical != url:
            canonicalized.append({"url": url, "canonical": canonical})

        if not _is_internal(canonical, primary_domain, additional_domains):
            canonical_external.append({"url": url, "canonical": canonical})

        target = by_url.get(canonical)
        if target is None:
            continue

        target_status = int(_get(target, "status_code", 0) or 0)
        target_indexable = bool(_get(target, "is_indexable", False))
        target_canonical = normalize_url(_get(target, "canonical", "") or "") if _get(target, "canonical", "") else ""

        if target_status and target_status != 200:
            canonical_to_non_200.append(
                {"url": url, "canonical": canonical, "canonical_status": target_status}
            )
        if target_status == 200 and not target_indexable:
            canonical_to_non_indexable.append({"url": url, "canonical": canonical})
        if target_canonical and target_canonical == url and canonical != url:
            canonical_loops.append({"url": url, "canonical": canonical})
        elif target_canonical and target_canonical != canonical:
            canonical_chains.append(
                {"url": url, "canonical": canonical, "next_canonical": target_canonical}
            )

    return {
        "missing_canonicals": missing,
        "missing_canonicals_count": len(missing),
        "canonicalized_pages": canonicalized,
        "canonicalized_pages_count": len(canonicalized),
        "canonical_to_non_200": canonical_to_non_200,
        "canonical_to_non_200_count": len(canonical_to_non_200),
        "canonical_to_non_indexable": canonical_to_non_indexable,
        "canonical_to_non_indexable_count": len(canonical_to_non_indexable),
        "canonical_external": canonical_external,
        "canonical_external_count": len(canonical_external),
        "canonical_loops": canonical_loops,
        "canonical_loops_count": len(canonical_loops),
        "canonical_chains": canonical_chains,
        "canonical_chains_count": len(canonical_chains),
    }


def _get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _is_internal(url: str, primary_domain: str, additional_domains: list[str]) -> bool:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if not host:
        return True
    domains = [primary_domain, *additional_domains]
    clean_domains = [domain.lower().removeprefix("www.") for domain in domains if domain]
    return any(host == domain or host.endswith("." + domain) for domain in clean_domains)
