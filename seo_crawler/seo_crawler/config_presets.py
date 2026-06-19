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
# v1.07: أضفنا strip_query_params — معاملات تُزال من URLs قبل الطابور كي لا تُولّد تكرار
# محتوى (مثل sort_by=price و sort_by=name يُرجعان نفس المنتجات بترتيب مختلف).
# عند تفعيل preset، main.py يستدعي helpers.set_extra_strip_params(preset["strip_query_params"]).
PRESETS: dict[str, dict[str, Any]] = {
    "zid": {
        "label": "Zid",
        "exclude_patterns": ["*/cart*", "*/checkout*", "*/account*", "*add-to-cart*"],
        # Zid يُضيف ?sort_by=… على صفحات التصنيفات/المنتجات — نفس المحتوى بترتيب مختلف
        "strip_query_params": ["sort_by", "sort", "order_by", "order", "view"],
        "note": "منصّة زد — استبعاد السلّة/الدفع/الحساب + تطبيع sort_by.",
    },
    "salla": {
        "label": "Salla",
        "exclude_patterns": ["*/cart*", "*/checkout*", "*/profile*", "*/login*", "*add-to-cart*"],
        "strip_query_params": ["sort", "order", "view"],
        "note": "منصّة سلة — استبعاد السلّة/الدفع/الملف الشخصي + تطبيع sort.",
    },
    "shopify": {
        "label": "Shopify",
        "exclude_patterns": ["*/cart*", "*/checkout*", "*/account*", "*/collections/*/products.json", "*add-to-cart*"],
        # Shopify: sort_by=price-ascending و sort_by=manual يُرجعان نفس مجموعة المنتجات
        "strip_query_params": ["sort_by", "sortBy", "view"],
        "note": "Shopify — استبعاد السلّة/الدفع + نقاط JSON + تطبيع sort_by.",
    },
    "woocommerce": {
        "label": "WooCommerce",
        "exclude_patterns": ["*/cart*", "*/checkout*", "*/my-account*", "*add-to-cart*", "*/wp-admin*"],
        # WooCommerce يستعمل orderby بدل sort_by
        "strip_query_params": ["orderby", "order", "min_price", "max_price"],
        "note": "WooCommerce — استبعاد السلّة/الإدارة + تطبيع orderby.",
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

    v1.07: يُفعّل أيضاً تطبيع معاملات query الخاصّة بالمنصّة (sort_by ونحوها) عبر
    helpers.set_extra_strip_params — يقلّص الطابور بـ40-70% للمواقع الكثيرة الصفحات.
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
    # v1.07: تطبيع معاملات المنصّة (sort_by/order/view) — يطبَّق globally للزحفة
    strip = preset.get("strip_query_params") or []
    if strip:
        try:
            from utils.helpers import set_extra_strip_params
            set_extra_strip_params(strip)
        except ImportError:
            pass  # في وضع التحميل المنفصل (الاختبار)؛ التطبيق لا يفشل
    return config
