"""
analyzers/near_duplicate.py
===========================
كشف التشابه التقريبي بين الصفحات (Near‑Duplicate) عبر بصمة SimHash المخزّنة لكل صفحة.

بخلاف «المحتوى المكرّر تماماً» (hash متطابق)، يكشف هذا المحلّل الصفحات المتشابهة جداً
وليست متطابقة (مثل صفحات منتجات بقوالب متطابقة ومحتوى ضئيل الاختلاف) — وهي مشكلة شائعة
في المتاجر تُضعف التميّز في البحث.

الكفاءة: نستخدم تجزئة LSH (تقسيم البصمة 64-بت إلى نطاقات) لتجميع المرشّحين بدل مقارنة
كل زوج (O(n²))، ثم نتحقّق بمسافة Hamming ضمن المجموعات فقط.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from utils.helpers import hamming_distance


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def detect_near_duplicates(
    pages: list[Any],
    max_distance: int = 3,
    bands: int = 4,
    bits: int = 64,
) -> dict[str, Any]:
    """يجد أزواج/مجموعات الصفحات المتشابهة تقريبياً.

    Args:
        max_distance: أقصى مسافة Hamming لاعتبار صفحتين متشابهتين (3 ≈ تشابه عالٍ جداً).
        bands: عدد نطاقات LSH (يجب أن يقسم bits). 4 نطاقات × 16 بت.
    """
    items: list[tuple[str, int]] = []
    for p in pages:
        sh = _get(p, "content_simhash", "") or ""
        url = _get(p, "url", "")
        if not url or not str(sh).strip():
            continue
        try:
            items.append((url, int(sh)))
        except (TypeError, ValueError):
            continue

    if len(items) < 2:
        return {"pairs": [], "pairs_count": 0, "pages_involved": 0,
                "summary": {"checked": len(items)}}

    # ضمان صحّة LSH: ضمان المرشّحين عبر النطاقات يصحّ فقط عندما bands > max_distance
    # (حمامة الأبراج: زوجان ضمن مسافة d لا بدّ أن يتطابقا في نطاق واحد على الأقل إذا
    # كان عدد النطاقات أكبر من d). كما يجب أن يقسم bands عددَ البِتّات بالتساوي.
    # نصحّح القيم تلقائياً بدل المخاطرة بفقدان أزواج متشابهة.
    if bands <= max_distance:
        # أصغر عدد نطاقات صالح: > max_distance ويقسم bits
        for cand in range(max_distance + 1, bits + 1):
            if bits % cand == 0:
                bands = cand
                break
    elif bits % bands != 0:
        for cand in range(bands, bits + 1):
            if bits % cand == 0:
                bands = cand
                break
    assert bits % bands == 0, f"bits ({bits}) must be divisible by bands ({bands})"

    band_size = bits // bands
    band_mask = (1 << band_size) - 1
    # مجموعات حسب قيمة كل نطاق — المرشّحون يتشاركون نطاقاً واحداً على الأقل
    buckets: list[dict[int, list[int]]] = [defaultdict(list) for _ in range(bands)]
    for idx, (_url, sh) in enumerate(items):
        for b in range(bands):
            key = (sh >> (b * band_size)) & band_mask
            buckets[b][key].append(idx)

    seen_pairs: set[tuple[int, int]] = set()
    pairs: list[dict[str, Any]] = []
    for band in buckets:
        for bucket in band.values():
            if len(bucket) < 2:
                continue
            for i in range(len(bucket)):
                for j in range(i + 1, len(bucket)):
                    a, b = bucket[i], bucket[j]
                    pair = (a, b) if a < b else (b, a)
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    dist = hamming_distance(items[a][1], items[b][1])
                    if dist <= max_distance:
                        similarity = round((bits - dist) / bits * 100, 1)
                        pairs.append({
                            "url_a": items[pair[0]][0],
                            "url_b": items[pair[1]][0],
                            "hamming_distance": dist,
                            "similarity_pct": similarity,
                        })

    pairs.sort(key=lambda x: -x["similarity_pct"])
    involved = {p["url_a"] for p in pairs} | {p["url_b"] for p in pairs}
    return {
        "pairs": pairs,
        "pairs_count": len(pairs),
        "pages_involved": len(involved),
        "summary": {
            "checked": len(items),
            "near_duplicate_pairs": len(pairs),
            "pages_involved": len(involved),
            "max_distance": max_distance,
        },
    }
