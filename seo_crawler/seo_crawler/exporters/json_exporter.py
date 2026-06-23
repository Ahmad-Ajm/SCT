"""
exporters/json_exporter.py
===========================
تصدير كل البيانات كـ JSON واحد للأرشفة والمقارنة لاحقاً.
"""

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.logger import get_logger

log = get_logger(__name__)


class JSONExporter:
    """مصدّر JSON كامل."""

    def __init__(self, output_dir: str, filename: str = "complete_audit.json"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.file_path = self.output_dir / filename

    def export(self, **datasets: Any) -> str:
        """
        تصدير كل البيانات كـ JSON واحد.

        Args:
            **datasets: keyword arguments تحتوي البيانات
                مثل: pages=..., links=..., issues=..., etc.

        Returns:
            str: مسار الملف
        """
        # تحويل dataclasses إلى dicts
        serializable = {
            "_meta": {
                "generated_at": datetime.now().isoformat(),
                "version": "1.13.5",
                "author": "Ahmad-Ajm",
            }
        }

        for name, data in datasets.items():
            serializable[name] = self._make_serializable(data)

        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(serializable, f, ensure_ascii=False, indent=2, default=str)

            log.info(f"تم حفظ JSON: {self.file_path}")
            return str(self.file_path)

        except Exception as e:
            log.error(f"فشل تصدير JSON: {e}")
            return ""

    def _make_serializable(self, obj: Any) -> Any:
        """تحويل أي كائن إلى صيغة قابلة للـ JSON serialization."""
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        if is_dataclass(obj):
            return asdict(obj)
        if isinstance(obj, dict):
            return {k: self._make_serializable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)):
            return [self._make_serializable(item) for item in obj]
        # fallback - convert to string
        return str(obj)
