"""
services/integrations_service.py — Phase 3: GSC + GA4 + PageSpeed + AWT + Backlinks + Lighthouse.

نُقل من main.py في v1.12.1 (Tier 3 — يعتمد على integrations.* lazy + utils + services.progress_service).
يحتوي أيضاً MinimalCrawler stub المُستخدَم من --integrations-only mode.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

from services.progress_service import emit_phase
from utils.logger import get_logger
from utils.monitoring import gauge, span

if TYPE_CHECKING:
    from modes.base import CrawlMode

log = get_logger(__name__)


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


class MinimalCrawler:
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
