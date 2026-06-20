"""
services/ai_service.py — مستشار الذكاء الاصطناعي (Phase 3.5، اختياري).

نُقل من main.py في v1.12 (Tier 1 — self-contained، lazy import لـintegrations.ai_advisor).
"""

from __future__ import annotations

import os
from typing import Any

from utils.logger import get_logger
from utils.monitoring import span

log = get_logger(__name__)


def run_ai_analysis(analysis: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """مستشار الذكاء الاصطناعي (اختياري) — يقرأ ملخّص التدقيق ويقترح تحسينات.

    مطفأ افتراضياً. المفتاح من الإعداد المحلي أو متغيّر البيئة AI_API_KEY (لا يُخزَّن
    في المستودع). يتعامل بلطف عند غياب المفتاح/المكتبة أو فشل الشبكة.
    """
    ai_cfg = (config.get("integrations", {}) or {}).get("ai", {}) or {}
    if not ai_cfg.get("enabled"):
        return {}

    from integrations.ai_advisor import AIAdvisor, build_audit_summary_for_ai

    advisor = AIAdvisor(
        provider=ai_cfg.get("provider", "openai"),
        api_key=ai_cfg.get("api_key") or os.getenv("AI_API_KEY", ""),
        model=ai_cfg.get("model", ""),
        base_url=ai_cfg.get("base_url", ""),
        timeout=int(ai_cfg.get("timeout", 60)),
        language=config.get("report", {}).get("language", "ar"),
        allow_private=bool(ai_cfg.get("allow_private", False)),
    )
    site_url = config.get("site", {}).get("start_url", "")
    summary = build_audit_summary_for_ai(
        analysis, site_url=site_url,
        max_opportunities=int(ai_cfg.get("max_opportunities", 15)),
    )

    log.info("=" * 60)
    log.info("Phase 3.5: AI Advisor (%s)", ai_cfg.get("provider", "openai"))
    log.info("=" * 60)
    with span("phase.ai_advisor", provider=ai_cfg.get("provider", "")):
        result = advisor.analyze(summary)
    if result.get("error"):
        log.warning("→ AI advisor unavailable: %s", result["error"])
    else:
        log.info("→ AI advisor: %d recommendation(s)", len(result.get("recommendations", [])))
    return result
