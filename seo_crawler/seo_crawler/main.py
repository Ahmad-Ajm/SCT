"""
main.py
========
SEO Crawler - نقطة البداية v3.0

التحسينات الجديدة في v3.0:
1. ✅ --mode (audit / competitor / compare)
2. ✅ Schema.org Validator (20+ نوع، Rich Results check)
3. ✅ Sitemap vs Crawl Diff (مشاكل sitemap)
4. ✅ Hreflang Validator (reciprocity, x-default, etc.)
5. ✅ كود generic بالكامل (قابل للنشر على GitHub)

الاستخدام:
    # وضع التدقيق الكامل (الافتراضي)
    python main.py
    python main.py --mode audit

    # تحليل منافس (محترم وخفيف)
    python main.py --mode competitor --url https://competitor.com/

    # مقارنة عدة مواقع
    python main.py --mode compare

    # خيارات أخرى
    python main.py --config custom.yaml
    python main.py --sync          # النسخة sync القديمة
    python main.py --no-resume     # بدء جديد
    python main.py --skip-external # تخطّي فحص الروابط الخارجية
    python main.py --clear-cache   # مسح API cache
    python main.py --analyze-only  # استخدم DB الموجود
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TYPE_CHECKING
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv

from modes import get_mode, AVAILABLE_MODES


def configure_stdio() -> None:
    """Prefer UTF-8 output on Windows terminals that default to cp125x."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (TypeError, ValueError):
            pass


configure_stdio()

from utils.logger import configure_logging, get_logger
from utils.monitoring import (
    configure_monitoring,
    gauge,
    increment,
    reset_monitoring,
    span,
    write_metrics,
)

if TYPE_CHECKING:
    from crawler.async_core import AsyncCrawler
    from crawler.core import Crawler
    from modes.base import CrawlMode
    from storage.database import CrawlDatabase

log = get_logger(__name__)


# v1.12 REFACTOR-services: نُقلت الـhelpers إلى services/ — نُعيد تصديرها هنا
# للتوافق العكسي (tests/test_core_behaviors.py وأيّ كود خارجي).
from services.deferred_service import deferred_list as _deferred_list
from services.deferred_service import deferred_summary as _deferred_summary
from services.integrations_summary import ga4_summary as _ga4_summary
from services.integrations_summary import gsc_summary as _gsc_summary
from services.progress_service import emit_phase


# ============================================================
# === Configuration ===
# ============================================================


# v1.12 REFACTOR-services: config + db facade نُقلا إلى services/ — re-export.
from services.config_service import (
    configure_target_site,
    load_config,
    setup_output_dir,
    slugify_label,
    validate_config,
)
from services.db_facade import AttrDict, DatabaseBackedCrawler


# ============================================================
# === Crawl Functions ===
# ============================================================


# v1.12 REFACTOR-services: crawl helpers نُقلت إلى services/crawl_service.py
from services.crawl_service import (
    find_phase2_deferred_csv as _find_phase2_deferred_csv,
    inject_phase2_seeds as _inject_phase2_seeds,
    run_crawl_async,
    run_crawl_sync,
)


# ============================================================
# === Analysis ===
# ============================================================


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

    if "duplicates" in enabled_analyzers:
        log.info("→ Detecting duplicates...")
        with span("analysis.duplicates", pages=len(pages)):
            results["duplicate_data"] = detect_duplicates(pages)
    else:
        results["duplicate_data"] = {}

    if "orphans" in enabled_analyzers:
        log.info("→ Finding orphan pages...")
        with span("analysis.orphans", pages=len(pages), links=len(links)):
            results["orphan_data"] = find_orphan_pages(pages, links)
    else:
        results["orphan_data"] = {}

    if "redirects" in enabled_analyzers:
        log.info("→ Analyzing redirects...")
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
        log.info("→ Detecting thin content...")
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
        log.info("→ Detecting broken links...")
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
        log.info("→ Analyzing images...")
        with span("analysis.images", images=len(images)):
            results["images_analysis"] = analyze_images(images)
    else:
        results["images_analysis"] = {}

    if "url_issues" in enabled_analyzers:
        log.info("→ Analyzing URL issues...")
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
        log.info("→ Analyzing canonicals...")
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
        log.info("→ Validating Schema.org...")
        with span("analysis.schema_validator", schema_entries=len(schema_entries)):
            results["schema_validation"] = validate_schemas(schema_entries)
        sv = results["schema_validation"]
        log.info(f"   Total schemas: {sv['total_schemas']}")
        log.info(f"   Rich Result eligible: {len(sv.get('rich_result_eligible', []))}")
        log.info(f"   Invalid (missing required): {len(sv.get('invalid_schemas', []))}")
    else:
        results["schema_validation"] = {}

    if "hreflang_validator" in enabled_analyzers:
        log.info("→ Validating Hreflang...")
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
        log.info("→ Comparing Sitemap vs Crawl...")
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
    if any(_get_value(p, "is_paginated") for p in pages):
        from analyzers.pagination_analyzer import analyze_pagination
        log.info("→ Analyzing pagination...")
        with span("analysis.pagination", pages=len(pages)):
            results["pagination_data"] = analyze_pagination(pages)
        pgd = results["pagination_data"]
        log.info(f"   Paginated: {pgd['total_paginated']} | issues: {pgd['issues_count']}")
    else:
        results["pagination_data"] = {}

    # === درجة الروابط الداخلية (PageRank داخلي) ===
    if links:
        from analyzers.link_score import compute_link_score
        log.info("→ Computing internal link score...")
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
        log.info("→ Spell check...")
        with span("analysis.spell_check", pages=len(pages)):
            results["spelling"] = run_spell_check(
                pages, max_pages=int(analysis_config.get("spell_check_max_pages", 0) or 0))
        st = results["spelling"].get("status", "")
        log.info(f"   Spelling: {st} (checked {results['spelling'].get('checked_pages', 0)})")
    else:
        results["spelling"] = {}

    # === التشابه التقريبي بين الصفحات (Near-Duplicate) ===
    if any(_get_value(p, "content_simhash") for p in pages):
        from analyzers.near_duplicate import detect_near_duplicates
        log.info("→ Detecting near-duplicate content...")
        with span("analysis.near_duplicate", pages=len(pages)):
            results["near_duplicate"] = detect_near_duplicates(pages)
        log.info(f"   Near-duplicate pairs: {results['near_duplicate'].get('pairs_count', 0)}")
    else:
        results["near_duplicate"] = {}

    # === Resource Inventory (الخطة #3) ===
    resources = getattr(crawler, "get_resources", lambda: [])()
    if resources:
        from analyzers.resources_analyzer import analyze_resources
        log.info("→ Analyzing resources...")
        with span("analysis.resources", resources=len(resources)):
            results["resources_data"] = analyze_resources(resources)
        rdz = results["resources_data"]
        log.info(f"   Resources: {rdz['total']} (unique {rdz['unique']}) | "
                 f"external {rdz['external_count']} | mixed {rdz['mixed_content_count']}")
    else:
        results["resources_data"] = {}

    # === Security headers (الخطة #8) ===
    if "security" in enabled_analyzers:
        log.info("→ Analyzing security headers...")
        sec_headers = crawler.get_headers()
        with span("analysis.security", pages=len(pages), headers=len(sec_headers)):
            results["security_data"] = analyze_security(pages, sec_headers)
        sd2 = results["security_data"]
        log.info(f"   Pages checked: {sd2['pages_checked']} | not HTTPS: {sd2['not_https_count']}")
    else:
        results["security_data"] = {}

    # === SEO Issues تجميع شامل ===
    if "seo_issues" in enabled_analyzers:
        log.info("→ Collecting SEO issues...")
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


# ============================================================
# === External Links Check ===
# ============================================================


