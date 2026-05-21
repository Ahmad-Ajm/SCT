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
from utils.monitoring import configure_monitoring, gauge, increment, span, write_metrics

if TYPE_CHECKING:
    from crawler.async_core import AsyncCrawler
    from crawler.core import Crawler
    from modes.base import CrawlMode
    from storage.database import CrawlDatabase

log = get_logger(__name__)


# ============================================================
# === Configuration ===
# ============================================================


def load_config(config_path: str = "config.yaml") -> dict[str, Any]:
    config_file = Path(config_path)
    if not config_file.exists():
        log.error(f"Config file not found: {config_path}")
        sys.exit(1)
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        log.error(f"YAML parse error: {e}")
        sys.exit(1)


def setup_output_dir(config: dict[str, Any], mode_name: str) -> Path:
    base_dir = Path(config["output"]["output_dir"])
    if config["output"].get("timestamped_folder", True):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_dir = base_dir / f"{mode_name}_{timestamp}"
    else:
        output_dir = base_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Output directory: {output_dir}")
    return output_dir


def slugify_label(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    slug = "_".join(part for part in slug.split("_") if part)
    return slug or "site"


def configure_target_site(config: dict[str, Any], url: str) -> None:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid site URL: {url}")
    config["site"]["start_url"] = url
    config["site"]["domain"] = parsed.netloc


class DatabaseBackedCrawler:
    """Read-only crawler facade for --analyze-only without importing crawl engines."""

    def __init__(self, db: CrawlDatabase):
        self.db = db
        self.sitemap_parser = None

    def get_pages(self) -> list[dict[str, Any]]:
        return [AttrDict(row) for row in self.db.get_all_pages()]

    def get_links(self) -> list[dict[str, Any]]:
        return list(self.db.get_all_links())

    def get_images(self) -> list[dict[str, Any]]:
        return list(self.db.get_all_images())

    def get_headings(self) -> list[dict[str, Any]]:
        return list(self.db.get_all_headings())

    def get_schema(self) -> list[dict[str, Any]]:
        return list(self.db.get_all_schema())

    def get_headers(self) -> list[dict[str, Any]]:
        return list(self.db.get_all_headers())

    def get_redirects(self) -> list[dict[str, Any]]:
        return list(self.db.get_all_redirects())

    def get_stats(self) -> SimpleNamespace:
        pages = self.get_pages()
        return SimpleNamespace(
            pages_crawled=len(pages),
            pages_failed=sum(1 for page in pages if page.get("crawl_error")),
            pages_skipped=0,
            status_codes={},
            duration_seconds=0,
            pages_per_second=0,
        )


class AttrDict(dict):
    """Dictionary row that also supports attribute access for legacy analyzers."""

    def __getattr__(self, name: str) -> Any:
        return self.get(name, "")


# ============================================================
# === Crawl Functions ===
# ============================================================


def run_crawl_sync(config: dict[str, Any]) -> Crawler:
    from crawler.core import Crawler

    log.info("=" * 60)
    log.info("Phase 1: Crawling (Sync)")
    log.info("=" * 60)
    with span("phase.crawl.sync", url=config["site"].get("start_url", "")):
        crawler = Crawler(config)
        crawler.run()
    return crawler


async def run_crawl_async(
    config: dict[str, Any], db: CrawlDatabase | None = None
) -> AsyncCrawler:
    from crawler.async_core import AsyncCrawler

    log.info("=" * 60)
    log.info("Phase 1: Crawling (Async)")
    log.info("=" * 60)
    with span("phase.crawl.async", url=config["site"].get("start_url", ""), use_db=bool(db)):
        crawler = AsyncCrawler(config, db=db)
        await crawler.run()
    return crawler


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
            results["redirect_data"] = analyze_redirects(pages, redirects)
    else:
        results["redirect_data"] = {}

    analysis_config = config.get("analysis", {})

    if "thin_content" in enabled_analyzers:
        log.info("→ Detecting thin content...")
        with span("analysis.thin_content", pages=len(pages)):
            results["thin_content_data"] = detect_thin_content(
                pages,
                word_threshold=analysis_config.get("thin_content_threshold", 300),
            )
    else:
        results["thin_content_data"] = {}

    if "broken_links" in enabled_analyzers:
        log.info("→ Detecting broken links...")
        with span("analysis.broken_links", pages=len(pages), links=len(links)):
            results["broken_data"] = detect_broken_links(pages, links)
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
        # نأخذ sitemap URLs من crawler إن متاحة، وإلا نتخطى
        sitemap_urls = []
        if hasattr(crawler, "sitemap_parser") and crawler.sitemap_parser:
            # إعادة استخدام البيانات التي حُمّلت أصلاً
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

    log.info(f"Unique external links: {len(external_urls)}")

    checker = ExternalLinksChecker(
        timeout=checker_config.get("timeout", 10),
        concurrent=checker_config.get("concurrent", 20),
        user_agent=config.get("crawl", {}).get("user_agent", "SEOCrawlerBot/1.0"),
        retry_attempts=checker_config.get("retry_attempts", 2),
        verify_ssl=checker_config.get("verify_ssl", True),
    )

    with span("phase.external_links", urls=len(external_urls)):
        results = await checker.check_urls(external_urls, progress=True)

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
    gauge("external_links.total", len(results))
    gauge("external_links.broken", len(broken))
    gauge("external_links.working", len(results) - len(broken))
    log.info(f"  Broken: {len(broken)} | Working: {len(results) - len(broken)}")

    return {"external_results": results, "broken_external_links": broken}


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
    else:
        log.info("→ GSC disabled")

    ps_config = integrations_config.get("pagespeed", {})
    if ps_config.get("enabled"):
        api_key = ps_config.get("api_key") or os.getenv("PAGESPEED_API_KEY", "")
        if api_key:
            log.info("→ PageSpeed Insights (with cache)...")
            with span("integration.pagespeed"):
                client = PageSpeedClient(
                    api_key=api_key,
                    delay_seconds=ps_config.get("delay_seconds", 1),
                    cache=cache,
                    cache_ttl_days=ps_config.get("cache_ttl_days", 7),
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

    pages = crawler.get_pages()
    links = crawler.get_links()
    images = crawler.get_images()
    headings = crawler.get_headings()
    schema = crawler.get_schema()
    redirects = crawler.get_redirects()
    headers = crawler.get_headers()

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
        exported_files.update({f"csv_{k}": v for k, v in csv_files.items()})

    if "excel" in formats:
        log.info("→ Excel...")
        with span("export.excel", output_dir=str(output_dir)):
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
                excel_exporter = ExcelExporter(str(output_dir), "master_audit.xlsx")
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
        with span("export.json", output_dir=str(output_dir)):
            json_exporter = JSONExporter(str(output_dir), "complete_audit.json")
            json_file = json_exporter.export(
                pages=pages, links=links, images=images, headings=headings,
                schema=schema, redirects=redirects,
                mode=mode.name,
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
                external_check=external_check,
                integrations=integrations,
                site_config=config["site"],
            )
        exported_files["json"] = json_file

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


def _get_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


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
            finally:
                if db:
                    db.close()

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

            # === Phase 2: Analyze ===
            analysis = run_analysis(crawler, config, mode)

            # === Phase 2.5: External Links ===
            external_check = {"external_results": []}
            if not args.skip_external:
                external_check = await run_external_links_check(crawler, db, config, mode)

            # === Phase 3: Integrations ===
            integrations = run_integrations(crawler, config, mode, cache=cache)

            # === Phase 4: Export ===
            exported_files = run_export(
                crawler, analysis, integrations, external_check, output_dir, config, mode
            )

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
    parser.add_argument("--clear-cache", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    config = load_config(args.config)
    logging_config = config.get("logging", {})
    configure_logging(
        level=logging_config.get("level", "INFO"),
        log_dir=logging_config.get("log_dir", "./logs"),
        console_output=logging_config.get("console_output", True),
        file_output=logging_config.get("file_output", True),
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
