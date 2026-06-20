"""
utils/auto_install.py
=====================
تثبيت اختياري للمتطلبات الاختيارية عند الحاجة (IMP-16).

v1.12 DEP-12 — تغيير سياسة الافتراضي إلى **معطَّل**:
سابقاً كان التثبيت مفعّلاً افتراضياً (يقتصر على قائمة بيضاء معروفة). المراجعة الأمنيّة
رأت أنّ ذلك:
- يُبطل ضوابط الـpin في requirements.txt (يجلب الإصدار latest غير المُختبَر)
- ينشئ dev/prod skew (يفشل تحت Docker USER sct لعدم صلاحيّة الكتابة)
- يفتح ناقل supply-chain (إن اخترق مهاجم ميرور PyPI أو سجّل typosquat)

السلوك الجديد: التثبيت **معطَّل افتراضياً** ويُعاد رسالة خطأ واضحة تسمّي الحزمة.
لتفعيله صراحةً في بيئة تطوير: SCT_AUTO_INSTALL=1.

متغيّر SCT_NO_AUTO_INSTALL لا يزال مدعوماً للتوافق العكسي لكنّه الآن لا يفعل شيئاً
لأنّ التعطيل صار افتراضياً.

الاستخدام:
    from utils.auto_install import ensure_package
    if ensure_package("openpyxl"):
        import openpyxl
    # في حال غياب openpyxl: log.error واضح، ولن يُثبَّت إلا إذا ضُبط SCT_AUTO_INSTALL=1.
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
    """v1.12 DEP-12: opt-in via SCT_AUTO_INSTALL=1 (default: DISABLED).
    SCT_NO_AUTO_INSTALL لا يزال مفهوماً لكن لا أثر له لأنّ التعطيل صار افتراضياً."""
    return os.environ.get("SCT_AUTO_INSTALL", "").strip() in ("1", "true", "yes", "on")


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
        log.error(
            "مكتبة اختيارية مطلوبة غير مثبّتة: %s\n"
            "  للتثبيت يدوياً (موصى به):  pip install %s\n"
            "  أو لتفعيل التثبيت التلقائي في بيئة تطوير: SCT_AUTO_INSTALL=1",
            import_name, resolved_pip,
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
