"""
extractors/headings_extractor.py
=================================
استخراج كل العناوين (H1 - H6) مع تحليل التسلسل.
"""

from typing import Any
from bs4 import BeautifulSoup


def extract_headings(soup: BeautifulSoup) -> dict[str, Any]:
    """
    استخراج كل العناوين من H1 إلى H6.

    Returns:
        dict: {
            "h1_count": int,
            "h1_text": list[str],
            "h2_count": int, ...
            "order": list[str],  # ['h1', 'h2', 'h2', 'h3'...]
            "detailed": list[dict],  # كل heading بـ tag + text + position
            "has_skipped_levels": bool,  # تخطّى مستوى (مثل h1 → h3)
        }
    """
    result: dict[str, Any] = {
        "h1_count": 0,
        "h1_text": [],
        "h2_count": 0,
        "h2_text": [],
        "h3_count": 0,
        "h3_text": [],
        "h4_count": 0,
        "h4_text": [],
        "h5_count": 0,
        "h5_text": [],
        "h6_count": 0,
        "h6_text": [],
        "order": [],
        "detailed": [],
        "has_skipped_levels": False,
    }

    # البحث عن كل العناوين بترتيبها في الصفحة
    all_headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])

    previous_level = 0
    for position, tag in enumerate(all_headings, start=1):
        level = int(tag.name[1])  # h1 → 1, h2 → 2, etc.
        text = tag.get_text(separator=" ", strip=True)

        # تخطّي العناوين الفارغة
        if not text:
            continue

        # تحديث counters
        count_key = f"h{level}_count"
        text_key = f"h{level}_text"
        result[count_key] += 1
        result[text_key].append(text)
        result["order"].append(f"h{level}")

        # حفظ تفصيلي
        result["detailed"].append(
            {
                "tag": f"h{level}",
                "level": level,
                "text": text,
                "length": len(text),
                "position": position,
            }
        )

        # التحقق من تخطّي المستويات (مثل h1 → h3 بدون h2)
        if previous_level > 0 and level > previous_level + 1:
            result["has_skipped_levels"] = True

        previous_level = level

    return result
