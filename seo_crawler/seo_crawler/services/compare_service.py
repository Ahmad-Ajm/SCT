"""
services/compare_service.py — وضع --mode compare (زحف متعدّد المواقع).

نُقل من main.py في v1.12.2 (Tier 5 orchestrator — يستورد من 6+ services).
يحتوي أيضاً build_compare_summary + summarize_crawler_result (تستخدمها compare).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from services.analysis_service import run_analysis
from services.config_service import configure_target_site, setup_output_dir, slugify_label
from services.crawl_service import run_crawl_async, run_crawl_sync
from services.db_facade import DatabaseBackedCrawler
from services.export_helpers import get_value
from services.export_service import run_export
from services.integrations_service import run_integrations
from utils.logger import get_logger
from utils.monitoring import increment, reset_monitoring, span, write_metrics

if TYPE_CHECKING:
    from modes.base import CrawlMode

log = get_logger(__name__)


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
        indexable = sum(1 for p in pages if get_value(p, "is_indexable", False))
        status_4xx = sum(1 for p in pages if 400 <= int(get_value(p, "status_code", 0) or 0) < 500)
        avg_words = 0
        if pages:
            avg_words = round(sum(int(get_value(p, "word_count", 0) or 0) for p in pages) / len(pages), 2)
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
    indexable = sum(1 for p in pages if get_value(p, "is_indexable", False))
    status_4xx = sum(1 for p in pages if 400 <= int(get_value(p, "status_code", 0) or 0) < 500)
    avg_words = 0
    if pages:
        avg_words = round(sum(int(get_value(p, "word_count", 0) or 0) for p in pages) / len(pages), 2)
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
