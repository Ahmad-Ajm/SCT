"""
crawler/adaptive_throttle.py
============================
تحكّم تكيّفي بسرعة الزحف (IMP-10): يزيد التأخير بين الطلبات تلقائياً عندما يُظهر الموقع
ضغطاً (429 / 5xx / استجابة بطيئة) ويُخفّضه تدريجياً عند تعافي الموقع — احتراماً للخادم
وتفادياً للحظر، دون إيقاف الزحف.

مُصمَّم كوحدة نقية قابلة للاختبار: لا I/O ولا حالة عامة. يستهلكه الزاحف عبر `delay()` قبل كل
طلب و`record(status, latency_ms)` بعده.
"""

from __future__ import annotations

from typing import Any


class AdaptiveThrottle:
    """يضبط تأخيراً إضافياً (بالثواني) حسب صحّة استجابات الموقع."""

    def __init__(
        self,
        enabled: bool = False,
        min_delay: float = 0.0,
        max_delay: float = 5.0,
        step_up: float = 0.5,
        step_down: float = 0.25,
        slow_ms: float = 3000.0,
    ):
        self.enabled = bool(enabled)
        self.min_delay = max(0.0, float(min_delay))
        self.max_delay = max(self.min_delay, float(max_delay))
        self.step_up = max(0.0, float(step_up))
        self.step_down = max(0.0, float(step_down))
        self.slow_ms = max(0.0, float(slow_ms))
        self._delay = self.min_delay

    @classmethod
    def from_config(cls, crawl_config: dict[str, Any]) -> "AdaptiveThrottle":
        cfg = (crawl_config or {}).get("adaptive_throttle", {}) or {}
        return cls(
            enabled=bool(cfg.get("enabled", False)),
            min_delay=cfg.get("min_delay", 0.0),
            max_delay=cfg.get("max_delay", 5.0),
            step_up=cfg.get("step_up", 0.5),
            step_down=cfg.get("step_down", 0.25),
            slow_ms=cfg.get("slow_ms", 3000.0),
        )

    def delay(self) -> float:
        """التأخير الإضافي الحالي بالثواني (0 عند التعطيل)."""
        return self._delay if self.enabled else 0.0

    def record(self, status_code: Any, latency_ms: float = 0.0) -> None:
        """يحدّث التأخير بناءً على نتيجة طلب."""
        if not self.enabled:
            return
        try:
            status = int(status_code or 0)
        except (TypeError, ValueError):
            status = 0
        try:
            latency = float(latency_ms or 0.0)
        except (TypeError, ValueError):
            latency = 0.0

        overloaded = status == 429 or 500 <= status < 600
        slow = self.slow_ms > 0 and latency >= self.slow_ms
        if overloaded:
            # 429/5xx ضغط صريح ⇒ تراجع أقوى (خطوتان)
            self._delay = min(self.max_delay, self._delay + self.step_up * 2)
        elif slow:
            self._delay = min(self.max_delay, self._delay + self.step_up)
        else:
            # استجابة صحّية ⇒ تعافٍ تدريجي
            self._delay = max(self.min_delay, self._delay - self.step_down)