async def run_external_links_check(crawler, db, config, mode: CrawlMode):
    """فحص الروابط الخارجية (async)."""
    from checkers.external_links_checker import ExternalLinksChecker

    checker_config = config.get("external_check", {})
    if not checker_config.get("enabled", True):
        log.info("→ External links check disabled in config")
        return {"external_results": []}

    if not mode.should_check_external_links():
        log.info("→ External links check skipped (not applicable for this mode)")
        return {"external_results": []}

    log.info("=" * 60)
    log.info("Phase 2.5: External Links Check")
    log.info("=" * 60)

    if db:
        external_urls = db.get_unchecked_external_links()
    else:
        all_links = crawler.get_links()
        external_urls = list(set(
            link["to_url"] for link in all_links
            if not link.get("is_internal")
            and not link.get("is_special_link")
            and link["to_url"].startswith(("http://", "https://"))
        ))

    if not external_urls:
        log.info("No external links to check")
        return {"external_results": []}

    # تسريع: عيّنة لكل host و/أو سقف إجمالي (تجنّب 1h+ على المواقع الضخمة).
    sample_per_host = bool(checker_config.get("sample_per_host", False))
    max_urls = int(checker_config.get("max_urls", 0) or 0)
    if sample_per_host and external_urls:
        from urllib.parse import urlparse as _urlparse
        by_host: dict[str, str] = {}
        for u in external_urls:
            try:
                h = _urlparse(u).netloc.lower()
            except (ValueError, TypeError):
                continue
            if h and h not in by_host:
                by_host[h] = u
        sampled = list(by_host.values())
        log.info(
            f"External sampling per host: {len(external_urls)} → {len(sampled)} "
            f"(فحص رابط واحد لكل host)"
        )
        external_urls = sampled
    if max_urls > 0 and len(external_urls) > max_urls:
        log.info(
            f"External cap: {len(external_urls)} → {max_urls} "
            f"(external_check.max_urls)"
        )
        external_urls = external_urls[:max_urls]

    log.info(f"Unique external links: {len(external_urls)}")
    emit_phase(
        crawler,
        "checking_external_links",
        external_links_total=len(external_urls),
        external_links_checked=0,
        external_links_broken=0,
        external_links_blocked=0,
    )

    checker = ExternalLinksChecker(
        timeout=checker_config.get("timeout", 10),
        concurrent=checker_config.get("concurrent", 20),
        user_agent=config.get("crawl", {}).get("user_agent", "SEOCrawlerBot/1.0"),
        retry_attempts=checker_config.get("retry_attempts", 2),
        verify_ssl=checker_config.get("verify_ssl", True),
    )

    progress_totals = {"checked": 0, "ok": 0, "broken": 0, "blocked": 0, "errors": 0}
    last_emit = 0.0

    def on_external_progress(delta: dict[str, Any]) -> None:
        nonlocal last_emit
        progress_totals["checked"] += int(delta.get("checked", 0))
        for key in ("ok", "broken", "blocked", "errors"):
            progress_totals[key] += int(delta.get(key, 0))

        now = time.time()
        total = int(delta.get("total", 0) or len(external_urls))
        is_last = progress_totals["checked"] >= total
        if is_last or now - last_emit >= 0.5:
            last_emit = now
            # v1.02: نسبة تقدّم محسوبة + label موحّد لشريط التقدّم في الواجهة
            pct = int(progress_totals["checked"] * 100 / max(total, 1))
            emit_phase(
                crawler,
                "checking_external_links",
                phase_label="checking_external_links",
                phase_percent=pct,
                phase_detail=f"{progress_totals['checked']}/{total} "
                             f"(✓ {progress_totals['ok']} · ✗ {progress_totals['broken']})",
                external_links_total=total,
                external_links_checked=progress_totals["checked"],
                external_links_ok=progress_totals["ok"],
                external_links_broken=progress_totals["broken"],
                external_links_blocked=progress_totals["blocked"],
                external_links_errors=progress_totals["errors"],
            )

    with span("phase.external_links", urls=len(external_urls)):
        results = await checker.check_urls(
            external_urls,
            progress=True,
            progress_callback=on_external_progress,
        )

    if db:
        with span("db.external_link_status.save_many", rows=len(results)):
            for result in results:
                db.save_external_link_status(
                    url=result["url"],
                    status_code=result["status_code"],
                    final_url=result.get("final_url", ""),
                    response_time_ms=result.get("response_time_ms", 0),
                    error=result.get("error"),
                )

    broken = [r for r in results if r.get("is_broken")]
    blocked = sum(1 for r in results if r.get("is_blocked"))
    ok = len(results) - len(broken) - blocked
    gauge("external_links.total", len(results))
    gauge("external_links.broken", len(broken))
    gauge("external_links.blocked", blocked)
    gauge("external_links.working", len(results) - len(broken))
    # نُظهر المحجوبة (401/403/429) صراحةً كي لا تختلط بالعاملة فعلاً
    log.info(f"  OK: {ok} | Blocked (401/403/429): {blocked} | Broken: {len(broken)}")
    if blocked:
        log.info(
            f"  ℹ️ {blocked} رابطاً خارجياً محجوب من السيرفر (بوت/معدّل طلبات) — "
            f"ليست أعطالاً حقيقية"
        )
    emit_phase(
        crawler,
        "checking_external_links",
        external_links_total=len(results),
        external_links_checked=len(results),
        external_links_broken=len(broken),
        external_links_working=len(results) - len(broken),
        external_links_blocked=sum(1 for r in results if r.get("is_blocked")),
        external_links_errors=sum(1 for r in results if r.get("error")),
    )

    return {"external_results": results, "broken_external_links": broken}


async def run_resource_status_check(crawler, config, mode: CrawlMode) -> dict[str, Any]:
    """فحص حالة HTTP لموارد الصفحة (CSS/JS/صور/خطوط…) — اختياري ومطفأ افتراضياً.

    يعيد استخدام فاحص الروابط الخارجية على روابط الموارد الفريدة، ويُرجع صفوفاً
    جاهزة لـ resource_status.csv. مكلف على المواقع الكبيرة، لذلك يُفعَّل صراحةً
    عبر extraction.check_resource_status.
    """
    if not config.get("extraction", {}).get("check_resource_status", False):
        return {"resource_status": []}

    resources = getattr(crawler, "get_resources", lambda: [])()
    if not resources:
        return {"resource_status": []}

    urls = sorted({
        r.get("url") for r in resources
        if r.get("url", "").startswith(("http://", "https://"))
    })
    if not urls:
        return {"resource_status": []}

    from checkers.external_links_checker import ExternalLinksChecker

    checker_config = config.get("external_check", {})
    log.info("=" * 60)
    log.info("Phase 2.6: Resource Status Check")
    log.info("=" * 60)
    log.info(f"Unique resources: {len(urls)}")

    checker = ExternalLinksChecker(
        timeout=checker_config.get("timeout", 10),
        concurrent=checker_config.get("concurrent", 20),
        user_agent=config.get("crawl", {}).get("user_agent", "SEOCrawlerBot/1.0"),
        retry_attempts=checker_config.get("retry_attempts", 2),
        verify_ssl=checker_config.get("verify_ssl", True),
    )
    with span("phase.resource_status", urls=len(urls)):
        results = await checker.check_urls(urls, progress=True)

    # ربط كل نتيجة بنوع المورد (للتقرير)
    type_by_url: dict[str, str] = {}
    for r in resources:
        type_by_url.setdefault(r.get("url", ""), r.get("resource_type", ""))
    for row in results:
        row["resource_type"] = type_by_url.get(row.get("url", ""), "")

    broken = [r for r in results if r.get("is_broken")]
    gauge("resource_status.total", len(results))
    gauge("resource_status.broken", len(broken))
    log.info(f"  Broken resources: {len(broken)} | OK: {len(results) - len(broken)}")
    return {"resource_status": results, "broken_resources_status": broken}


# v1.12 REFACTOR-services: AI advisor نُقل إلى services/ai_service.py
from services.ai_service import run_ai_analysis


# ============================================================
# === Integrations ===
# ============================================================


