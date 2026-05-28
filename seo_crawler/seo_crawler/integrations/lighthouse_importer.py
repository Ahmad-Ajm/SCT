"""
integrations/lighthouse_importer.py
===================================
استيراد نتائج Lighthouse/PageSpeed (ملفات JSON) — بدون أي مفاتيح أو إنترنت.

الفلسفة (راجع docs/EXTERNAL_TOOLS_GUIDE):
- لا نُعيد بناء محرك أداء؛ المستخدم يشغّل Lighthouse CLI أو PageSpeed محلياً،
  ثم يضع ملفات JSON في مجلد، ونقرأها لعرض الـ scores بجانب تقارير SCT.

الاستخدام: ضع ملفات Lighthouse JSON في مجلد (افتراضياً ./external_data/lighthouse)
ثم فعّل integrations.lighthouse في الإعدادات.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from utils.logger import get_logger

log = get_logger(__name__)

_CATEGORIES = ["performance", "accessibility", "best-practices", "seo", "pwa"]


class LighthouseImporter:
    def __init__(self, folder: str = "./external_data/lighthouse"):
        self.folder = Path(folder)

    def load(self) -> list[dict[str, Any]]:
        """قراءة كل ملفات Lighthouse JSON في المجلد وإرجاع صفوف ملخّص."""
        if not self.folder.exists():
            log.info(f"مجلد Lighthouse غير موجود: {self.folder} — تخطّي")
            return []

        rows: list[dict[str, Any]] = []
        for path in sorted(self.folder.glob("*.json")):
            row = self._parse_one(path)
            if row:
                rows.append(row)
        log.info(f"تم استيراد {len(rows)} تقرير Lighthouse من {self.folder}")
        return rows

    def _parse_one(self, path: Path) -> dict[str, Any] | None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"تعذّر قراءة {path.name}: {e}")
            return None

        # دعم تنسيق PageSpeed API (lighthouseResult متداخل) و Lighthouse CLI
        lh = data.get("lighthouseResult", data)
        cats = lh.get("categories", {}) or {}
        url = lh.get("finalUrl") or lh.get("requestedUrl") or data.get("id", path.stem)

        row: dict[str, Any] = {"url": url, "source_file": path.name,
                               "fetch_time": lh.get("fetchTime", "")}
        for cat in _CATEGORIES:
            score = (cats.get(cat) or {}).get("score")
            # Lighthouse score بين 0-1 → نحوّله إلى 0-100
            row[cat.replace("-", "_")] = round(score * 100) if isinstance(score, (int, float)) else None
        return row
