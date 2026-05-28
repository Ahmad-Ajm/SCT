"""
config_presets.py
=================
قوالب جاهزة لمنصّات التجارة الإلكترونية الشائعة (IMP-11): زد (Zid)، سلة (Salla)،
Shopify، WooCommerce. تكشف المنصّة من HTML/الترويسات وتطبّق إعدادات موصى بها
(استبعاد صفحات السلّة/الدفع/الحساب التي لا قيمة لها في فهرسة البحث).

دالّة الكشف نقية وقابلة للاختبار. التطبيق يدمج أنماط الاستبعاد في `filters.exclude_patterns`
دون مسح ما يضعه المستخدم.
"""

from __future__ import annotations

from typing import Any

# أنماط استبعاد موصى بها لكل منصّة (صفحات تفاعلية لا تُفهرَس عادةً)
PRESETS: dict[str, dict[str, Any]] = {
    "zid": {
        "label": "Zid",
        "exclude_patterns": ["*/cart*", "*/checkout*", "*/account*", "*add-to-cart*"],
        "note": "منصّة زد — استبعاد السلّة/الدفع/الحساب.",
    },
    "salla": {
        "label": "Salla",
        "exclude_patterns": ["*/cart*", "*/checkout*", "*/profile*", "*/login*", "*add-to-cart*"],
        "note": "منصّة سلة — استبعاد السلّة/الدفع/الملف الشخصي.",
    },
    "shopify": {
        "label": "Shopify",
        "exclude_patterns": ["*/cart*", "*/checkout*", "*/account*", "*/collections/*/products.json", "*add-to-cart*"],
        "note": "Shopify — استبعاد السلّة/الدفع/الحساب ونقاط JSON.",
    },
    "woocommerce": {
        "label": "WooCommerce",
        "exclude_patterns": ["*/cart*", "*/checkout*", "*/my-account*", "*add-to-cart*", "*/wp-admin*"],
        "note": "WooCommerce — استبعاد السلّة/الدفع/الحساب/الإدارة.",
    },
}

# توقيعات الكشف: (المنصّة, قائمة كلمات تظهر في HTML أو قيم الترويسات)
_SIGNATURES: list[tuple[str, tuple[str, ...]]] = [
    ("shopify", ("cdn.shopify.com", "myshopify.com", "shopify", "x-shopid", "x-shopify")),
    ("salla", ("salla.sa", "cdn.salla", "s-cdn.net", "salla")),
    ("zid", ("zid.store", "cdn.zid", "x-zid", "zidapi", "zid")),
    ("woocommerce", ("woocommerce", "wp-content/plugins/woocommerce", "wc-ajax", "wc_")),
]


def detect_platform(html: str = "", headers: dict[str, Any] | None = None) -> str:
    """يكشف منصّة التجارة من HTML/الترويسات. يعيد المعرّف أو "unknown"."""
    hay = (html or "").lower()
    if headers:
        for k, v in headers.items():
            hay += f" {str(k).lower()}:{str(v).lower()}"
    for platform, needles in _SIGNATURES:
        if any(n in hay for n in needles):
            return platform
    return "unknown"


def apply_preset(config: dict[str, Any], name: str) -> dict[str, Any]:
    """يدمج قالب المنصّة في الإعداد (يضيف أنماط الاستبعاد دون مسح القائمة الحالية).

    name: معرّف منصّة معروف (zid/salla/shopify/woocommerce). غير المعروف يُتجاهَل بأمان.
    """
    preset = PRESETS.get((name or "").lower())
    if not preset:
        return config
    filters = config.setdefault("filters", {})
    existing = list(filters.get("exclude_patterns", []) or [])
    for pat in preset["exclude_patterns"]:
        if pat not in existing:
            existing.append(pat)
    filters["exclude_patterns"] = existing
    config.setdefault("site", {})["platform_preset_applied"] = preset["label"]
    return config