def run_integrations(crawler, config, mode: CrawlMode, cache=None):
    from integrations.awt_importer import AWTImporter
    from integrations.gsc_api import GSCClient
    from integrations.pagespeed_api import PageSpeedClient

    if not mode.should_run_integrations():
        log.info("→ Integrations skipped (not applicable for this mode)")
        return {}

    log.info("=" * 60)
    log.info("Phase 3: Integrations")
    log.info("=" * 60)

    integrations_config = config.get("integrations", {})
    results = {}

    gsc_config = integrations_config.get("gsc", {})
    if gsc_config.get("enabled"):
        log.info("→ Google Search Console...")
        with span("integration.gsc"):
            client = GSCClient(
                credentials_path=gsc_config["credentials_file"],
                site_url=gsc_config["site_url"],
                months_back=gsc_config.get("months_back", 16),
            )
            if client.authenticate():
                results["gsc_pages"] = client.get_top_pages()
                results["gsc_queries"] = client.get_top_queries()
                # بُعد (page, query) لتحليل تكلّس الكلمات (IMP-1) — بلا نداء API إضافي
                # خارج حصّة GSC الاعتيادية.
                try:
                    results["gsc_page_queries"] = client.get_pages_with_queries()
                except Exception:  # noqa: BLE001
                    log.warning("  GSC page+query fetch skipped", exc_info=True)
                # حالة الفهرسة الحقيقية لكل رابط (IMP-2) — اختياري، يحترم الحصّة عبر سقف
                if gsc_config.get("url_inspection"):
                    inspect_max = int(gsc_config.get("inspect_max_urls", 50))
                    insp_urls = [
                        (p.url if hasattr(p, "url") else p.get("url"))
                        for p in crawler.get_pages()
                    ]
                    insp_urls = [u for u in insp_urls if u][:inspect_max]
                    log.info(f"  → URL Inspection على {len(insp_urls)} رابط (سقف {inspect_max})")
                    results["gsc_index_status"] = client.inspect_urls(
                        insp_urls, max_urls=inspect_max)
    else:
        log.info("→ GSC disabled")

    ps_config = integrations_config.get("pagespeed", {})
    if ps_config.get("enabled"):
        api_key = ps_config.get("api_key") or os.getenv("PAGESPEED_API_KEY", "")
        if api_key:
            log.info("→ PageSpeed Insights (with cache)...")
            with span("integration.pagespeed"):
                raw_dir = None
                if ps_config.get("save_raw_json"):
                    out_dir = config.get("output", {}).get("output_dir", "./output")
                    raw_dir = str(Path(out_dir) / "pagespeed_raw")

                # v1.02: تحديث تقدّم الواجهة بكل طلب — تظهر «الحالة: جلب من PageSpeed»
                # و«التفاصيل: <الرابط الحالي>» بدل أن يبدو الجوب «معلّقاً» لمدّة طويلة.
                def _ps_progress(idx: int, total: int, page_url: str, strategy: str) -> None:
                    pct = int(idx * 100 / max(total, 1))
                    emit_phase(
                        crawler, "pagespeed",
                        phase_label="pagespeed",
                        phase_detail=f"[{idx}/{total}] {strategy}: {page_url}",
                        phase_percent=pct,
                    )

                client = PageSpeedClient(
                    api_key=api_key,
                    delay_seconds=ps_config.get("delay_seconds", 1),
                    timeout=int(ps_config.get("timeout", 90)),
                    cache=cache,
                    cache_ttl_days=ps_config.get("cache_ttl_days", 7),
                    raw_dir=raw_dir,
                    on_progress=_ps_progress,
                )
                pages = crawler.get_pages()
                urls_to_test = [
                    p.url if hasattr(p, "url") else p.get("url")
                    for p in pages
                    if (p.status_code if hasattr(p, "status_code") else p.get("status_code", 0)) == 200
                    and (p.is_indexable if hasattr(p, "is_indexable") else p.get("is_indexable", False))
                ]

                max_urls = ps_config.get("max_urls", 0)
                if max_urls > 0:
                    urls_to_test = urls_to_test[:max_urls]

                strategies = ps_config.get("strategies", ["mobile", "desktop"])
                gauge("pagespeed.urls_to_test", len(urls_to_test))
                gauge("pagespeed.strategies", len(strategies))
                log.info(f"  Testing {len(urls_to_test)} URLs × {len(strategies)}")
                results["pagespeed"] = client.audit_bulk(urls_to_test, strategies)
                cache_stats = client.get_cache_stats()
                log.info(
                    f"  Cache: {cache_stats['hits']} hits / "
                    f"{cache_stats['misses']} misses "
                    f"({cache_stats['hit_rate']}% hit rate)"
                )
                # اتجاه Core Web Vitals عبر الزمن على مستوى الأصل (IMP-9) — اختياري
                if ps_config.get("crux_history"):
                    from integrations.crux_history import CrUXHistoryClient
                    origin = config.get("site", {}).get("start_url", "")
                    log.info(f"  → CrUX History للأصل {origin}")
                    rows = CrUXHistoryClient(api_key).query(origin=origin)
                    if rows:
                        results["crux_history"] = rows
        else:
            log.warning("  PageSpeed API key missing")
    else:
        log.info("→ PageSpeed disabled")

    awt_config = integrations_config.get("awt", {})
    if awt_config.get("enabled"):
        log.info("→ AWT (CSV imports)...")
        with span("integration.awt"):
            importer = AWTImporter(awt_config.get("csv_folder", "./external_data/awt"))
            results["awt_backlinks"] = importer.load_backlinks()
            results["awt_keywords"] = importer.load_keywords()
    else:
        log.info("→ AWT disabled")

    # v1.04: تكاملات الروابط الخلفيّة الحيّة (Ahrefs / Majestic) — اختياريّة ومدفوعة.
    # المفتاح يُمرَّر من البيئة (مثل PageSpeed) كي لا يُكتب على القرص.
    backlinks_config = integrations_config.get("backlinks", {})
    if backlinks_config.get("enabled"):
        provider = (backlinks_config.get("provider") or "").lower()
        # المفتاح: من البيئة أوّلاً (لا يُكتب على القرص) ثم من الإعداد (للاختبار)
        key = os.environ.get("BACKLINKS_API_KEY") or backlinks_config.get("api_key", "")
        site_url = config.get("site", {}).get("start_url", "")
        if not key:
            log.warning(f"  Backlinks ({provider}) skipped — missing API key")
        elif not provider:
            log.warning("  Backlinks skipped — provider not set (ahrefs/majestic)")
        else:
            log.info(f"→ Backlinks ({provider})...")
            with span(f"integration.backlinks.{provider}"):
                from integrations.backlinks_api import BacklinksProvider
                client = BacklinksProvider.create(
                    provider, key,
                    timeout=int(backlinks_config.get("timeout", 30)),
                )
                if client is None:
                    log.warning(f"  Unknown backlinks provider: {provider}")
                else:
                    res = client.fetch(site_url)
                    if res.get("error"):
                        log.warning(f"  Backlinks {provider} failed: {res['error']}")
                    else:
                        log.info(
                            f"  {provider}: {(res.get('summary') or {}).get('referring_domains', 0)} "
                            f"referring domains"
                        )
                    results["backlinks"] = res
    else:
        log.info("→ Backlinks (live API) disabled")

    # === Lighthouse / PageSpeed JSON import (الخطة #6) — اختياري بلا مفاتيح ===
    lh_config = integrations_config.get("lighthouse", {})
    if lh_config.get("enabled"):
        from integrations.lighthouse_importer import LighthouseImporter

        log.info("→ Lighthouse import...")
        with span("integration.lighthouse"):
            importer = LighthouseImporter(
                lh_config.get("folder", "./external_data/lighthouse")
            )
            results["lighthouse"] = importer.load()
    else:
        log.info("→ Lighthouse import disabled")

    # === GA4 (سلوك المستخدم) — اختياري بلا مفاتيح في الكود ===
    ga4_config = integrations_config.get("ga4", {})
    if ga4_config.get("enabled"):
        from integrations.ga4_api import GA4Client

        log.info("→ Google Analytics 4...")
        with span("integration.ga4"):
            property_id = ga4_config.get("property_id") or os.getenv("GA4_PROPERTY_ID", "")
            creds = ga4_config.get("credentials_file") or os.getenv("GA4_CREDENTIALS_FILE", "")
            client = GA4Client(
                property_id=property_id,
                credentials_file=creds,
                date_range_days=ga4_config.get("date_range_days", 90),
            )
            if client.authenticate():
                results["ga4_landing_pages"] = client.get_landing_pages()
                results["ga4_channels"] = client.get_channels()
    else:
        log.info("→ GA4 disabled")

    return results


# ============================================================
# === Export ===
# ============================================================


