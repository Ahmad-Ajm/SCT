"""
services/analysis_service.py — تشغيل Phase 2 (المحلّلات) حسب الـmode.

نُقل من main.py في v1.12 (Tier 2 mid-tier — يعتمد على analyzers/* lazy + utils
+ services/export_helpers لـget_value).

ملاحظة معماريّة: lazy imports لجميع analyzers مُحافَظ عليها كما كانت — تُتيح
--integrations-only و--analyze-only بلا تثبيت كلّ الـanalyzers، وتُسرّع
startup CLI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from services.export_helpers import get_value
from utils.logger import get_logger
from services.progress_service import emit_phase
from utils.monitoring import gauge, span

if TYPE_CHECKING:
    from modes.base import CrawlMode

log = get_logger(__name__)


def run_analysis(
    crawler,
    config: dict[str, Any],
    mode: CrawlMode,
) -> dict[str, Any]:
    """تشغيل المحلّلات حسب الـ mode."""
    from analyzers.broken_links import detect_broken_links
    from analyzers.canonical_analyzer import analyze_canonicals
    from analyzers.duplicate_detector import detect_duplicates
    from analyzers.hreflang_validator import validate_hreflang
    from analyzers.images_analyzer import analyze_images
    from analyzers.orphan_finder import find_orphan_pages
    from analyzers.redirect_analyzer import analyze_redirects
    from analyzers.schema_validator import validate_schemas
    from analyzers.security_analyzer import analyze_security
    from analyzers.seo_issues import collect_seo_issues
    from analyzers.sitemap_diff import diff_sitemap_vs_crawl
    from analyzers.thin_content import detect_thin_content
    from analyzers.url_issues import analyze_url_issues

    log.info("=" * 60)
    log.info(f"Phase 2: Analysis ({mode.name} mode)")
    log.info("=" * 60)

    enabled_analyzers = set(mode.get_analyzers())

    pages = crawler.get_pages()
    links = crawler.get_links()
    images = crawler.get_images()
    redirects = crawler.get_redirects()
    schema_entries = crawler.get_schema()
    gauge("analysis.input.pages", len(pages))
    gauge("analysis.input.links", len(links))
    gauge("analysis.input.images", len(images))
    gauge("analysis.input.redirects", len(redirects))
    gauge("analysis.input.schema_entries", len(schema_entries))

    results: dict[str, Any] = {}

    # v1.13.25: كل خطوة محلّل تُسجَّل في اللوغ وتُبثّ لسطر النشاط الحيّ كي لا
    # تبدو مرحلة التحليل معلّقة (بعض الخطوات مثل PageRank تأخذ دقيقة على المواقع
    # الكبيرة). عدّاد خطوات تقريبيّ لتحريك شريط التقدّم.
    _steps_total = 18
    _step_i = {"n": 0}

    def _astep(detail: str) -> None:
        _step_i["n"] += 1
        log.info(f"→ {detail}")
        try:
            emit_phase(crawler, "analyzing", phase_label="analyzing",
                       phase_detail=detail,
                       phase_percent=int(_step_i["n"] * 100 / _steps_total))
        except Exception:  # noqa: BLE001
            pass

    if "duplicates" in enabled_analyzers:
        _astep("Detecting duplicates...")
        with span("analysis.duplicates", pages=len(pages)):
            results["duplicate_data"] = detect_duplicates(pages)
    else:
        results["duplicate_data"] = {}

    if "orphans" in enabled_analyzers:
        _astep("Finding orphan pages...")
        with span("analysis.orphans", pages=len(pages), links=len(links)):
            results["orphan_data"] = find_orphan_pages(pages, links)
    else:
        results["orphan_data"] = {}

    if "redirects" in enabled_analyzers:
        _astep("Analyzing redirects...")
        with span("analysis.redirects", redirects=len(redirects)):
            results["redirect_data"] = analyze_redirects(
                pages,
                redirects,
                primary_domain=config.get("site", {}).get("domain", ""),
                additional_domains=config.get("site", {}).get("additional_internal_domains", []),
            )
    else:
        results["redirect_data"] = {}

    analysis_config = config.get("analysis", {})

    if "thin_content" in enabled_analyzers:
        _astep("Detecting thin content...")
        with span("analysis.thin_content", pages=len(pages)):
            results["thin_content_data"] = detect_thin_content(
                pages,
                word_threshold=analysis_config.get("thin_content_threshold", 300),
                critical_threshold=analysis_config.get("thin_content_critical_threshold", 100),
                text_ratio_threshold=analysis_config.get("text_ratio_threshold", 10.0),
            )
    else:
        results["thin_content_data"] = {}

    if "broken_links" in enabled_analyzers:
        _astep("Detecting broken links...")
        with span("analysis.broken_links", pages=len(pages), links=len(links)):
            results["broken_data"] = detect_broken_links(pages, links)
        bd = results["broken_data"]
        log.info(
            f"   4xx: {len(bd.get('pages_4xx', []))} | 5xx: {len(bd.get('pages_5xx', []))} "
            f"| 404 بروابط واردة: {len(bd.get('pages_404_with_inlinks', []))}"
        )
    else:
        results["broken_data"] = {}

    if "images" in enabled_analyzers:
        _astep("Analyzing images...")
        with span("analysis.images", images=len(images)):
            results["images_analysis"] = analyze_images(images)
    else:
        results["images_analysis"] = {}

    if "url_issues" in enabled_analyzers:
        _astep("Analyzing URL issues...")
        with span("analysis.url_issues", pages=len(pages)):
            results["url_issues"] = analyze_url_issues(
                pages,
                max_length=analysis_config.get("url_max_length", 115),
                max_query_params=analysis_config.get("url_max_query_params", 5),
                flag_non_ascii=analysis_config.get("url_flag_non_ascii", False),
            )
    else:
        results["url_issues"] = {}

    if "canonicals" in enabled_analyzers:
        _astep("Analyzing canonicals...")
        with span("analysis.canonicals", pages=len(pages)):
            results["canonical_data"] = analyze_canonicals(
                pages,
                primary_domain=config.get("site", {}).get("domain", ""),
                additional_domains=config.get("site", {}).get("additional_internal_domains", []),
            )
    else:
        results["canonical_data"] = {}

    # === التحسينات v3.0 ===
    if "schema_validator" in enabled_analyzers:
        _astep("Validating Schema.org...")
        with span("analysis.schema_validator", schema_entries=len(schema_entries)):
            results["schema_validation"] = validate_schemas(schema_entries)
        sv = results["schema_validation"]
        log.info(f"   Total schemas: {sv['total_schemas']}")
        log.info(f"   Rich Result eligible: {len(sv.get('rich_result_eligible', []))}")
        log.info(f"   Invalid (missing required): {len(sv.get('invalid_schemas', []))}")
    else:
        results["schema_validation"] = {}

    if "hreflang_validator" in enabled_analyzers:
        _astep("Validating Hreflang...")
        with span("analysis.hreflang_validator", pages=len(pages)):
            results["hreflang_validation"] = validate_hreflang(pages)
        hv = results["hreflang_validation"]
        if hv.get("total_pages_with_hreflang", 0) > 0:
            log.info(f"   Pages with hreflang: {hv['total_pages_with_hreflang']}")
            log.info(f"   Non-reciprocal: {hv.get('non_reciprocal_count', 0)}")
            log.info(f"   Missing x-default: {hv.get('missing_x_default_count', 0)}")
    else:
        results["hreflang_validation"] = {}

    if "sitemap_diff" in enabled_analyzers:
        _astep("Comparing Sitemap vs Crawl...")
        # نأخذ sitemap URLs الكاملة من crawler (تراكمية عبر كل الـ sitemaps)
        sitemap_urls = list(getattr(crawler, "sitemap_urls_seen", []) or [])
        if not sitemap_urls and hasattr(crawler, "sitemap_parser") and crawler.sitemap_parser:
            # fallback قديم: آخر sitemap فقط
            for entry in getattr(crawler.sitemap_parser, "_all_entries", []):
                sitemap_urls.append(entry.url)
        with span("analysis.sitemap_diff", pages=len(pages), sitemap_urls=len(sitemap_urls)):
            results["sitemap_diff"] = diff_sitemap_vs_crawl(pages, sitemap_urls)
        sd = results["sitemap_diff"]
        if sd.get("sitemap_total", 0) > 0:
            log.info(f"   Sitemap URLs: {sd['sitemap_total']}")
            log.info(f"   Coverage: {sd['summary']['coverage_percentage']}%")
            log.info(f"   404 in sitemap: {sd.get('sitemap_404_count', 0)}")
    else:
        results["sitemap_diff"] = {}

    # === Pagination (rel=next/prev) — يعمل تلقائياً عند وجود صفحات مرقّمة ===
    if any(get_value(p, "is_paginated") for p in pages):
        from analyzers.pagination_analyzer import analyze_pagination
        _astep("Analyzing pagination...")
        with span("analysis.pagination", pages=len(pages)):
            results["pagination_data"] = analyze_pagination(pages)
        pgd = results["pagination_data"]
        log.info(f"   Paginated: {pgd['total_paginated']} | issues: {pgd['issues_count']}")
    else:
        results["pagination_data"] = {}

    # === درجة الروابط الداخلية (PageRank داخلي) ===
    if links:
        from analyzers.link_score import compute_link_score
        _astep("Computing internal link score...")
        with span("analysis.link_score", pages=len(pages), links=len(links)):
            results["link_score"] = compute_link_score(pages, links)
        ls = results["link_score"].get("summary", {})
        log.info(f"   Pages scored: {results['link_score'].get('count', 0)} | "
                 f"no internal inlinks: {ls.get('pages_with_no_internal_inlinks', 0)}")
    else:
        results["link_score"] = {}

    # === التدقيق الإملائي (اختياري، مطفأ افتراضياً) ===
    if analysis_config.get("spell_check"):
        from analyzers.spell_check import run_spell_check
        _astep("Spell check...")
        with span("analysis.spell_check", pages=len(pages)):
            results["spelling"] = run_spell_check(
                pages, max_pages=int(analysis_config.get("spell_check_max_pages", 0) or 0))
        st = results["spelling"].get("status", "")
        log.info(f"   Spelling: {st} (checked {results['spelling'].get('checked_pages', 0)})")
    else:
        results["spelling"] = {}

    # === التشابه التقريبي بين الصفحات (Near-Duplicate) ===
    if any(get_value(p, "content_simhash") for p in pages):
        from analyzers.near_duplicate import detect_near_duplicates
        _astep("Detecting near-duplicate content...")
        with span("analysis.near_duplicate", pages=len(pages)):
            results["near_duplicate"] = detect_near_duplicates(pages)
        log.info(f"   Near-duplicate pairs: {results['near_duplicate'].get('pairs_count', 0)}")
    else:
        results["near_duplicate"] = {}

    # === Resource Inventory (الخطة #3) ===
    resources = getattr(crawler, "get_resources", lambda: [])()
    if resources:
        from analyzers.resources_analyzer import analyze_resources
        _astep("Analyzing resources...")
        with span("analysis.resources", resources=len(resources)):
            results["resources_data"] = analyze_resources(resources)
        rdz = results["resources_data"]
        log.info(f"   Resources: {rdz['total']} (unique {rdz['unique']}) | "
                 f"external {rdz['external_count']} | mixed {rdz['mixed_content_count']}")
    else:
        results["resources_data"] = {}

    # === Security headers (الخطة #8) ===
    if "security" in enabled_analyzers:
        _astep("Analyzing security headers...")
        sec_headers = crawler.get_headers()
        with span("analysis.security", pages=len(pages), headers=len(sec_headers)):
            results["security_data"] = analyze_security(pages, sec_headers)
        sd2 = results["security_data"]
        log.info(f"   Pages checked: {sd2['pages_checked']} | not HTTPS: {sd2['not_https_count']}")
    else:
        results["security_data"] = {}

    # === SEO Issues تجميع شامل ===
    if "seo_issues" in enabled_analyzers:
        _astep("Collecting SEO issues...")
        with span("analysis.seo_issues", pages=len(pages)):
            results["seo_issues"] = collect_seo_issues(
                pages=pages,
                duplicate_data=results["duplicate_data"],
                orphan_data=results["orphan_data"],
                redirect_data=results["redirect_data"],
                thin_content_data=results["thin_content_data"],
                broken_data=results["broken_data"],
                images_data=results["images_analysis"],
                url_issues=results["url_issues"],
                canonical_data=results["canonical_data"],
                config=config,
            )
            # إثراء المشاكل بتلميحات الأثر/الجهد و«لماذا/كيف» (IMP-8)
            from analyzers.hints import attach_hints
            attach_hints(results["seo_issues"])
        summary = results["seo_issues"]["summary"]
        log.info(f"  🔴 Critical: {summary['critical_count']}")
        log.info(f"  🟠 High:     {summary['high_count']}")
        log.info(f"  🟡 Medium:   {summary['medium_count']}")
        log.info(f"  🟢 Low:      {summary['low_count']}")
    else:
        results["seo_issues"] = {"all_issues": [], "summary": {}}

    return results
