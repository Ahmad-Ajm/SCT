"""
utils/auto_install.py
=====================
تثبيت تلقائي للمتطلبات الاختيارية عند الحاجة (IMP-16).

عندما تحتاج الأداة مكتبة اختيارية غير مثبّتة، نُثبّتها تلقائياً (بإعلام المستخدم، دون طلب
موافقة) بدل أن تفشل الميزة بصمت. حدّ الأمان: يقتصر التثبيت على **قائمة معروفة مسبقاً
لمكتبات الأداة الاختيارية** (لا حزم عشوائية)، والتثبيت محلي عبر `pip` لنفس مفسّر بايثون.

الاستخدام:
    from utils.auto_install import ensure_package
    if ensure_package("openpyxl"):
        import openpyxl

التعطيل: ضع متغيّر البيئة SCT_NO_AUTO_INSTALL=1 (يبقى الاستيراد يُحاوَل، لكن بلا تثبيت).
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from typing import Callable, Optional

from utils.logger import get_logger

log = get_logger(__name__)

# قائمة بيضاء: اسم الاستيراد -> اسم حزمة pip. لا يُثبَّت أي شيء خارجها.
ALLOWLIST: dict[str, str] = {
    "openpyxl": "openpyxl",
    "spellchecker": "pyspellchecker",
    "playwright": "playwright",
    "lxml": "lxml",
    "bs4": "beautifulsoup4",
    "aiohttp": "aiohttp",
    "defusedxml": "defusedxml",
    "requests": "requests",
    "yaml": "PyYAML",
    "googleapiclient": "google-api-python-client",
    "google_auth_oauthlib": "google-auth-oauthlib",
    "google.oauth2": "google-auth",
    "google.analytics.data": "google-analytics-data",
}

# عمليات تثبيت تمّت في هذه الجلسة (لتفادي تكرار المحاولة)
_attempted: set[str] = set()


def is_auto_install_enabled() -> bool:
    return not os.environ.get("SCT_NO_AUTO_INSTALL")


def ensure_package(
    import_name: str,
    pip_name: Optional[str] = None,
    auto: Optional[bool] = None,
    notify: Optional[Callable[[str], None]] = None,
) -> bool:
    """يضمن توفّر مكتبة: يستوردها، وإن غابت يُثبّتها تلقائياً (إن سُمح).

    Returns:
        bool: True إن أصبحت المكتبة متاحة.
    """
    # 1) متاحة أصلاً؟
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        pass

    # 2) ضمن القائمة البيضاء؟ (أمان: لا حزم عشوائية)
    resolved_pip = pip_name or ALLOWLIST.get(import_name)
    if not resolved_pip:
        log.error(
            f"مكتبة مطلوبة غير مثبّتة وخارج قائمة التثبيت التلقائي: {import_name}"
        )
        return False

    enabled = is_auto_install_enabled() if auto is None else bool(auto)
    if not enabled:
        log.warning(
            f"مكتبة {import_name} غير مثبّتة والتثبيت التلقائي معطّل "
            f"(ثبّتها يدوياً: pip install {resolved_pip})"
        )
        return False

    if import_name in _attempted:
        return False
    _attempted.add(import_name)

    msg = f"يجري تثبيت {resolved_pip}…"
    log.info(msg)
    if notify:
        try:
            notify(msg)
        except Exception:  # noqa: BLE001
            pass

    # 3) تثبيت محلي لنفس المفسّر
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", resolved_pip],
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
    except (subprocess.CalledProcessError, OSError) as e:
        log.error(f"فشل تثبيت {resolved_pip}: {e}")
        return False

    importlib.invalidate_caches()
    try:
        importlib.import_module(import_name)
        log.info(f"تم تثبيت {resolved_pip} بنجاح")
        return True
    except ImportError:
        log.error(f"تعذّر استيراد {import_name} بعد التثبيت")
        return False
