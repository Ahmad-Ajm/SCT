"""
extractors/content_extractor.py
================================
استخراج وتحليل محتوى الصفحة النصي.
"""

import re
from typing import Any
from bs4 import BeautifulSoup, Comment

from utils.helpers import compute_simhash, compute_text_hash


# === Tags التي تُحذف من الحساب (محتوى غير مرئي) ===
EXCLUDED_TAGS = {"script", "style", "noscript", "iframe", "head", "meta", "link"}


def extract_content(soup: BeautifulSoup, html_size_bytes: int = 0) -> dict[str, Any]:
    """
    استخراج وتحليل المحتوى النصي.

    Args:
        soup: BeautifulSoup
        html_size_bytes: حجم HTML بالـ bytes (لحساب text-to-html ratio)

    Returns:
        dict: {
            "word_count": int,
            "character_count": int,
            "paragraph_count": int,
            "sentence_count": int,
            "text_to_html_ratio": float,
            "language": str,
            "content_hash": str,
            "main_text": str (مقتطف),
            "has_arabic": bool,
            "has_english": bool,
            "estimated_reading_time_minutes": int,
        }
    """
    # === نسخة للتنظيف بدون تغيير الأصل ===
    soup_copy = BeautifulSoup(str(soup), "lxml")

    # === إزالة العناصر غير المرئية ===
    for tag_name in EXCLUDED_TAGS:
        for tag in soup_copy.find_all(tag_name):
            tag.decompose()

    # === إزالة HTML comments ===
    for comment in soup_copy.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # === استخراج النص ===
    text = soup_copy.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()

    # === حساب الكلمات (يدعم العربية والإنجليزية) ===
    # نقسّم على whitespace بعد إزالة علامات الترقيم
    words_text = re.sub(r"[^\w\s\u0600-\u06FF]", " ", text)
    words = [w for w in words_text.split() if w]
    word_count = len(words)

    # === حساب الفقرات ===
    paragraphs = soup.find_all("p")
    paragraph_count = sum(1 for p in paragraphs if p.get_text(strip=True))

    # === حساب الجمل (تقريبي) ===
    # نعد علامات الترقيم الإنجليزية والعربية
    sentence_endings = re.findall(r"[.!?؟،]", text)
    sentence_count = len(sentence_endings)

    # === Language detection (بسيط) ===
    arabic_chars = len(re.findall(r"[\u0600-\u06FF]", text))
    english_chars = len(re.findall(r"[a-zA-Z]", text))
    total_lang_chars = arabic_chars + english_chars

    has_arabic = arabic_chars > 0
    has_english = english_chars > 0

    if total_lang_chars == 0:
        language = "unknown"
    elif arabic_chars / total_lang_chars > 0.7:
        language = "ar"
    elif english_chars / total_lang_chars > 0.7:
        language = "en"
    else:
        language = "mixed"

    # محاولة من html lang attribute
    html_tag = soup.find("html")
    declared_lang = html_tag.get("lang", "") if html_tag else ""

    # === Text-to-HTML ratio ===
    text_size = len(text.encode("utf-8"))
    text_to_html_ratio = (text_size / html_size_bytes * 100) if html_size_bytes > 0 else 0.0

    # === Content hash (تكرار تام) + SimHash (تشابه تقريبي) ===
    content_hash = compute_text_hash(text)
    # بصمة SimHash من «شينغلات» الكلمات (3-grams) لكشف التشابه التقريبي بين الصفحات
    if len(words) >= 3:
        shingles = [" ".join(words[i:i + 3]) for i in range(len(words) - 2)]
    else:
        shingles = words
    content_simhash = str(compute_simhash(shingles))

    # === Reading time (تقدير: 200 كلمة/دقيقة) ===
    reading_time = max(1, round(word_count / 200))

    return {
        "word_count": word_count,
        "character_count": len(text),
        "paragraph_count": paragraph_count,
        "sentence_count": sentence_count,
        "text_to_html_ratio": round(text_to_html_ratio, 2),
        "language": language,
        "declared_language": declared_lang,
        "content_hash": content_hash,
        "content_simhash": content_simhash,
        "main_text_preview": text[:500],
        "has_arabic": has_arabic,
        "has_english": has_english,
        "arabic_percentage": round(
            arabic_chars / total_lang_chars * 100 if total_lang_chars > 0 else 0, 2
        ),
        "estimated_reading_time_minutes": reading_time,
    }
