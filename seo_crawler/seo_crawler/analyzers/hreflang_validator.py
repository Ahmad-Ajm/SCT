"""
analyzers/hreflang_validator.py
=================================
التحقق من صحة تطبيق Hreflang للمواقع متعددة اللغات.

يكشف:
1. Hreflang غير متبادل (A يشير لـ B، لكن B لا يشير لـ A) — شائع جداً!
2. x-default مفقود
3. Hreflang يشير لصفحات 404
4. Hreflang يشير لصفحات NoIndex
5. اللغة المُعلَنة في hreflang لا تطابق lang attribute
6. تنسيق غير صحيح (يجب: ar-SA, en-US, etc.)
7. تكرار اللغات في نفس الصفحة
8. self-reference مفقود

مرجع: https://developers.google.com/search/docs/specialty/international/localized-versions
"""

import re
from typing import Any

from utils.helpers import normalize_url


# تنسيقات صحيحة لـ hreflang بعد التطبيع.
# نقبل الإدخال case-insensitive مثل ar-sa ونطبّعه إلى ar-SA قبل الحكم.
# v1.13.26 (L1-hreflang-format): نسمح بـsubtag سكربت اختياري (4 أحرف Title-case
# مثل Hant) وإقليم UN M.49 (3 أرقام مثل 419/001) إضافةً للإقليم ثنائي الأحرف،
# حتى لا نرفض قيم Google الصحيحة zh-Hant, zh-Hant-HK, es-419, en-001.
HREFLANG_PATTERN = re.compile(
    r"^(?:x-default|[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))?)$"
)