def run_export(crawler, analysis, integrations, external_check, output_dir, config, mode):
    from exporters.csv_exporter import CSVExporter
    from exporters.json_exporter import JSONExporter

    log.info("=" * 60)
    log.info("Phase 4: Export")
    log.info("=" * 60)

    formats = config["output"].get("formats", ["csv", "excel", "json"])
    encoding = config["output"].get("encoding", "utf-8-sig")
    exported_files = {}

    # طابع زمني + اسم نطاق لتسمية الملفات الرئيسية (التقرير/Excel/JSON)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    site_slug = slugify_label(config.get("site", {}).get("domain", "") or mode.name)
    excel_name = f"audit_{site_slug}_{stamp}.xlsx"
    json_name = f"audit_{site_slug}_{stamp}.json"
    report_stem = f"report_{site_slug}_{stamp}"

    pages = crawler.get_pages()
    links = crawler.get_links()
    images = crawler.get_images()
    headings = crawler.get_headings()
    schema = crawler.get_schema()
    redirects = crawler.get_redirects()
    headers = crawler.get_headers()
    excluded = getattr(crawler, "get_excluded", lambda: [])()
    excluded_counts = getattr(crawler, "excluded_counts", {}) or {}

    gauge("export.input.pages", len(pages))
    gauge("export.input.links", len(links))
    gauge("export.input.images", len(images))
    gauge("export.input.headings", len(headings))
    gauge("export.input.schema", len(schema))

    if "csv" in formats:
        log.info("→ CSV...")
        with span("export.csv", output_dir=str(output_dir / "csv")):
            csv_exporter = CSVExporter(str(output_dir / "csv"), encoding=encoding)
            csv_files = csv_exporter.export_all(
                pages=pages, links=links, images=images, headings=headings,
                schema=schema, redirects=redirects, headers=headers,
                seo_issues=analysis.get("seo_issues", {}),
                duplicate_data=analysis.get("duplicate_data", {}),
                orphan_data=analysis.get("orphan_data", {}),
                thin_content_data=analysis.get("thin_content_data", {}),
                broken_data=analysis.get("broken_data", {}),
                images_analysis=analysis.get("images_analysis", {}),
                url_issues=analysis.get("url_issues", {}),
                canonical_data=analysis.get("canonical_data", {}),
            )
            if excluded:
                csv_files["excluded_urls"] = csv_exporter._export("excluded_urls.csv", excluded)

            # v1.08: CSV للروابط المؤجَّلة — يتيح للمستخدم استعراضها/تصفيتها قبل Phase 2
            deferred_rows = _deferred_list(crawler)
            if deferred_rows:
                csv_files["deferred_urls"] = csv_exporter._export(
                    "deferred_urls.csv", deferred_rows,
                )

            # تقارير redirects التفصيلية (الخطة #1)
            rd = analysis.get("redirect_data", {}) or {}
            if rd.get("redirect_chains"):
                csv_files["redirect_chains"] = csv_exporter._export(
                    "redirect_chains.csv",
                    [{"original_url": c.get("original_url"), "final_url": c.get("final_url"),
                      "chain_length": c.get("chain_length"),
                      "hops": " → ".join(h.get("from", "") for h in c.get("hops", []))}
                     for c in rd["redirect_chains"]],
                )
            if rd.get("redirect_loops"):
                csv_files["redirect_loops"] = csv_exporter._export(
                    "redirect_loops.csv",
                    [{"original_url": c.get("original_url"), "final_url": c.get("final_url"),
                      "chain_length": c.get("chain_length")} for c in rd["redirect_loops"]],
                )
            redirect_issues = []
            for r in rd.get("temporary_redirects", []):
                redirect_issues.append({"issue": "temporary_302_307", **r})
            for r in rd.get("internal_redirects", []):
                redirect_issues.append({"issue": "internal_redirect", **r})
            for c in rd.get("protocol_upgrades", []):
                redirect_issues.append({"issue": "protocol_upgrade",
                                        "from": c.get("original_url"), "to": c.get("final_url")})
            if redirect_issues:
                csv_files["redirect_issues"] = csv_exporter._export(
                    "redirect_issues.csv", redirect_issues)

            # مشاكل الأمان (الخطة #8)
            sec = analysis.get("security_data", {}) or {}
            if sec.get("issues"):
                csv_files["security_issues"] = csv_exporter._export(
                    "security_issues.csv", sec["issues"])

            # الاستخراج المخصّص (الخطة #5)
            custom_rows = getattr(crawler, "get_custom_extraction", lambda: [])()
            if custom_rows:
                csv_files["custom_extraction"] = csv_exporter._export(
                    "custom_extraction.csv", custom_rows)

            # استيراد Lighthouse (الخطة #6)
            lh_rows = (integrations or {}).get("lighthouse") or []
            if lh_rows:
                csv_files["lighthouse_import"] = csv_exporter._export(
                    "lighthouse_import.csv", lh_rows)

            # جرد الموارد (الخطة #3)
            resource_rows = getattr(crawler, "get_resources", lambda: [])()
            if resource_rows:
                csv_files["resources"] = csv_exporter._export("resources.csv", resource_rows)
                rdata = analysis.get("resources_data", {}) or {}
                issues = (rdata.get("mixed_content", []) or []) + (rdata.get("broken_resources", []) or [])
                if issues:
                    csv_files["resource_issues"] = csv_exporter._export(
                        "resource_issues.csv", issues)
            # حالة HTTP للموارد (عند تفعيل extraction.check_resource_status)
            resource_status = analysis.get("resource_status", []) or []
            if resource_status:
                csv_files["resource_status"] = csv_exporter._export(
                    "resource_status.csv", resource_status)

            # ترقيم الصفحات (rel=next/prev)
            pgd = analysis.get("pagination_data", {}) or {}
            if pgd.get("paginated_pages"):
                csv_files["pagination"] = csv_exporter._export(
                    "pagination.csv", pgd["paginated_pages"])
            if pgd.get("issues"):
                csv_files["pagination_issues"] = csv_exporter._export(
                    "pagination_issues.csv", pgd["issues"])

            # مشاكل hreflang (عدم التبادل/404/noindex…)
            hv = analysis.get("hreflang_validation", {}) or {}
            hreflang_rows = _flatten_hreflang_issues(hv)
            if hreflang_rows:
                csv_files["hreflang_issues"] = csv_exporter._export(
                    "hreflang_issues.csv", hreflang_rows)

            # diff تصيير JavaScript (الخطة #4)
            js_diff = getattr(crawler, "get_js_diff", lambda: [])()
            if js_diff:
                csv_files["js_diff"] = csv_exporter._export("js_diff.csv", js_diff)

            # فحص الوصولية (axe-core) — ملخّص لكل صفحة + قائمة المخالفات
            a11y = getattr(crawler, "get_accessibility", lambda: [])()
            if a11y:
                csv_files["accessibility"] = csv_exporter._export(
                    "accessibility.csv", _flatten_accessibility(a11y))
                a11y_issues = _flatten_accessibility_issues(a11y)
                if a11y_issues:
                    csv_files["accessibility_issues"] = csv_exporter._export(
                        "accessibility_issues.csv", a11y_issues)

            # === التقرير الموحّد: GSC / GA4 / الأولويات ===
            if (integrations or {}).get("gsc_pages"):
                csv_files["gsc_pages"] = csv_exporter._export(
                    "gsc_pages.csv", integrations["gsc_pages"])
            if (integrations or {}).get("gsc_queries"):
                csv_files["gsc_queries"] = csv_exporter._export(
                    "gsc_queries.csv", integrations["gsc_queries"])
            if (integrations or {}).get("ga4_landing_pages"):
                csv_files["ga4_landing_pages"] = csv_exporter._export(
                    "ga4_landing_pages.csv", integrations["ga4_landing_pages"])
            if (integrations or {}).get("ga4_channels"):
                csv_files["ga4_channels"] = csv_exporter._export(
                    "ga4_channels.csv", integrations["ga4_channels"])
            if (integrations or {}).get("gsc_index_status"):
                csv_files["gsc_index_status"] = csv_exporter._export(
                    "gsc_index_status.csv", integrations["gsc_index_status"])
            opps = (analysis.get("opportunities", {}) or {}).get("opportunities")
            if opps:
                csv_files["priority_opportunities"] = csv_exporter._export(
                    "priority_opportunities.csv", opps)
            # محرّك الأولويات v2: درجة لكل صفحة + لوحة العمل
            prio = analysis.get("priority", {}) or {}
            prio_pages = prio.get("pages") or []
            if prio_pages:
                csv_files["page_priority"] = csv_exporter._export(
                    "page_priority.csv", prio_pages)
                from reporting.priority_engine import build_action_board
                board = build_action_board(prio)
                if board:
                    csv_files["action_board"] = csv_exporter._export(
                        "action_board.csv", board)

            # درجة الروابط الداخلية (PageRank داخلي) لكل صفحة
            ls = (analysis.get("link_score", {}) or {}).get("pages") or []
            if ls:
                csv_files["link_score"] = csv_exporter._export("link_score.csv", ls)

            # أزواج الصفحات المتشابهة تقريبياً (Near-Duplicate)
            nd_pairs = (analysis.get("near_duplicate", {}) or {}).get("pairs") or []
            if nd_pairs:
                csv_files["near_duplicates"] = csv_exporter._export(
                    "near_duplicates.csv", nd_pairs)

            # تحليلات GSC (IMP-1): تكلّس الكلمات + فُرَص الروابط الداخلية
            cann_rows = _flatten_cannibalization(analysis.get("cannibalization", {}))
            if cann_rows:
                csv_files["keyword_cannibalization"] = csv_exporter._export(
                    "keyword_cannibalization.csv", cann_rows)
            ilo = (analysis.get("internal_link_opportunities", {}) or {}).get("opportunities") or []
            if ilo:
                csv_files["internal_link_opportunities"] = csv_exporter._export(
                    "internal_link_opportunities.csv", ilo)

            # PageSpeed Insights (عند تفعيل التكامل) — نُسطّح المقاييس الأساسية
            ps_data = (integrations or {}).get("pagespeed") or []
            ps_rows = _flatten_pagespeed(ps_data)
            if ps_rows:
                csv_files["pagespeed"] = csv_exporter._export("pagespeed.csv", ps_rows)
            ps_opps = _flatten_pagespeed_opportunities(ps_data)
            if ps_opps:
                csv_files["pagespeed_opportunities"] = csv_exporter._export(
                    "pagespeed_opportunities.csv", ps_opps)
            # الجداول المنظّمة العميقة (audits / network / treemap / failed) — IMP-17أ
            _export_pagespeed_tables(ps_data, csv_exporter, csv_files)
            # اتجاه Core Web Vitals عبر الزمن (IMP-9)
            if (integrations or {}).get("crux_history"):
                csv_files["crux_history"] = csv_exporter._export(
                    "crux_history.csv", integrations["crux_history"])

            # توصيات الذكاء الاصطناعي (عند تفعيل التكامل)
            ai = analysis.get("ai_analysis", {}) or {}
            if ai.get("recommendations"):
                csv_files["ai_recommendations"] = csv_exporter._export(
                    "ai_recommendations.csv", ai["recommendations"])
        exported_files.update({f"csv_{k}": v for k, v in csv_files.items()})

    if "excel" in formats:
        log.info("→ Excel...")
        with span("export.excel", output_dir=str(output_dir)):
            # تثبيت تلقائي لـ openpyxl عند الحاجة (IMP-16)
            from utils.auto_install import ensure_package
            ensure_package("openpyxl")
            try:
                from exporters.excel_exporter import ExcelExporter
            except ModuleNotFoundError as e:
                if e.name == "openpyxl":
                    log.warning("Excel export skipped: openpyxl is not installed")
                    increment("export.excel.skipped_missing_openpyxl")
                    excel_file = ""
                else:
                    raise
            else:
                excel_exporter = ExcelExporter(str(output_dir), excel_name)
                excel_file = excel_exporter.export(
                    pages=pages, links=links, images=images, headings=headings,
                    schema=schema, redirects=redirects, headers=headers,
                    seo_issues=analysis.get("seo_issues", {}),
                    duplicate_data=analysis.get("duplicate_data", {}),
                    orphan_data=analysis.get("orphan_data", {}),
                    thin_content_data=analysis.get("thin_content_data", {}),
                    broken_data=analysis.get("broken_data", {}),
                    images_analysis=analysis.get("images_analysis", {}),
                    crawl_stats=crawler.get_stats(),
                    site_url=config["site"]["start_url"],
                )
        if excel_file:
            exported_files["excel"] = excel_file

    if "json" in formats:
        log.info("→ JSON...")
        # المصفوفات الخام (روابط/صور/عناوين) قد تبلغ مئات آلاف الصفوف وتُضخّم JSON
        # لغيغابايتات يتعذّر فتحها/إعادة بناء التقرير منها. نستثنيها افتراضياً (متوفّرة
        # كاملةً في CSV/Excel/XML)، وتُضمَّن فقط عند output.json_full=true.
        json_full = bool(config["output"].get("json_full", False))
        with span("export.json", output_dir=str(output_dir)):
            json_exporter = JSONExporter(str(output_dir), json_name)
            raw_arrays: dict[str, Any] = {}
            if json_full:
                raw_arrays = {"links": links, "images": images, "headings": headings}
            else:
                raw_arrays = {"raw_arrays_omitted": {
                    "links": len(links), "images": len(images), "headings": len(headings),
                    "note": "set output.json_full=true to embed; full data is in CSV/Excel/XML",
                }}
            json_file = json_exporter.export(
                pages=pages,
                schema=schema, redirects=redirects,
                mode=mode.name,
                **raw_arrays,
                seo_issues=analysis.get("seo_issues", {}),
                duplicate_data=analysis.get("duplicate_data", {}),
                orphan_data=analysis.get("orphan_data", {}),
                thin_content_data=analysis.get("thin_content_data", {}),
                broken_data=analysis.get("broken_data", {}),
                images_analysis=analysis.get("images_analysis", {}),
                url_issues=analysis.get("url_issues", {}),
                canonical_data=analysis.get("canonical_data", {}),
                schema_validation=analysis.get("schema_validation", {}),
                hreflang_validation=analysis.get("hreflang_validation", {}),
                sitemap_diff=analysis.get("sitemap_diff", {}),
                redirect_data=analysis.get("redirect_data", {}),
                pagination_data=analysis.get("pagination_data", {}),
                external_check=external_check,
                integrations=_integrations_for_json(integrations),
                excluded_urls=excluded,
                excluded_summary=excluded_counts,
                # v1.08: روابط مؤجَّلة (لم تُفحَص في Phase 1) + ملخّصها
                deferred_urls=_deferred_list(crawler),
                deferred_summary=_deferred_summary(crawler),
                security_data=analysis.get("security_data", {}),
                resources_data=analysis.get("resources_data", {}),
                resource_status=analysis.get("resource_status", []),
                custom_extraction=getattr(crawler, "get_custom_extraction", lambda: [])(),
                js_diff=getattr(crawler, "get_js_diff", lambda: [])(),
                accessibility=getattr(crawler, "get_accessibility", lambda: [])(),
                opportunities=analysis.get("opportunities", {}),
                priority=analysis.get("priority", {}),
                cannibalization=analysis.get("cannibalization", {}),
                internal_link_opportunities=analysis.get("internal_link_opportunities", {}),
                ai_analysis=analysis.get("ai_analysis", {}),
                gsc_summary=_gsc_summary(integrations),
                ga4_summary=_ga4_summary(integrations),
                site_config=config["site"],
            )
        exported_files["json"] = json_file

    if "xml" in formats:
        log.info("→ XML...")
        # سقف لصفوف XML: على المواقع الكبيرة كان links.xml يتجاوز الغيغابايت.
        # نقصّ كل مجموعة عند الحد (البيانات الكاملة في CSV/Excel). 0 = بلا حد.
        xml_max = int(config["output"].get("xml_max_rows", 50000) or 0)

        def _cap(rows: list[Any], name: str) -> list[Any]:
            if xml_max and len(rows) > xml_max:
                log.warning(
                    f"   XML {name}: {len(rows)} صف يتجاوز الحد {xml_max} — يُقتصَر في XML "
                    f"(البيانات الكاملة في CSV/Excel)"
                )
                return rows[:xml_max]
            return rows

        with span("export.xml", output_dir=str(output_dir / "xml")):
            from exporters.xml_exporter import XMLExporter

            xml_exporter = XMLExporter(str(output_dir / "xml"))
            xml_files = xml_exporter.export_all(
                pages=_cap(pages, "pages"),
                links=_cap(links, "links"),
                images=_cap(images, "images"),
                schema=_cap(schema, "schema"),
                seo_issues=analysis.get("seo_issues", {}),
            )
        exported_files.update({f"xml_{k}": v for k, v in xml_files.items()})

    # === HTML / PDF report ===
    # عند الإيقاف اليدوي نتخطّى بناء HTML/PDF (البطيء) كي تظهر تنزيلات النتائج
    # الجزئية فوراً؛ يمكن للمستخدم إعادة بناء التقرير لاحقاً من الواجهة.
    stopped_early = getattr(crawler, "_external_stop", False)
    if ("html" in formats or "pdf" in formats) and not stopped_early:
        log.info("→ HTML/PDF report...")
        from exporters.report_builder import build_report

        report_opts = config.get("report", {}) or {}
        make_pdf = "pdf" in formats

        def on_report_progress(status: str, **payload: Any) -> None:
            emit_phase(crawler, status, **payload)

        # نبني التقرير من البيانات في الذاكرة مباشرةً، لا بإعادة تحميل ملف JSON
        # الذي قد يبلغ غيغابايتات على المواقع الكبيرة (كان سبب تعليق «إعداد التقارير»).
        # التقرير يحتاج الصفحات + التحليلات + الملخّصات فقط — لا المصفوفات الخام
        # (روابط/صور/عناوين) المتوفّرة في CSV/Excel/XML.
        report_audit = {
            "site_config": config["site"],
            "pages": pages,
            "seo_issues": analysis.get("seo_issues", {}),
            "opportunities": analysis.get("opportunities", {}),
            "redirect_data": analysis.get("redirect_data", {}),
            "pagination_data": analysis.get("pagination_data", {}),
            "resources_data": analysis.get("resources_data", {}),
            "resource_status": analysis.get("resource_status", []),
            "hreflang_validation": analysis.get("hreflang_validation", {}),
            "schema_validation": analysis.get("schema_validation", {}),
            "ai_analysis": analysis.get("ai_analysis", {}),
            "gsc_summary": _gsc_summary(integrations),
            "ga4_summary": _ga4_summary(integrations),
        }
        with span("export.report", output_dir=str(output_dir)):
            report = build_report(
                report_audit,
                str(output_dir),
                options=report_opts,
                make_pdf=make_pdf,
                name_stem=report_stem,
                progress_callback=on_report_progress,
            )
        # نسجّل كل صيغ التقرير الناتجة (تشمل client/expert في وضع both)
        for key in ("html", "pdf", "html_client", "pdf_client", "html_expert", "pdf_expert"):
            if report.get(key):
                exported_files[key] = report[key]

    # === توليد Sitemap من الصفحات القابلة للفهرسة (IMP-5) — اختياري ===
    if config["output"].get("generate_sitemap"):
        try:
            from exporters.sitemap_generator import SitemapGenerator
            base = config.get("site", {}).get("start_url", "")
            sm = SitemapGenerator(str(output_dir), base_url=base).generate(pages)
            for i, fpath in enumerate(sm.get("files", [])):
                exported_files["sitemap" if i == 0 else f"sitemap_{i}"] = fpath
        except Exception:  # noqa: BLE001
            log.exception("Sitemap generation failed")

    gauge("export.files", len(exported_files))
    return exported_files


