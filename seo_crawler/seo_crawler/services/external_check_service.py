"""
services/external_check_service.py — Phase 2.5 + 2.6: فحص الروابط الخارجية + الموارد.

نُقل من main.py في v1.12 (Tier 3 — يعتمد على services/progress_service لـemit_phase،
checkers.external_links_checker، utils.monitoring).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from services.progress_service import emit_phase
from utils.logger import get_logger
from utils.monitoring import gauge, span

if TYPE_CHECKING:
    from modes.base import CrawlMode

log = get_logger(__name__)


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

    # v1.13.25: هذه المرحلة كانت "صامتة" — على متجر بآلاف الموارد قد تستغرق
    # ساعات دون أيّ تحديث في progress.json، فتبدو الواجهة معلّقة. نضيف نفس نمط
    # التقدّم المستعمل في فحص الروابط الخارجية (Phase 2.5): emit أوّليّ + callback
    # مُخنَّق كل 0.5 ثانية يُظهر [عدد/إجمالي] + الرابط الحالي + شريط نسبة يتحرّك.
    total_res = len(urls)
    emit_phase(
        crawler,
        "checking_resource_status",
        phase_label="checking_resource_status",
        phase_percent=0,
        phase_detail=f"0/{total_res}",
        resource_status_total=total_res,
        resource_status_checked=0,
    )
    res_totals = {"checked": 0, "ok": 0, "broken": 0, "blocked": 0, "errors": 0}
    res_last_emit = 0.0

    def on_resource_progress(delta: dict[str, Any]) -> None:
        nonlocal res_last_emit
        res_totals["checked"] += int(delta.get("checked", 0))
        for key in ("ok", "broken", "blocked", "errors"):
            res_totals[key] += int(delta.get(key, 0))
        now = time.time()
        is_last = res_totals["checked"] >= total_res
        if is_last or now - res_last_emit >= 0.5:
            res_last_emit = now
            pct = int(res_totals["checked"] * 100 / max(total_res, 1))
            cur = str(delta.get("url", "") or "")
            detail = f"{res_totals['checked']}/{total_res} (✓ {res_totals['ok']} · ✗ {res_totals['broken']})"
            if cur:
                detail = f"{detail} · {cur}"
            emit_phase(
                crawler,
                "checking_resource_status",
                phase_label="checking_resource_status",
                phase_percent=pct,
                phase_detail=detail,
                resource_status_total=total_res,
                resource_status_checked=res_totals["checked"],
                resource_status_broken=res_totals["broken"],
            )

    with span("phase.resource_status", urls=len(urls)):
        results = await checker.check_urls(
            urls, progress=True, progress_callback=on_resource_progress)

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
