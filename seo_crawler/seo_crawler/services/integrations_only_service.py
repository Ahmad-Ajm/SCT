"""
services/integrations_only_service.py — وضع --integrations-only (جلب التكاملات بلا زحف).

نُقل من main.py في v1.12.2 (Tier 5 orchestrator — يستورد من 5+ services).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from services.config_service import slugify_label
from services.db_facade import DatabaseBackedCrawler
from services.export_helpers import (
    export_pagespeed_tables,
    flatten_pagespeed,
    flatten_pagespeed_opportunities,
    integrations_for_json,
)
from services.integrations_service import MinimalCrawler, run_integrations
from services.integrations_summary import ga4_summary, gsc_summary
from services.progress_service import emit_phase
from utils.logger import get_logger
from utils.monitoring import write_metrics

log = get_logger(__name__)


async def run_integrations_only(config, mode, output_dir, cache, db=None) -> None:
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
            crawler = MinimalCrawler(start_url)
        else:
            log.info(f"عُثر على {page_count} صفحة من زحف سابق — PageSpeed سيستعملها (مع سقف max_urls)")
    else:
        crawler = MinimalCrawler(start_url)
    emit_phase(crawler, "integrations", phase_label="integrations")
    integrations = run_integrations(crawler, config, mode, cache=cache)

    emit_phase(crawler, "exporting", phase_label="exporting")
    csv_dir = Path(output_dir) / "csv"
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
    ps_rows = flatten_pagespeed(ps_data)
    if ps_rows:
        exported["pagespeed"] = csv_exp._export("pagespeed.csv", ps_rows)
        log.info(f"  ✓ pagespeed.csv ({len(ps_rows)} صفوف)")
    ps_opps = flatten_pagespeed_opportunities(ps_data)
    if ps_opps:
        exported["pagespeed_opportunities"] = csv_exp._export(
            "pagespeed_opportunities.csv", ps_opps)
        log.info(f"  ✓ pagespeed_opportunities.csv ({len(ps_opps)} صفوف)")
    # الجداول المنظّمة العميقة (audits / network / treemap / failed) — IMP-17أ
    export_pagespeed_tables(ps_data, csv_exp, exported, log_each=True)

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    site_slug = slugify_label(config.get("site", {}).get("domain", "") or "site")
    json_file = JSONExporter(str(output_dir),
                             f"integrations_{site_slug}_{stamp}.json").export(
        mode="integrations_only",
        site_config=config["site"],
        gsc_summary=gsc_summary(integrations),
        ga4_summary=ga4_summary(integrations),
        integrations=integrations_for_json(integrations),
    )
    log.info(f"  ✓ {json_file}")

    metrics_file = write_metrics(output_dir)
    if metrics_file:
        log.info(f"  ✓ {metrics_file}")

    emit_phase(crawler, "complete")
    log.info("=" * 60)
    log.info("✅ انتهى جلب التكامل")
    log.info("=" * 60)