def build_compare_summary(site_results: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for result in site_results:
        if "summary" in result:
            rows.append(result["summary"])
            continue
        pages = result.get("pages", [])
        links = result.get("links", [])
        images = result.get("images", [])
        schema = result.get("schema", [])
        indexable = sum(1 for p in pages if _get_value(p, "is_indexable", False))
        status_4xx = sum(1 for p in pages if 400 <= int(_get_value(p, "status_code", 0) or 0) < 500)
        avg_words = 0
        if pages:
            avg_words = round(sum(int(_get_value(p, "word_count", 0) or 0) for p in pages) / len(pages), 2)
        rows.append({
            "label": result["label"],
            "url": result["url"],
            "pages": len(pages),
            "indexable_pages": indexable,
            "status_4xx": status_4xx,
            "links": len(links),
            "images": len(images),
            "schema_entries": len(schema),
            "avg_word_count": avg_words,
        })
    return {"sites": rows}


def summarize_crawler_result(label: str, url: str, crawler) -> dict[str, Any]:
    pages = crawler.get_pages()
    links = crawler.get_links()
    images = crawler.get_images()
    schema = crawler.get_schema()
    indexable = sum(1 for p in pages if _get_value(p, "is_indexable", False))
    status_4xx = sum(1 for p in pages if 400 <= int(_get_value(p, "status_code", 0) or 0) < 500)
    avg_words = 0
    if pages:
        avg_words = round(sum(int(_get_value(p, "word_count", 0) or 0) for p in pages) / len(pages), 2)
    return {
        "label": label,
        "url": url,
        "pages": len(pages),
        "indexable_pages": indexable,
        "status_4xx": status_4xx,
        "links": len(links),
        "images": len(images),
        "schema_entries": len(schema),
        "avg_word_count": avg_words,
    }


# v1.12 REFACTOR-services: export helpers نُقلت إلى services/export_helpers.py
from services.export_helpers import (
    export_pagespeed_tables as _export_pagespeed_tables,
    flatten_accessibility as _flatten_accessibility,
    flatten_accessibility_issues as _flatten_accessibility_issues,
    flatten_cannibalization as _flatten_cannibalization,
    flatten_hreflang_issues as _flatten_hreflang_issues,
    flatten_pagespeed as _flatten_pagespeed,
    flatten_pagespeed_failed_audits as _flatten_pagespeed_failed_audits,
    flatten_pagespeed_opportunities as _flatten_pagespeed_opportunities,
    flatten_pagespeed_table as _flatten_pagespeed_table,
    get_value as _get_value,
    integrations_for_json as _integrations_for_json,
)


class _MinimalCrawler:
    """زاحف وهمي صغير لتشغيل تكاملات تعتمد على «صفحات» (مثل PageSpeed) في وضع
    «جلب التكامل فقط» — يحوي رابط البداية فقط."""

    def __init__(self, start_url: str):
        self._pages = [{"url": start_url, "status_code": 200, "is_indexable": True}]

    def get_pages(self): return list(self._pages)
    def get_links(self): return []
    def get_images(self): return []
    def get_headings(self): return []
    def get_schema(self): return []
    def get_headers(self): return []
    def get_redirects(self): return []
    def get_resources(self): return []
    def get_stats(self) -> SimpleNamespace:
        return SimpleNamespace(
            total_pages=len(self._pages),
            crawled=len(self._pages),
            failed=0,
            duration_seconds=0.0,
        )


async def _run_integrations_only(config, mode, output_dir, cache, db=None) -> None:
    """ينفّذ مرحلة التكاملات فقط (بلا زحف) ويصدّر بياناتها كـ CSV/JSON.

    إن وُجدت قاعدة بيانات لزحف سابق نستعملها (يفحص PageSpeed عيّنة من صفحات
    الموقع الحقيقية لا الرئيسية فقط)؛ وإلا نُكوّن زاحفاً وهمياً بالصفحة الرئيسية.
    """
    from exporters.csv_exporter import CSVExporter
    from exporters.json_exporter import JSONExporter

    start_url = config.get("site", {}).get("start_url", "")
    log.info("=" * 60)
    log.info("Integrations-only mode (لا يوجد زحف)")
    log.info("=" * 60)

    crawler: Any
    if db is not None:
        crawler = DatabaseBackedCrawler(db)
        page_count = len(crawler.get_pages())
        if page_count == 0:
            log.info("لا توجد صفحات في DB سابقة — يُستعمل الرابط الرئيسي فقط لـPageSpeed")
            crawler = _MinimalCrawler(start_url)
        else:
            log.info(f"عُثر على {page_count} صفحة من زحف سابق — PageSpeed سيستعملها (مع سقف max_urls)")
    else:
        crawler = _MinimalCrawler(start_url)
    emit_phase(crawler, "integrations", phase_label="integrations")
    integrations = run_integrations(crawler, config, mode, cache=cache)

    emit_phase(crawler, "exporting", phase_label="exporting")
    csv_dir = output_dir / "csv"
    csv_exp = CSVExporter(str(csv_dir),
                          encoding=config["output"].get("encoding", "utf-8-sig"))
    exported: dict[str, str] = {}
    for key in ("gsc_pages", "gsc_queries", "ga4_landing_pages", "ga4_channels",
                "gsc_index_status", "crux_history"):
        rows = (integrations or {}).get(key) or []
        if rows:
            exported[key] = csv_exp._export(f"{key}.csv", rows)
            log.info(f"  ✓ {key}.csv ({len(rows)} صفوف)")
    ps_data = (integrations or {}).get("pagespeed") or []
    ps_rows = _flatten_pagespeed(ps_data)
    if ps_rows:
        exported["pagespeed"] = csv_exp._export("pagespeed.csv", ps_rows)
        log.info(f"  ✓ pagespeed.csv ({len(ps_rows)} صفوف)")
    ps_opps = _flatten_pagespeed_opportunities(ps_data)
    if ps_opps:
        exported["pagespeed_opportunities"] = csv_exp._export(
            "pagespeed_opportunities.csv", ps_opps)
        log.info(f"  ✓ pagespeed_opportunities.csv ({len(ps_opps)} صفوف)")
    # الجداول المنظّمة العميقة (audits / network / treemap / failed) — IMP-17أ
    _export_pagespeed_tables(ps_data, csv_exp, exported, log_each=True)

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    site_slug = slugify_label(config.get("site", {}).get("domain", "") or "site")
    json_file = JSONExporter(str(output_dir),
                             f"integrations_{site_slug}_{stamp}.json").export(
        mode="integrations_only",
        site_config=config["site"],
        gsc_summary=_gsc_summary(integrations),
        ga4_summary=_ga4_summary(integrations),
        integrations=_integrations_for_json(integrations),
    )
    log.info(f"  ✓ {json_file}")

    metrics_file = write_metrics(output_dir)
    if metrics_file:
        log.info(f"  ✓ {metrics_file}")

    emit_phase(crawler, "complete")
    log.info("=" * 60)
    log.info("✅ انتهى جلب التكامل")
    log.info("=" * 60)


async def run_compare_workflow(args, config: dict[str, Any], mode: CrawlMode) -> None:
    from exporters.json_exporter import JSONExporter
    from storage.cache import APICache
    from storage.database import CrawlDatabase

    sites = config.get("sites_to_compare", [])
    if args.url:
        sites = [{"url": args.url, "label": urlparse(args.url).netloc, "is_primary": True}]
    if not sites:
        raise ValueError("compare mode needs at least one entry in sites_to_compare")

    state_dir = Path(config.get("state", {}).get("state_dir", "./state"))
    state_dir.mkdir(parents=True, exist_ok=True)
    cache = APICache(
        str(state_dir / "api_cache.db"),
        default_ttl_days=config.get("state", {}).get("cache_ttl_days", 7),
    )

    if args.clear_cache:
        log.info("Clearing cache...")
        cache.invalidate()
        log.info("✅ Cache cleared")
        cache.close()
        return

    output_dir = setup_output_dir(config, mode.name)
    site_results: list[dict[str, Any]] = []

    try:
        for index, site in enumerate(sites, start=1):
            site_url = site.get("url")
            if not site_url:
                log.warning("Skipping compare site without url: %s", site)
                continue

            # تصفير المقاييس لكل موقع كي لا تتراكم أرقام موقع على آخر
            reset_monitoring()

            label = site.get("label") or urlparse(site_url).netloc or f"site_{index}"
            site_config = mode.apply_defaults(dict(config))
            site_config["site"] = dict(site_config.get("site", {}))
            configure_target_site(site_config, site_url)

            db = None
            if site_config.get("state", {}).get("use_database", True):
                db_path = state_dir / f"crawl_compare_{slugify_label(label)}.db"
                if args.no_resume and db_path.exists():
                    db_path.unlink()
                db = CrawlDatabase(str(db_path))

            log.info("=" * 60)
            log.info("Compare site %s/%s: %s (%s)", index, len(sites), label, site_url)
            log.info("=" * 60)

            try:
                with span("compare.site", index=index, label=label, url=site_url):
                    increment("compare.sites")
                    if not args.analyze_only:
                        crawler = (
                            run_crawl_sync(site_config)
                            if args.sync
                            else await run_crawl_async(site_config, db=db)
                        )
                    else:
                        if not db:
                            raise ValueError("--analyze-only requires state.use_database=true")
                        crawler = DatabaseBackedCrawler(db)

                    analysis = run_analysis(crawler, site_config, mode)
                    integrations = (
                        run_integrations(crawler, site_config, mode, cache=cache)
                        if site.get("is_primary")
                        else {}
                    )
                    site_output_dir = output_dir / slugify_label(label)
                    exported = run_export(
                        crawler,
                        analysis,
                        integrations,
                        {"external_results": []},
                        site_output_dir,
                        site_config,
                        mode,
                    )
                    site_results.append({
                        "label": label,
                        "url": site_url,
                        "summary": summarize_crawler_result(label, site_url, crawler),
                        "analysis": analysis,
                        "exported": exported,
                    })
                    # مقاييس هذا الموقع وحده داخل مجلده (قبل تصفير الموقع التالي)
                    write_metrics(site_output_dir)
            finally:
                if db:
                    db.close()

        # المقاييس على المستوى الأعلى تخص مرحلة المقارنة فقط (كل موقع له ملفه)
        reset_monitoring()
        with span("compare.summary", sites=len(site_results)):
            summary = build_compare_summary(site_results)
            JSONExporter(str(output_dir), "comparison_summary.json").export(
                mode=mode.name,
                site_config=config.get("site", {}),
                integrations={},
                external_check={},
                compare_summary=summary,
                sites=[
                    {
                        "label": item["label"],
                        "url": item["url"],
                        "exported": item["exported"],
                        "analysis": item["analysis"],
                    }
                    for item in site_results
                ],
            )
        write_metrics(output_dir)
        log.info("Compare summary written to %s", output_dir / "comparison_summary.json")
    finally:
        cache.close()


# ============================================================
# === Main Workflow ===
# ============================================================


async def main_async(args, config: dict[str, Any]):
    from storage.cache import APICache
    from storage.database import CrawlDatabase

    start_time = time.time()

    # === تحديد الـ Mode ===
    mode = get_mode(args.mode, config)
    log.info(f"🎯 Mode: {mode.name} - {mode.description}")

    # تطبيق defaults الخاصة بالـ mode
    config = mode.apply_defaults(config)

    # === تحديد URL لو مُعطى من CLI ===
    if args.url:
        configure_target_site(config, args.url)
        log.info(f"🌐 Target URL: {args.url}")

    # === قالب منصّة التجارة (IMP-11) — يُطبَّق عند تحديده صراحةً ===
    preset_name = (config.get("site", {}) or {}).get("platform_preset", "")
    if preset_name and preset_name != "auto":
        from config_presets import apply_preset, PRESETS
        if preset_name in PRESETS:
            apply_preset(config, preset_name)
            log.info(f"🛍️  Applied platform preset: {PRESETS[preset_name]['label']}")

    with span("workflow.main", mode=mode.name, url=config["site"].get("start_url", "")):
        if mode.name == "compare":
            await run_compare_workflow(args, config, mode)
            return

        # === DB و Cache ===
        state_dir = Path(config.get("state", {}).get("state_dir", "./state"))
        state_dir.mkdir(parents=True, exist_ok=True)
        db_path = state_dir / f"crawl_{mode.name}.db"
        cache_path = state_dir / "api_cache.db"

        log.info(f"💾 API Cache: {cache_path}")
        cache = APICache(
            str(cache_path),
            default_ttl_days=config.get("state", {}).get("cache_ttl_days", 7),
        )

        if args.clear_cache:
            log.info("Clearing cache...")
            with span("cache.clear"):
                cache.invalidate()
            log.info("✅ Cache cleared")
            cache.close()
            return

        use_db = config.get("state", {}).get("use_database", True)
        db = None
        if use_db:
            log.info(f"📦 SQLite Database: {db_path}")
            if args.no_resume and db_path.exists():
                log.info("Starting fresh - removing existing DB")
                db_path.unlink()
            with span("db.open", path=str(db_path)):
                db = CrawlDatabase(str(db_path))

        output_dir = setup_output_dir(config, mode.name)

        # === وضع «جلب التكامل فقط»: بلا زحف، فقط GSC/GA4/PageSpeed ===
        if getattr(args, "integrations_only", False):
            await _run_integrations_only(config, mode, output_dir, cache, db=db)
            cache.close()
            return

        # v1.08: تفعيل Phase 2 (يستعمل deferred_urls.csv كبذور إضافيّة + يُعطّل التأجيل)
        if getattr(args, "phase2", False):
            config.setdefault("crawl", {}).setdefault("deferred_crawl", {})["phase2"] = True
            log.info("🔁 Phase 2 mode — جميع الروابط ستُفحص (لا تأجيل)")

        crawler = None
        try:
            # === Phase 1: Crawl ===
            if not args.analyze_only:
                if args.sync:
                    crawler = run_crawl_sync(config)
                else:
                    crawler = await run_crawl_async(config, db=db)
            else:
                log.info("Skipping crawl - using existing DB")
                if not db:
                    raise ValueError("--analyze-only requires state.use_database=true")
                crawler = DatabaseBackedCrawler(db)

            # عند الإيقاف اليدوي نُنتج النتائج الجزئية بسرعة: نتخطّى فحص
            # الروابط الخارجية (المرحلة الأبطأ) لكن نُكمل التحليل والتصدير.
            stopped_early = getattr(crawler, "_external_stop", False)

            # === Phase 2: Analyze ===
            emit_phase(crawler, "analyzing", phase_label="analyzing", phase_percent=0)
            analysis = run_analysis(crawler, config, mode)

            # === Phase 2.5: External Links ===
            external_check = {"external_results": []}
            if not args.skip_external and not stopped_early:
                emit_phase(crawler, "checking_external_links",
                           phase_label="checking_external_links", phase_percent=0)
                external_check = await run_external_links_check(crawler, db, config, mode)
            elif stopped_early:
                log.info("→ External links check skipped (manual stop — exporting partial results)")

            # === Phase 2.6: Resource status (اختياري، مطفأ افتراضياً) ===
            if not stopped_early:
                resource_status = await run_resource_status_check(crawler, config, mode)
                analysis["resource_status"] = resource_status.get("resource_status", [])

            # === Phase 3: Integrations ===
            integrations = run_integrations(crawler, config, mode, cache=cache)

            # === تحليلات GSC: تكلّس الكلمات + فُرَص الروابط الداخلية (IMP-1) ===
            try:
                from analyzers.gsc_insights import (
                    detect_cannibalization, find_internal_link_opportunities)
                pq = (integrations or {}).get("gsc_page_queries") or []
                if pq:
                    analysis["cannibalization"] = detect_cannibalization(pq)
                    log.info(
                        f"→ Cannibalization: "
                        f"{analysis['cannibalization']['count']} استعلام متنافَس عليه")
                gsc_pages = (integrations or {}).get("gsc_pages") or []
                if gsc_pages:
                    ls_pages = (analysis.get("link_score") or {}).get("pages") or []
                    analysis["internal_link_opportunities"] = \
                        find_internal_link_opportunities(gsc_pages, ls_pages)
                    log.info(
                        f"→ Internal-link opportunities: "
                        f"{analysis['internal_link_opportunities']['count']} صفحة")
            except Exception:  # noqa: BLE001
                log.exception("GSC insights failed")

            # === التقرير الموحّد: دمج تقني + GSC + GA4 وحساب الأولويات ===
            try:
                from reporting.report_join import build_unified
                from reporting.opportunities import compute_opportunities
                unified_rows = build_unified(
                    crawler.get_pages(), analysis,
                    integrations.get("gsc_pages"),
                    integrations.get("ga4_landing_pages"),
                )
                analysis["unified_rows"] = unified_rows
                analysis["opportunities"] = compute_opportunities(unified_rows)
                # محرّك الأولويات v2: درجة متعددة العوامل + لوحة عمل (حتمي)
                from reporting.priority_engine import compute_priority
                platform = (config.get("site", {}) or {}).get("platform_preset", "")
                analysis["priority"] = compute_priority(unified_rows, platform=platform)
                log.info(
                    f"→ Unified report: {len(unified_rows)} pages | "
                    f"opportunities {analysis['opportunities']['total_with_issues']} | "
                    f"priority do-now {analysis['priority']['summary'].get('do_now', 0)}"
                )
            except Exception:
                log.exception("Unified report build failed")
                analysis["unified_rows"] = []
                analysis["opportunities"] = {}
                analysis["priority"] = {}

            # === Phase 3.5: AI Advisor (اختياري) ===
            analysis["ai_analysis"] = run_ai_analysis(analysis, config)

            # === Phase 4: Export ===
            emit_phase(crawler, "exporting", phase_label="exporting", phase_percent=0)
            exported_files = run_export(
                crawler, analysis, integrations, external_check, output_dir, config, mode
            )

            # === الحالة النهائية للتقدّم (بعد اكتمال التصدير) ===
            if getattr(crawler, "_reached_max_pages", False):
                emit_phase(crawler, "partial_max_pages")
            elif getattr(crawler, "_external_stop", False):
                emit_phase(crawler, "stopped")
            else:
                emit_phase(crawler, "complete")

            # === Summary ===
            duration = time.time() - start_time
            db_stats = None
            if db:
                db_stats = db.get_stats()
                gauge("db.tables", db_stats)

            cache_stats = cache.get_stats()
            gauge("cache.stats", cache_stats)

            metrics_file = write_metrics(output_dir)
            if metrics_file:
                exported_files["metrics"] = metrics_file

            log.info("=" * 60)
            log.info(f"✅ Completed successfully! ({mode.name} mode)")
            log.info("=" * 60)
            log.info(f"Duration: {duration:.1f}s")
            log.info(f"Output:   {output_dir}")
            log.info(f"Files:    {len(exported_files)}")

            if db_stats:
                log.info("\n📊 DB Stats:")
                for table, count in db_stats.items():
                    log.info(f"  {table}: {count}")

            log.info(f"\n💾 Cache: {cache_stats.get('valid_entries', 0)} entries, "
                     f"{cache_stats.get('db_size_mb', 0)} MB")
            log.info("=" * 60)

            if "excel" in exported_files:
                print(f"\n📊 Excel: {exported_files['excel']}")
            if "json" in exported_files:
                print(f"📦 JSON: {exported_files['json']}")
            if "metrics" in exported_files:
                print(f"📈 Metrics: {exported_files['metrics']}")

        except Exception as e:
            failed_phase = "unknown"
            try:
                current = {}
                pf = os.environ.get("SCT_PROGRESS_FILE")
                if pf and os.path.exists(pf):
                    with open(pf, "r", encoding="utf-8") as f:
                        current = json.load(f) or {}
                failed_phase = current.get("status", "unknown")
            except (OSError, json.JSONDecodeError):
                pass
            emit_phase(
                crawler,
                "failed",
                failed_phase=failed_phase,
                error=type(e).__name__,
                error_message=str(e)[:500],
            )
            log.error("Workflow failed during phase '%s': %s", failed_phase, e, exc_info=True)
            raise
        finally:
            if db:
                db.close()
            cache.close()


def main():
    parser = argparse.ArgumentParser(
        description="SEO Crawler v3.0 - Async + SQLite + Cache + Multi-mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                                    # Full audit (default)
  python main.py --mode audit                       # Same as above
  python main.py --mode competitor --url https://x  # Analyze competitor
  python main.py --mode compare                     # Compare multiple sites
  python main.py --clear-cache                      # Clear API cache
  python main.py --no-resume                        # Start fresh
        """,
    )
    parser.add_argument(
        "--mode", default="audit", choices=list(AVAILABLE_MODES.keys()),
        help="Crawl mode: audit (default) / competitor / compare",
    )
    parser.add_argument("--url", help="Override start URL from config")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--sync", action="store_true", help="Use sync crawler")
    parser.add_argument("--analyze-only", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--skip-external", action="store_true")
    parser.add_argument("--integrations-only", action="store_true",
                        help="جلب بيانات التكامل (GSC/GA4/PageSpeed) فقط بلا زحف")
    parser.add_argument("--phase2", action="store_true",
                        help="v1.08: زحف Phase 2 — يستعمل deferred_urls.csv كبذور "
                             "ويعطّل المصنّف (يفحص الجميع). يُمدّد audit JSON الحالي.")
    parser.add_argument("--clear-cache", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    config = load_config(args.config)
    # v1.10-C1 (M-8): validate config قبل أيّ شيء — التحذيرات تظهر مباشرة في
    # stdout قبل تفعيل logging كي يراها المستخدم بوضوح.
    _cfg_warnings = validate_config(config)
    for w in _cfg_warnings:
        print(f"⚠️ config: {w}", file=sys.stderr)
    logging_config = config.get("logging", {})
    configure_logging(
        level=logging_config.get("level", "INFO"),
        log_dir=logging_config.get("log_dir", "./logs"),
        console_output=logging_config.get("console_output", True),
        file_output=logging_config.get("file_output", True),
        max_log_size_mb=logging_config.get("max_log_size_mb", 50),
        backup_count=logging_config.get("backup_count", 3),
    )
    configure_monitoring(config.get("observability", {}))

    print("""
╔══════════════════════════════════════════════════════════════╗
║       SEO Crawler v3.0                                       ║
║   Async + SQLite + Cache + Multi-mode (audit/competitor)     ║
╚══════════════════════════════════════════════════════════════╝
    """)

    try:
        asyncio.run(main_async(args, config))
    except KeyboardInterrupt:
        log.warning("\n⚠️  Stopped manually")
        log.info("State saved")
        sys.exit(130)
    except ModuleNotFoundError as e:
        missing = e.name or "unknown"
        log.error(
            "Missing dependency: %s. Install dependencies with: "
            "python -m pip install -r requirements.txt",
            missing,
        )
        sys.exit(1)
    except Exception as e:
        log.error(f"Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
