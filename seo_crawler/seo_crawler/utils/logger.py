"""
utils/logger.py
================
نظام السجلات الموحّد للمشروع.

يدعم:
- الكتابة على ملف + Console
- مستويات مختلفة (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- ألوان في Console
- اسم ملف مع timestamp
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init()  # تفعيل ألوان Windows
    COLOR_SUPPORT = True
except ImportError:
    COLOR_SUPPORT = False


class ColoredFormatter(logging.Formatter):
    """منسّق ملوّن للسجلات على Console فقط."""

    COLORS = {
        "DEBUG": Fore.CYAN if COLOR_SUPPORT else "",
        "INFO": Fore.GREEN if COLOR_SUPPORT else "",
        "WARNING": Fore.YELLOW if COLOR_SUPPORT else "",
        "ERROR": Fore.RED if COLOR_SUPPORT else "",
        "CRITICAL": Fore.MAGENTA if COLOR_SUPPORT else "",
    }
    RESET = Style.RESET_ALL if COLOR_SUPPORT else ""

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        formatted = super().format(record)
        return f"{color}{formatted}{self.RESET}"


# قاموس لتخزين Loggers (Singleton-like pattern)
_loggers: dict[str, logging.Logger] = {}
_file_output_enabled = False
_default_log_dir = "./logs"


def get_logger(
    name: str,
    level: str = "INFO",
    log_dir: str = "./logs",
    console_output: bool = True,
    file_output: bool | None = None,
) -> logging.Logger:
    """
    إنشاء أو استرجاع Logger باسم محدد.

    Args:
        name: اسم الـ Logger (عادةً اسم الـ module)
        level: مستوى السجل (DEBUG/INFO/WARNING/ERROR/CRITICAL)
        log_dir: مجلد حفظ السجلات
        console_output: هل نطبع على Console أيضاً؟

    Returns:
        logging.Logger: كائن Logger جاهز للاستخدام

    Example:
        >>> log = get_logger(__name__)
        >>> log.info("بدأ الزحف")
        >>> log.error("فشل الطلب: %s", url)
    """
    # إذا كان موجوداً، أعِده بدون إنشاء جديد
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # تجنّب تكرار الـ handlers
    if logger.handlers:
        return logger

    should_write_file = _file_output_enabled if file_output is None else file_output
    if should_write_file:
        _add_file_handler(logger, log_dir)

    # === Console Handler (مع ألوان) ===
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(
            ColoredFormatter(
                "%(asctime)s | %(levelname)-8s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logger.addHandler(console_handler)

    # حفظ في القاموس للاسترجاع السريع
    _loggers[name] = logger

    return logger


def configure_logging(
    level: str = "INFO",
    log_dir: str = "./logs",
    console_output: bool = True,
    file_output: bool = True,
) -> None:
    """Apply runtime logging config without creating log files at import time."""
    global _file_output_enabled, _default_log_dir
    _file_output_enabled = file_output
    _default_log_dir = log_dir

    log_level = getattr(logging, level.upper(), logging.INFO)
    for logger in _loggers.values():
        logger.setLevel(log_level)
        _ensure_console_handler(logger, console_output)
        if file_output:
            _add_file_handler(logger, log_dir)


def set_global_level(level: str) -> None:
    """تغيير مستوى السجل لكل الـ Loggers الموجودة."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    for logger in _loggers.values():
        logger.setLevel(log_level)


def _ensure_console_handler(logger: logging.Logger, console_output: bool) -> None:
    has_console = any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
                      for h in logger.handlers)
    if console_output and not has_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(
            ColoredFormatter(
                "%(asctime)s | %(levelname)-8s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logger.addHandler(console_handler)


def _add_file_handler(logger: logging.Logger, log_dir: str | None = None) -> None:
    if any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        return

    log_path = Path(log_dir or _default_log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d")
    log_file = log_path / f"crawler_{timestamp}.log"

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(name)s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(file_handler)
