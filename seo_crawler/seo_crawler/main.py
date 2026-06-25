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
# v1.12.1 REFACTOR-services: run_analysis نُقل إلى services/analysis_service.py
from services.analysis_service import run_analysis  # noqa: E402,F401

# ============================================================
# === External Links Check + Resource Status Check ===
# ============================================================
# v1.12.1 REFACTOR-services: نُقلا إلى services/external_check_service.py
from services.external_check_service import (  # noqa: E402,F401
    run_external_links_check,
    run_resource_status_check,
)
# v1.12 REFACTOR-services: AI advisor نُقل إلى services/ai_service.py
from services.ai_service import run_ai_analysis


# ============================================================
# === Integrations ===
# ============================================================
# v1.12.1 REFACTOR-services: نُقل إلى services/integrations_service.py
from services.integrations_service import run_integrations  # noqa: E402,F401

# ============================================================
# === Export ===
# ============================================================
# v1.12.2 REFACTOR-services: نُقل إلى services/export_service.py
from services.export_service import run_export  # noqa: E402,F401


# v1.12.2 REFACTOR-services: compare helpers نُقلت إلى services/compare_service.py
from services.compare_service import (  # noqa: E402,F401
    build_compare_summary,
    summarize_crawler_result,
)


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


# v1.12.1 REFACTOR-services: MinimalCrawler نُقل إلى services/integrations_service.py
from services.integrations_service import MinimalCrawler as _MinimalCrawler  # noqa: E402,F401


# v1.12.2 REFACTOR-services: نُقل إلى services/integrations_only_service.py
from services.integrations_only_service import (  # noqa: E402,F401
    run_integrations_only as _run_integrations_only,
)

# v1.12.2 REFACTOR-services: نُقل إلى services/compare_service.py
from services.compare_service import run_compare_workflow  # noqa: E402,F401

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
                    # v1.13.15 (B2): KeyboardInterrupt أثناء crawl لا يجب أن يقتل export.
                    # نلتقطه هنا، نوسم crawler بالـstop، ونتابع لمرحلة export الجزئيّة.
                    try:
                        crawler = await run_crawl_async(config, db=db)
                    except (KeyboardInterrupt, asyncio.CancelledError):
                        log.warning("⚠️  Crawl interrupted — falling through to partial export")
                        # crawler قد يكون None إن انكسر قبل return؛ في تلك الحالة نخرج بهدوء.
                        if crawler is None:
                            emit_phase(None, "stopped")
                            return
                        crawler._external_stop = True
                        crawler._stop_requested = True
            else:
                log.info("Skipping crawl - using existing DB")
                if not db:
                    raise ValueError("--analyze-only requires state.use_database=true")
                crawler = DatabaseBackedCrawler(db)

            # عند الإيقاف اليدوي نُنتج النتائج الجزئية بسرعة: نتخطّى فحص
            # الروابط الخارجية (المرحلة الأبطأ) لكن نُكمل التحليل والتصدير.
            stopped_early = getattr(crawler, "_external_stop", False)

            # v1.13.16 (E-Stop): عند إيقاف يدوي نقفز فوراً إلى export بأدنى تحليل
            # ممكن — لا تكاملات (Google/Backlinks/AI)، لا روابط خارجيّة، لا
            # link_score الثقيل، لا near_duplicate. النتائج الجزئيّة تظهر خلال
            # ثوانٍ بدل ~دقيقة من الانتظار. المستخدم يحصل على pages.csv بأخطاء
            # الـSEO الأساسيّة فقط.
            external_check = {"external_results": []}
            integrations = {}
            if stopped_early:
                emit_phase(crawler, "exporting",
                           phase_label="exporting", phase_percent=0)
                log.info("→ Stop signal received: minimal export (skip analysis + integrations + AI)")
                analysis = {}
            else:
                # === Phase 2: Analyze (المسار العادي فقط) ===
                emit_phase(crawler, "analyzing",
                           phase_label="analyzing", phase_percent=0)
                try:
                    analysis = run_analysis(crawler, config, mode)
                except (KeyboardInterrupt, asyncio.CancelledError):
                    log.warning("⚠️  Analysis interrupted — falling through to partial export")
                    analysis = {}
                    stopped_early = True
                    crawler._external_stop = True

                # === Phase 2.5: External Links ===
                if not args.skip_external and not stopped_early:
                    emit_phase(crawler, "checking_external_links",
                               phase_label="checking_external_links", phase_percent=0)
                    external_check = await run_external_links_check(
                        crawler, db, config, mode)

                # === Phase 2.6: Resource status (اختياري) ===
                if not stopped_early:
                    resource_status = await run_resource_status_check(crawler, config, mode)
                    analysis["resource_status"] = resource_status.get("resource_status", [])

                # === Phase 3: Integrations (نتخطّاها كاملاً عند الإيقاف) ===
                if not stopped_early:
                    integrations = run_integrations(crawler, config, mode, cache=cache)

                # === تحليلات GSC ===
                if not stopped_early:
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

                # === التقرير الموحّد ===
                if not stopped_early:
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

                # === Phase 3.5: AI Advisor (نتخطّاه عند الإيقاف) ===
                if not stopped_early:
                    analysis["ai_analysis"] = run_ai_analysis(analysis, config)

            # === Phase 4: Export ===
            # v1.13.15 (B2): export يجب أن يكتمل حتى لو وصلت إشارة إيقاف ثانية
            # أثناءه — وإلاّ نخسر كل العمل. KeyboardInterrupt هنا → نسجّل ونمضي
            # (run_export نفسها لها try/except داخليّة لكل format).
            emit_phase(crawler, "exporting", phase_label="exporting", phase_percent=0)
            try:
                exported_files = run_export(
                    crawler, analysis, integrations, external_check, output_dir, config, mode
                )
            except (KeyboardInterrupt, asyncio.CancelledError):
                log.warning("⚠️  Export interrupted — keeping whatever was written")
                exported_files = {}
                stopped_early = True

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