def _attr(obj, name, default=None):
    """جلب attribute من dict أو dataclass."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _normalize_hreflang(value: str) -> str:
    """تطبيع hreflang بدون خلق false positives بسبب حالة الأحرف."""
    value = (value or "").strip()
    if value.lower() == "x-default":
        return "x-default"
    if "-" not in value:
        return value.lower()
    # v1.13.26 (L1-hreflang-format): طبّع كل subtag حسب نوعه — اللغة lowercase،
    # subtag السكربت (4 أحرف) Title-case (Hant لا HANT)، الإقليم (حرفان) uppercase،
    # وإقليم M.49 (3 أرقام) يبقى كما هو (upper لا يؤثّر على الأرقام).
    parts = value.split("-")
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            normalized.append(part.capitalize())
        else:
            normalized.append(part.upper())
    return "-".join(normalized)


def validate_hreflang(pages: list[Any]) -> dict[str, Any]:
    """
    تحقق شامل من تطبيق hreflang.

    Args:
        pages: قائمة الصفحات المزحوفة

    Returns:
        dict مع كل المشاكل المكتشفة
    """
    # بناء خريطة شاملة: URL → hreflang_tags
    pages_with_hreflang: dict[str, list[dict]] = {}
    page_data_map: dict[str, Any] = {}

    for page in pages:
        url = _attr(page, "url", "")
        if not url:
            continue

        normalized_url = normalize_url(url)
        page_data_map[normalized_url] = page

        hreflang_tags = _attr(page, "hreflang_tags", []) or []
        if hreflang_tags:
            pages_with_hreflang[normalized_url] = hreflang_tags

    if not pages_with_hreflang:
        return {
            "total_pages_with_hreflang": 0,
            "errors": [],
            "warnings": [],
            "summary": {
                "no_hreflang_implementation": True,
            },
        }

    # === فحوصات ===
    invalid_format = []
    missing_x_default = []
    missing_self_reference = []
    non_reciprocal = []  # ⭐ أهم مشكلة في hreflang
    duplicated_languages = []
    points_to_404 = []
    points_to_noindex = []
    lang_mismatch = []

    for source_url, tags in pages_with_hreflang.items():
        seen_langs = set()
        has_x_default = False
        has_self_reference = False

        for tag in tags:
            raw_hreflang_code = tag.get("hreflang", "")
            hreflang_code = _normalize_hreflang(raw_hreflang_code)
            href = tag.get("href", "")

            # 1. تنسيق
            if not HREFLANG_PATTERN.match(hreflang_code):
                invalid_format.append({
                    "page_url": source_url,
                    "hreflang_value": raw_hreflang_code,
                    "issue": "Invalid format - يجب: lang أو lang-REGION (e.g., ar, ar-SA)",
                })

            # 2. تكرار
            if hreflang_code.lower() in seen_langs:
                duplicated_languages.append({
                    "page_url": source_url,
                    "duplicated_lang": hreflang_code,
                })
            seen_langs.add(hreflang_code.lower())

            # 3. x-default
            if hreflang_code.lower() == "x-default":
                has_x_default = True

            # 4. Self-reference
            normalized_href = normalize_url(href)
            if normalized_href == source_url:
                has_self_reference = True

            # 5. التحقق من الصفحات المُشار إليها
            target_page = page_data_map.get(normalized_href)
            if target_page:
                # v1.09-B2: تحويل آمن
                from analyzers._coerce import status_of
                target_status = status_of(target_page)
                target_robots = _attr(target_page, "meta_robots", "") or ""
                target_x_robots = _attr(target_page, "x_robots_tag", "") or ""

                # 404
                if 400 <= target_status < 500:
                    points_to_404.append({
                        "page_url": source_url,
                        "hreflang_value": hreflang_code,
                        "target_url": href,
                        "target_status": target_status,
                    })

                # NoIndex
                combined = (target_robots + " " + target_x_robots).lower()
                if "noindex" in combined:
                    points_to_noindex.append({
                        "page_url": source_url,
                        "hreflang_value": hreflang_code,
                        "target_url": href,
                    })

                # Lang mismatch
                target_lang = (_attr(target_page, "language", "") or "").lower()
                declared_lang = tag.get("language_code", "").lower()
                if target_lang and declared_lang and target_lang not in (
                    "unknown", "mixed", ""
                ) and target_lang != declared_lang:
                    lang_mismatch.append({
                        "page_url": source_url,
                        "hreflang_value": hreflang_code,
                        "target_url": href,
                        "detected_language": target_lang,
                        "declared_language": declared_lang,
                    })

            # 6. Reciprocity check ⭐
            # إذا href موجود في صفحاتنا، يجب أن يُشير back إلينا
            if normalized_href != source_url and normalized_href in pages_with_hreflang:
                target_tags = pages_with_hreflang[normalized_href]
                reciprocal_found = False
                for t in target_tags:
                    target_href_normalized = normalize_url(t.get("href", ""))
                    if target_href_normalized == source_url:
                        reciprocal_found = True
                        break

                if not reciprocal_found:
                    non_reciprocal.append({
                        "page_url": source_url,
                        "hreflang_value": hreflang_code,
                        "target_url": href,
                        "issue": f"{href} لا يحتوي على hreflang يشير لـ {source_url}",
                    })
            # v1.13.26 (L1-hreflang-reciprocity): الحالة الأشيع — الهدف مزحوف لكنه
            # لا يُصدر أيّ hreflang عائد إطلاقاً، فكان يُتخطّى بصمت لأنه غائب عن
            # pages_with_hreflang. نفحصه مقابل مجموعة الزحف الكاملة (page_data_map).
            elif (normalized_href != source_url
                  and normalized_href in page_data_map):
                non_reciprocal.append({
                    "page_url": source_url,
                    "hreflang_value": hreflang_code,
                    "target_url": href,
                    "issue": f"{href} مزحوفة لكنها لا تُصدر أيّ hreflang يشير لـ {source_url}",
                })

        # 3. x-default check
        if not has_x_default:
            missing_x_default.append({
                "page_url": source_url,
                "tags_count": len(tags),
            })

        # 4. Self-reference check
        if not has_self_reference:
            missing_self_reference.append({
                "page_url": source_url,
                "tags_count": len(tags),
            })

    return {
        "total_pages_with_hreflang": len(pages_with_hreflang),

        # 🔴 أخطاء حرجة
        "non_reciprocal": non_reciprocal,
        "non_reciprocal_count": len(non_reciprocal),
        "points_to_404": points_to_404,
        "points_to_404_count": len(points_to_404),
        "points_to_noindex": points_to_noindex,
        "points_to_noindex_count": len(points_to_noindex),
        "invalid_format": invalid_format,
        "invalid_format_count": len(invalid_format),

        # 🟠 مهم
        "missing_self_reference": missing_self_reference,
        "missing_self_reference_count": len(missing_self_reference),
        "missing_x_default": missing_x_default,
        "missing_x_default_count": len(missing_x_default),
        "duplicated_languages": duplicated_languages,
        "duplicated_languages_count": len(duplicated_languages),

        # 🟡 تحذيرات
        "lang_mismatch": lang_mismatch,
        "lang_mismatch_count": len(lang_mismatch),

        "summary": {
            "total_pages_with_hreflang": len(pages_with_hreflang),
            "critical_errors": (
                len(non_reciprocal) + len(points_to_404) +
                len(invalid_format)
            ),
            "warnings": (
                len(missing_x_default) + len(missing_self_reference) +
                len(duplicated_languages) + len(lang_mismatch)
            ),
        },
    }
