"""
analyzers/sitemap_diff.py
==========================
مقارنة بين الـ Sitemap والنتائج الفعلية للزحف.

يكشف مشاكل خطيرة لـ SEO:
1. صفحات في Sitemap لكنها 404
2. صفحات في Sitemap لكنها NoIndex (تناقض!)
3. صفحات في Sitemap لكنها Redirect
4. صفحات في Sitemap لكنها Canonicalised لصفحة أخرى
5. صفحات مزحوفة لكنها ليست في Sitemap (يجب إضافتها)
6. صفحات مهمة (depth=1) ليست في Sitemap
"""

from typing import Any

from utils.helpers import normalize_url


def diff_sitemap_vs_crawl(
    pages: list[Any],
    sitemap_urls: list[str],
) -> dict[str, Any]:
    """
    مقارنة شاملة بين sitemap و crawl results.

    Args:
        pages: قائمة PageData من الـ crawler
        sitemap_urls: قائمة URLs من الـ sitemap

    Returns:
        dict مع كل أنواع المشاكل المكتشفة
    """
    if not sitemap_urls and not pages:
        return {
            "sitemap_total": 0,
            "crawl_total": 0,
            "errors": ["لا توجد بيانات للمقارنة"],
        }

    # تطبيع URLs للمقارنة الدقيقة
    sitemap_set = {normalize_url(url) for url in sitemap_urls}

    def _get_url(p):
        """جلب URL من PageData أو dict."""
        if isinstance(p, dict):
            return p.get("url", "")
        return getattr(p, "url", "")

    crawled_set = {normalize_url(_get_url(p)) for p in pages if _get_url(p)}
    crawled_set.discard("")

    # تجميع الصفحات حسب URL للوصول السريع
    pages_by_url: dict[str, Any] = {}
    for p in pages:
        url = _get_url(p)
        if url:
            pages_by_url[normalize_url(url)] = p

    # === المقارنات ===

    # 1. في sitemap لكن 404
    sitemap_404 = []
    sitemap_redirects = []
    sitemap_noindex = []
    sitemap_canonicalised = []
    sitemap_not_crawled = []

    for sitemap_url in sitemap_set:
        page = pages_by_url.get(sitemap_url)

        if not page:
            sitemap_not_crawled.append(sitemap_url)
            continue

        # استخراج البيانات (سواء PageData أو dict)
        def attr(obj, name, default=None):
            if isinstance(obj, dict):
                return obj.get(name, default)
            return getattr(obj, name, default)

        status = attr(page, "status_code", 0)
        is_indexable = attr(page, "is_indexable", True)
        is_redirect = attr(page, "is_redirect", False)
        canonical = attr(page, "canonical", "")
        meta_robots = attr(page, "meta_robots", "") or ""
        x_robots = attr(page, "x_robots_tag", "") or ""

        # 404
        if 400 <= status < 500:
            sitemap_404.append({
                "url": sitemap_url,
                "status_code": status,
            })

        # Redirect
        if is_redirect or (300 <= status < 400):
            sitemap_redirects.append({
                "url": sitemap_url,
                "status_code": status,
                "redirects_to": attr(page, "final_url", ""),
            })

        # NoIndex
        combined_robots = (meta_robots + " " + x_robots).lower()
        if "noindex" in combined_robots:
            sitemap_noindex.append({
                "url": sitemap_url,
                "meta_robots": meta_robots,
                "x_robots_tag": x_robots,
            })

        # Canonicalised (canonical يشير لـ URL مختلف)
        if canonical and canonical != sitemap_url:
            normalized_canonical = normalize_url(canonical)
            if normalized_canonical != sitemap_url:
                sitemap_canonicalised.append({
                    "url": sitemap_url,
                    "canonical": canonical,
                })

    # 2. صفحات مزحوفة لكنها ليست في Sitemap
    not_in_sitemap = []
    important_pages_not_in_sitemap = []  # depth ≤ 2 + indexable

    for url, page in pages_by_url.items():
        if url in sitemap_set:
            continue

        def attr(obj, name, default=None):
            if isinstance(obj, dict):
                return obj.get(name, default)
            return getattr(obj, name, default)

        status = attr(page, "status_code", 0)
        is_indexable = attr(page, "is_indexable", True)
        depth = attr(page, "depth", 99)

        # فقط صفحات 200 وindexable
        if status != 200 or not is_indexable:
            continue

        entry = {
            "url": url,
            "depth": depth,
            "title": attr(page, "title", ""),
        }
        not_in_sitemap.append(entry)

        if depth <= 2:
            important_pages_not_in_sitemap.append(entry)

    # 3. إحصائيات
    return {
        "sitemap_total": len(sitemap_set),
        "crawl_total": len(crawled_set),
        "overlap": len(sitemap_set & crawled_set),
        "sitemap_only": len(sitemap_set - crawled_set),
        "crawl_only": len(crawled_set - sitemap_set),

        # 🔴 مشاكل حرجة في sitemap
        "sitemap_404_pages": sitemap_404,
        "sitemap_404_count": len(sitemap_404),
        "sitemap_redirects": sitemap_redirects,
        "sitemap_redirects_count": len(sitemap_redirects),
        "sitemap_noindex_pages": sitemap_noindex,
        "sitemap_noindex_count": len(sitemap_noindex),
        "sitemap_canonicalised": sitemap_canonicalised,
        "sitemap_canonicalised_count": len(sitemap_canonicalised),
        "sitemap_not_crawled": sitemap_not_crawled,  # URLs لم نصل إليها

        # 🟠 فرص ضائعة
        "pages_not_in_sitemap": not_in_sitemap,
        "pages_not_in_sitemap_count": len(not_in_sitemap),
        "important_pages_missing_from_sitemap": important_pages_not_in_sitemap,
        "important_pages_missing_count": len(important_pages_not_in_sitemap),

        "summary": {
            "sitemap_quality_issues": (
                len(sitemap_404)
                + len(sitemap_redirects)
                + len(sitemap_noindex)
                + len(sitemap_canonicalised)
            ),
            "coverage_percentage": round(
                (len(sitemap_set & crawled_set) / max(len(sitemap_set), 1)) * 100, 2
            ) if sitemap_set else 0,
        },
    }
