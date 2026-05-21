"""
analyzers/images_analyzer.py
=============================
تحليل الصور لكشف مشاكل SEO والأداء.
"""

from collections import Counter
from typing import Any


def analyze_images(all_images: list[dict[str, Any]]) -> dict[str, Any]:
    """
    تحليل كل الصور المُكتشفة.

    يكشف:
    - صور بدون alt
    - alt مكرر
    - alt طويل جداً
    - صور بدون width/height (يسبب CLS)
    - صور بصيغ قديمة
    - صور كبيرة (يحتاج معلومات حجم)

    Returns:
        dict: تقرير شامل
    """
    # === Counters ===
    no_alt = []
    empty_alt_intentional = []  # alt="" مقصود (للصور الزخرفية)
    long_alt = []  # > 125 حرف
    duplicate_alt: dict[str, list[str]] = {}
    no_dimensions = []
    legacy_formats = []  # JPG/PNG بدلاً من WebP
    not_lazy_loaded = []
    no_srcset = []

    # تجميع alt للكشف عن التكرار
    alt_to_images: dict[str, list[dict]] = {}

    for img in all_images:
        page_url = img.get("page_url", "")
        src = img.get("src", "")
        alt = img.get("alt", "")
        has_alt = img.get("has_alt", False)
        alt_is_empty = img.get("alt_is_empty", False)

        img_entry = {
            "page_url": page_url,
            "src": src,
            "alt": alt,
            "extension": img.get("file_extension", ""),
        }

        # alt مفقود (بدون attribute)
        if not has_alt:
            no_alt.append(img_entry)

        # alt="" مقصود (صور زخرفية)
        elif alt_is_empty:
            empty_alt_intentional.append(img_entry)

        # alt طويل
        elif len(alt) > 125:
            long_alt.append({**img_entry, "alt_length": len(alt)})

        # تجميع alt للتكرار
        if alt and len(alt) > 3:  # نتجاهل alt قصير جداً
            alt_to_images.setdefault(alt.lower(), []).append(img_entry)

        # بدون أبعاد صريحة
        if not img.get("has_explicit_dimensions"):
            no_dimensions.append(img_entry)

        # صيغة قديمة
        ext = img.get("file_extension", "").lower()
        if ext in {"jpg", "jpeg", "png", "gif"}:
            legacy_formats.append({**img_entry, "current_format": ext})

        # بدون lazy loading
        if not img.get("is_lazy_loaded"):
            not_lazy_loaded.append(img_entry)

        # بدون srcset (مهم للـ responsive)
        if not img.get("srcset"):
            no_srcset.append(img_entry)

    # === كشف التكرارات في alt ===
    duplicate_alt = {
        alt: imgs for alt, imgs in alt_to_images.items() if len(imgs) > 1
    }

    # === إحصائيات ===
    total_images = len(all_images)

    return {
        "total_images": total_images,
        "no_alt_count": len(no_alt),
        "no_alt": no_alt[:100],  # نُقيِّد لـ 100 للـ output
        "empty_alt_intentional_count": len(empty_alt_intentional),
        "long_alt_count": len(long_alt),
        "long_alt": long_alt,
        "duplicate_alt_count": len(duplicate_alt),
        "duplicate_alt_groups": [
            {"alt": alt, "count": len(imgs), "examples": imgs[:5]}
            for alt, imgs in list(duplicate_alt.items())[:50]
        ],
        "no_dimensions_count": len(no_dimensions),
        "no_dimensions": no_dimensions[:100],
        "legacy_formats_count": len(legacy_formats),
        "legacy_formats_examples": legacy_formats[:50],
        "not_lazy_loaded_count": len(not_lazy_loaded),
        "no_srcset_count": len(no_srcset),
        # نسب
        "no_alt_percentage": round(
            len(no_alt) / total_images * 100 if total_images > 0 else 0, 2
        ),
        "no_dimensions_percentage": round(
            len(no_dimensions) / total_images * 100 if total_images > 0 else 0, 2
        ),
        # توزيع الامتدادات
        "extensions_distribution": dict(
            Counter(img.get("file_extension", "unknown") for img in all_images)
        ),
    }
