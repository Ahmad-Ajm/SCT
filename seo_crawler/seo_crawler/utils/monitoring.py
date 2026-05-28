"""
utils/monitoring.py
===================
Lightweight observability helpers for crawl runs.

The module records timings, counters, and gauges without introducing external
dependencies. It is intentionally global because the crawler has many execution
paths; a single collector keeps phase, URL, DB, and export metrics together.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Iterator

from utils.logger import get_logger

log = get_logger(__name__)

# مفاتيح محجوزة لتوقيع event()/span — نُعيد تسميتها في attrs لتفادي
# TypeError: "got multiple values for argument ..." عند تمريرها من المتصل.
_RESERVED_ATTR_KEYS = frozenset({"name", "status", "duration_ms", "error"})


def _safe_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    """إعادة تسمية أي مفاتيح تتعارض مع وسائط event() الموضعية."""
    if not any(k in _RESERVED_ATTR_KEYS for k in attrs):
        return attrs
    return {
        (f"attr_{k}" if k in _RESERVED_ATTR_KEYS else k): v
        for k, v in attrs.items()
    }


class MetricsCollector:
    """Thread-safe metrics collector for one CLI run."""

    def __init__(self) -> None:
        self.enabled = False
        self.log_function_calls = False
        self.log_url_events = False
        self.log_extraction_details = False
        self.slow_call_ms = 500.0
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.started_at = datetime.now().isoformat()
            self.counters: dict[str, int | float] = {}
            self.gauges: dict[str, Any] = {}
            self.timings: dict[str, dict[str, float]] = {}
            self.recent_events: list[dict[str, Any]] = []

    def configure(self, config: dict[str, Any] | None) -> None:
        config = config or {}
        self.enabled = bool(config.get("enabled", True))
        self.log_function_calls = bool(config.get("log_function_calls", True))
        self.log_url_events = bool(config.get("log_url_events", True))
        self.log_extraction_details = bool(config.get("log_extraction_details", True))
        self.slow_call_ms = float(config.get("slow_call_ms", 500))
        # تجميع تحذيرات البطء في ملخص نهائي بدل تحذير لكل نداء (يقلّل ضجيج اللوغ)
        self.slow_call_summary = bool(config.get("slow_call_summary", True))
        self.reset()

    @contextmanager
    def span(self, name: str, **attrs: Any) -> Iterator[None]:
        if not self.enabled:
            yield
            return

        start = perf_counter()
        if self.log_function_calls and self._should_log_span(name):
            log.debug("▶ %s start %s", name, self._format_attrs(attrs))

        try:
            yield
        except Exception as exc:
            elapsed_ms = (perf_counter() - start) * 1000
            self._record_timing(name, elapsed_ms)
            self.increment(f"errors.{name}")
            self.event(
                name, "error", duration_ms=round(elapsed_ms, 2),
                error=type(exc).__name__, **_safe_attrs(attrs),
            )
            log.error("✖ %s failed after %.2fms: %s", name, elapsed_ms, exc)
            raise
        else:
            elapsed_ms = (perf_counter() - start) * 1000
            self._record_timing(name, elapsed_ms)
            self.event(name, "ok", duration_ms=round(elapsed_ms, 2), **_safe_attrs(attrs))
            if self.log_function_calls and self._should_log_span(name):
                # عند تفعيل الملخص: لا نُحذّر لكل نداء بطيء (يُجمَّع في النهاية)
                if elapsed_ms >= self.slow_call_ms and not self.slow_call_summary:
                    logger = log.warning
                else:
                    logger = log.debug
                logger("✓ %s end %.2fms %s", name, elapsed_ms, self._format_attrs(attrs))

    def increment(self, name: str, value: int | float = 1) -> None:
        if not self.enabled:
            return
        with self._lock:
            self.counters[name] = self.counters.get(name, 0) + value

    def gauge(self, name: str, value: Any) -> None:
        if not self.enabled:
            return
        with self._lock:
            self.gauges[name] = self._json_safe(value)

    def event(self, name: str, status: str, **attrs: Any) -> None:
        if not self.enabled:
            return
        with self._lock:
            self.recent_events.append(
                {
                    "ts": datetime.now().isoformat(),
                    "name": name,
                    "status": status,
                    "attrs": self._json_safe(attrs),
                }
            )
            if len(self.recent_events) > 500:
                self.recent_events = self.recent_events[-500:]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "started_at": self.started_at,
                "finished_at": datetime.now().isoformat(),
                "counters": dict(sorted(self.counters.items())),
                "gauges": dict(sorted(self.gauges.items())),
                "timings": {
                    name: {
                        "count": int(data["count"]),
                        "total_ms": round(data["total_ms"], 2),
                        "avg_ms": round(data["total_ms"] / data["count"], 2) if data["count"] else 0,
                        "min_ms": round(data["min_ms"], 2),
                        "max_ms": round(data["max_ms"], 2),
                    }
                    for name, data in sorted(self.timings.items())
                },
                "recent_events": list(self.recent_events),
            }

    def write(self, output_dir: str | Path, filename: str = "metrics.json") -> str:
        if not self.enabled:
            return ""
        self.log_slow_summary()
        path = Path(output_dir) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.snapshot(), f, ensure_ascii=False, indent=2, default=str)
        log.info("📈 Metrics written: %s", path)
        return str(path)

    def log_slow_summary(self, top_n: int = 10) -> None:
        """ملخص أبطأ المراحل (بدل تحذير لكل نداء بطيء)."""
        if not (self.enabled and self.slow_call_summary):
            return
        with self._lock:
            slow = [
                (name, data["max_ms"], data["total_ms"] / data["count"] if data["count"] else 0,
                 int(data["count"]))
                for name, data in self.timings.items()
                if data["max_ms"] >= self.slow_call_ms
            ]
        if not slow:
            return
        slow.sort(key=lambda x: x[1], reverse=True)
        log.info("⏱️  ملخص الأداء — أبطأ %d مرحلة (الحد %.0fms):", min(top_n, len(slow)), self.slow_call_ms)
        for name, mx, avg, cnt in slow[:top_n]:
            log.info("    %-32s count=%-5d avg=%.0fms max=%.0fms", name, cnt, avg, mx)

    def _record_timing(self, name: str, elapsed_ms: float) -> None:
        with self._lock:
            data = self.timings.setdefault(
                name,
                {"count": 0.0, "total_ms": 0.0, "min_ms": elapsed_ms, "max_ms": elapsed_ms},
            )
            data["count"] += 1
            data["total_ms"] += elapsed_ms
            data["min_ms"] = min(data["min_ms"], elapsed_ms)
            data["max_ms"] = max(data["max_ms"], elapsed_ms)

    def _should_log_span(self, name: str) -> bool:
        if name.startswith(("crawler.async.page", "crawler.async.fetch", "external_link.")):
            return self.log_url_events
        if name.startswith("crawler.extract."):
            return self.log_extraction_details
        return True

    def _format_attrs(self, attrs: dict[str, Any]) -> str:
        if not attrs:
            return ""
        compact = ", ".join(f"{key}={self._short(value)}" for key, value in attrs.items())
        return f"({compact})"

    def _short(self, value: Any) -> str:
        text = str(value)
        return text if len(text) <= 140 else text[:137] + "..."

    def _json_safe(self, value: Any) -> Any:
        try:
            json.dumps(value, ensure_ascii=False, default=str)
            return value
        except TypeError:
            return str(value)


collector = MetricsCollector()


def reset_monitoring() -> None:
    """تصفير العدّادات/المؤشّرات/التوقيتات مع الحفاظ على الإعدادات.

    يُستخدم بين مواقع وضع المقارنة كي لا تتراكم مقاييس موقع على آخر.
    """
    collector.reset()


def configure_monitoring(config: dict[str, Any] | None) -> None:
    collector.configure(config)
    if collector.enabled:
        log.info(
            "Observability enabled: calls=%s url_events=%s extraction=%s slow_call_ms=%.0f",
            collector.log_function_calls,
            collector.log_url_events,
            collector.log_extraction_details,
            collector.slow_call_ms,
        )


def span(name: str, **attrs: Any):
    return collector.span(name, **attrs)


def increment(name: str, value: int | float = 1) -> None:
    collector.increment(name, value)


def gauge(name: str, value: Any) -> None:
    collector.gauge(name, value)


def event(name: str, status: str, **attrs: Any) -> None:
    collector.event(name, status, **attrs)


def write_metrics(output_dir: str | Path, filename: str = "metrics.json") -> str:
    return collector.write(output_dir, filename)
