"""
exporters/xml_exporter.py
=========================
تصدير أهم بيانات التدقيق إلى ملفات XML منفصلة.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable
from xml.etree.ElementTree import Element, ElementTree, SubElement

from utils.logger import get_logger
from utils.monitoring import increment, span

log = get_logger(__name__)


class XMLExporter:
    """مصدّر XML خفيف لبيانات SCT الأساسية."""

    # سقف أمان صلب لكل ملف XML — حتى لو مرّر المتّصل بيانات غير مقصوصة
    # (مثل seo_issues) لا يتضخّم الملف إلى غيغابايت ويُجمّد الذاكرة. 0 = بلا حد.
    DEFAULT_MAX_ROWS = 200000

    def __init__(self, output_dir: str, max_rows: int | None = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_rows = self.DEFAULT_MAX_ROWS if max_rows is None else int(max_rows)

    def export_all(
        self,
        pages: list[Any],
        links: list[dict[str, Any]],
        images: list[dict[str, Any]],
        schema: list[dict[str, Any]],
        seo_issues: dict[str, Any],
    ) -> dict[str, str]:
        with span("xml.export_all", output_dir=str(self.output_dir)):
            exported = {
                "pages": self._export("pages.xml", "pages", "page", pages),
                "links": self._export("links.xml", "links", "link", links),
                "images": self._export("images.xml", "images", "image", images),
                "schema": self._export("schema.xml", "schema_entries", "schema", schema),
                "seo_issues": self._export(
                    "seo_issues.xml",
                    "seo_issues",
                    "issue",
                    seo_issues.get("all_issues", []) if isinstance(seo_issues, dict) else [],
                ),
            }
            increment("xml.files_exported", len(exported))
            log.info("تم تصدير %d ملف XML إلى %s", len(exported), self.output_dir)
            return exported

    def _export(
        self,
        filename: str,
        root_name: str,
        row_name: str,
        rows: Iterable[Any],
    ) -> str:
        path = self.output_dir / filename
        normalized_rows = [self._to_dict(row) for row in rows]
        if self.max_rows and len(normalized_rows) > self.max_rows:
            log.warning(
                "XML %s: %d صف يتجاوز سقف الأمان %d — يُقتصَر",
                filename, len(normalized_rows), self.max_rows,
            )
            normalized_rows = normalized_rows[: self.max_rows]
        with span("xml.export_file", filename=filename, rows=len(normalized_rows)):
            root = Element(root_name)
            root.set("count", str(len(normalized_rows)))
            for row in normalized_rows:
                node = SubElement(root, row_name)
                for key, value in row.items():
                    child = SubElement(node, self._safe_tag(key))
                    child.text = self._value(value)
            ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
            increment("xml.rows_exported", len(normalized_rows))
            return str(path)

    def _to_dict(self, obj: Any) -> dict[str, Any]:
        if is_dataclass(obj):
            return asdict(obj)
        if isinstance(obj, dict):
            return obj
        return {"value": str(obj)}

    def _value(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, dict, tuple, set)):
            return json.dumps(value, ensure_ascii=False, default=str)
        return str(value)

    def _safe_tag(self, key: Any) -> str:
        text = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in str(key))
        if not text or not (text[0].isalpha() or text[0] == "_"):
            text = f"field_{text}"
        return text
