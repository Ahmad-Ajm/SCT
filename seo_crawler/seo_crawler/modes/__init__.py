"""
modes — أوضاع الزحف المختلفة (audit / competitor / compare).
"""
from modes.base import CrawlMode
from modes.audit import AuditMode
from modes.competitor import CompetitorMode
from modes.compare import CompareMode


# سجل الأوضاع المتاحة
AVAILABLE_MODES = {
    "audit": AuditMode,
    "competitor": CompetitorMode,
    "compare": CompareMode,
}


def get_mode(mode_name: str, config: dict) -> CrawlMode:
    """جلب instance من mode حسب الاسم."""
    if mode_name not in AVAILABLE_MODES:
        available = ", ".join(AVAILABLE_MODES.keys())
        raise ValueError(
            f"Mode غير معروف: '{mode_name}'. المتاح: {available}"
        )
    return AVAILABLE_MODES[mode_name](config)


__all__ = ["CrawlMode", "AuditMode", "CompetitorMode", "CompareMode",
           "AVAILABLE_MODES", "get_mode"]
