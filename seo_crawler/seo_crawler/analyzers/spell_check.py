"""
analyzers/spell_check.py
========================
تدقيق إملائي اختياري للعناوين والأوصاف وH1 — مطفأ افتراضياً.

ملاحظة عملية: التدقيق الإملائي يعتمد على قاموس للّغة. مكتبة `pyspellchecker`
الاختيارية تدعم الإنجليزية وعدّة لغات أوروبية، لكن **لا تدعم العربية**. لذلك على
المواقع العربية يقتصر التدقيق على الصفحات/الحقول الإنجليزية فقط، ويُرجع
المحلّل حالة واضحة عند عدم الدعم.

التفعيل: analysis.spell_check: true   (يتطلّب: pip install pyspellchecker)
"""

from __future__ import annotations

import re
from typing import Any


def _get(o: Any, k: str, d: Any = None) -> Any:
    return o.get(k, d) if isinstance(o, dict) else getattr(o, k, d)


# اللغات المدعومة في pyspellchecker (نُبقي القائمة محافِظة)
_SUPPORTED = {"en", "es", "fr", "pt", "de", "it", "ru", "nl"}


def _tokens(text: str) -> list[str]:
    """كلمات لاتينية فقط (نتجاهل الأرقام والرموز والحروف غير اللاتينية)."""
    if not text:
        return []
    return [t.lower() for t in re.findall(r"[A-Za-z]{3,}", text)]


def run_spell_check(pages: list[Any], max_pages: int = 0,
                    max_examples: int = 20) -> dict[str, Any]:
    """يفحص العنوان + الوصف + H1 لكل صفحة بلغة مدعومة.

    Returns:
        dict مع status, checked_pages, pages_with_issues, top_misspellings, examples.
    """
    try:
        from spellchecker import SpellChecker
    except ImportError:
        return {
            "status": "library_missing",
            "note": "ثبّت: pip install pyspellchecker لتفعيل التدقيق الإملائي.",
            "checked_pages": 0, "pages_with_issues": 0,
            "top_misspellings": [], "examples": [],
        }

    by_lang: dict[str, list[tuple[Any, str]]] = {}
    for p in pages:
        lang = (_get(p, "language", "") or "").lower()
        if lang not in _SUPPORTED:
            continue
        title = str(_get(p, "title", "") or "")
        desc = str(_get(p, "meta_description", "") or "")
        h1 = _get(p, "h1_text", []) or []
        if isinstance(h1, str):
            h1_text = h1
        else:
            h1_text = " ".join(h1) if isinstance(h1, list) else ""
        combined = " ".join([title, desc, h1_text]).strip()
        if combined:
            by_lang.setdefault(lang, []).append((p, combined))

    if not by_lang:
        return {
            "status": "no_supported_language_pages",
            "note": "لا توجد صفحات بلغة مدعومة (مثل الإنجليزية). للعربية يلزم قاموس "
                    "خارجي ليس مدمجاً مع المكتبة.",
            "checked_pages": 0, "pages_with_issues": 0,
            "top_misspellings": [], "examples": [],
        }

    misspellings_count: dict[str, int] = {}
    examples: list[dict[str, Any]] = []
    checked = 0
    pages_with_issues = 0

    for lang, items in by_lang.items():
        try:
            spell = SpellChecker(language=lang)
        except Exception:
            continue
        for page, text in items:
            if max_pages and checked >= max_pages:
                break
            words = set(_tokens(text))
            if not words:
                continue
            checked += 1
            unknown = spell.unknown(words)
            if not unknown:
                continue
            pages_with_issues += 1
            for w in unknown:
                misspellings_count[w] = misspellings_count.get(w, 0) + 1
            if len(examples) < max_examples:
                examples.append({
                    "url": _get(page, "url", ""),
                    "language": lang,
                    "suspected_misspellings": sorted(unknown)[:10],
                })

    top = sorted(misspellings_count.items(), key=lambda x: -x[1])[:30]
    return {
        "status": "ok",
        "checked_pages": checked,
        "pages_with_issues": pages_with_issues,
        "top_misspellings": [{"word": w, "count": c} for w, c in top],
        "examples": examples,
    }
