"""
modes/base.py
==============
الفئة الأساسية لكل modes (audit/competitor/compare).

كل mode يرث منها ويُحدّد:
- ما يُستخرَج
- ما يُحلَّل
- ما يُصدَّر
- إعدادات افتراضية مخصصة
"""

from abc import ABC, abstractmethod
from typing import Any


class CrawlMode(ABC):
    """فئة أساسية لكل modes الزحف."""

    name: str = "base"
    description: str = "Base mode"

    def __init__(self, config: dict[str, Any]):
        self.config = config

    @abstractmethod
    def apply_defaults(self, config: dict[str, Any]) -> dict[str, Any]:
        """تطبيق الإعدادات الافتراضية الخاصة بهذا الـ mode."""
        ...

    @abstractmethod
    def get_extractors(self) -> list[str]:
        """ما الـ extractors التي يجب تشغيلها."""
        ...

    @abstractmethod
    def get_analyzers(self) -> list[str]:
        """ما الـ analyzers التي يجب تشغيلها."""
        ...

    @abstractmethod
    def get_excel_sheets(self) -> list[str]:
        """ما الأوراق التي يجب تضمينها في Excel."""
        ...

    def should_check_external_links(self) -> bool:
        """هل نفحص الروابط الخارجية؟"""
        return True

    def should_run_integrations(self) -> bool:
        """هل نشغّل التكاملات (GSC, PageSpeed)؟"""
        return True
