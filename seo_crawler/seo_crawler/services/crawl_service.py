"""
services/crawl_service.py — تشغيل الـcrawler (sync + async) + helpers لـPhase 2.

نُقل من main.py في v1.12 (Tier 2 mid-tier).
يعتمد على crawler.core, crawler.async_core, utils.helpers — لا أيّ service آخر
(عدا التيرز السفلى عبر utils.monitoring).
"""

from __future__ import annotations

import csv as _csv
from pathlib import Path
from typing import TYPE_CHECKING, Any

from utils.logger import get_logger
from utils.monitoring import span

if TYPE_CHECKING:
    from crawler.async_core import AsyncCrawler
    from crawler.core import Crawler
    from storage.database import CrawlDatabase

log = get_logger(__name__)


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
    is_phase2 = bool((config.get("crawl", {}).get("deferred_crawl", {}) or {}).get("phase2"))
    log.info(f"{'Phase 2' if is_phase2 else 'Phase 1'}: Crawling (Async)")
    log.info("=" * 60)
    with span("phase.crawl.async", url=config["site"].get("start_url", ""), use_db=bool(db)):
        crawler = AsyncCrawler(config, db=db)
        # v1.08: في Phase 2، حقن الـdeferred URLs المحفوظة سابقاً كبذور إضافيّة
        if is_phase2:
            inject_phase2_seeds(crawler, config)
        await crawler.run()
    return crawler


def find_phase2_deferred_csv(output_dir: str) -> Path | None:
    """v1.09-B1: يبحث عن deferred_urls.csv من Phase 1 بطريقة تتحمّل
    `timestamped_folder=true` (افتراضي): إن لم يوجد في output_dir الحالي، نبحث
    في أحدث مجلّد شقيق (نفس parent) فيه `csv/deferred_urls.csv`."""
    out = Path(output_dir)
    direct = out / "csv" / "deferred_urls.csv"
    if direct.exists():
        return direct
    parent = out.parent
    if not parent.exists():
        return None
    # نُرتّب بحسب mtime تنازلياً ونعود إلى أحدث شقيق فيه deferred CSV
    siblings = [d for d in parent.iterdir() if d.is_dir() and d != out]
    siblings.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    for sib in siblings:
        cand = sib / "csv" / "deferred_urls.csv"
        if cand.exists():
            log.info(f"Phase 2: تمّ العثور على deferred_urls.csv في شقيق: {cand}")
            return cand
    return None


def inject_phase2_seeds(crawler: Any, config: dict[str, Any]) -> None:
    """v1.08: قبل بدء الزحف في وضع Phase 2، نقرأ deferred_urls.csv من المهمّة
    السابقة ونضيفها كبذور إضافيّة. classifier.phase2_mode=True يعني أنّها تُعامَل
    عاديّة بلا تأجيل.

    v1.09-B1: يدعم timestamped_folder=true عبر البحث في أشقّاء الـoutput_dir
    (كان مكسوراً افتراضياً قبل هذا الإصلاح)."""
    output_dir = config.get("output", {}).get("output_dir", "")
    if not output_dir:
        return
    csv_path = find_phase2_deferred_csv(output_dir)
    if not csv_path:
        log.warning(f"Phase 2: deferred_urls.csv غير موجود في {output_dir} ولا في أيّ "
                    f"مجلّد شقيق — Phase 2 لن تُحقَن بذور.")
        return
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            urls = [row.get("url", "").strip() for row in _csv.DictReader(f) if row.get("url")]
    except OSError as e:
        log.warning(f"Phase 2: تعذّر قراءة deferred_urls.csv: {e}")
        return
    # v1.09-B5: فحص SSRF لكلّ URL مقروء من CSV (المستخدم قد يحرّره)
    from utils.helpers import is_safe_remote_url
    allow_private = bool(config.get("crawl", {}).get("allow_private_hosts", False))
    # نُضيفها إلى sitemap_seeds (تُسحب إلى الطابور كبذور مؤجَّلة عاديّة)
    added = 0
    rejected = 0
    for u in urls:
        if not u or u in crawler.sitemap_seeds:
            continue
        safe, _reason = is_safe_remote_url(u, allow_private)
        if not safe:
            rejected += 1
            continue
        crawler.sitemap_seeds.append(u)
        added += 1
    log.info(f"Phase 2: حُقن {added} رابط مؤجَّل سابقاً كبذور للزحف"
             + (f" (رفض {rejected} لعدم الأمان)" if rejected else ""))
