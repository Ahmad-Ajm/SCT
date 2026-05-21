"""
analyzers — تحليل البيانات بعد انتهاء الزحف لاكتشاف المشاكل.

كل analyzer يأخذ بيانات الـ Crawler ويُرجع قائمة مشاكل/تحليلات.
"""
from analyzers.duplicate_detector import detect_duplicates
from analyzers.orphan_finder import find_orphan_pages
from analyzers.redirect_analyzer import analyze_redirects
from analyzers.thin_content import detect_thin_content
from analyzers.broken_links import detect_broken_links
from analyzers.images_analyzer import analyze_images
from analyzers.seo_issues import collect_seo_issues
from analyzers.schema_validator import validate_schemas
from analyzers.sitemap_diff import diff_sitemap_vs_crawl
from analyzers.hreflang_validator import validate_hreflang

__all__ = [
    "detect_duplicates",
    "find_orphan_pages",
    "analyze_redirects",
    "detect_thin_content",
    "detect_broken_links",
    "analyze_images",
    "collect_seo_issues",
    "validate_schemas",
    "diff_sitemap_vs_crawl",
    "validate_hreflang",
]
