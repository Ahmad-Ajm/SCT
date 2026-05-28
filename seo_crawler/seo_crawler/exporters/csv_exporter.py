"""
exporters/csv_exporter.py
==========================
تصدير كل البيانات كـ CSV files منفصلة.
"""

import csv
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable

from utils.helpers import neutralize_formula as _neutralize_formula
from utils.logger import get_logger
from utils.monitoring import increment, span

log = get_logger(__name__)


class CSVExporter:
    """
    مصدّر CSV.

    يُنشئ ملفات منفصلة لكل نوع بيانات:
    - pages.csv: الصفحات الكاملة
    - inlinks.csv / outlinks.csv: الروابط
    - images.csv: الصور
    - headings.csv: العناوين
    - schema.csv: Schema.org
    - redirects.csv: التحويلات
    - headers.csv: HTTP headers
    - seo_issues.csv: مشاكل SEO
    - duplicates.csv: التكرارات
    - orphans.csv: الصفحات اليتيمة
    """

    def __init__(self, output_dir: str, encoding: str = "utf-8-sig"):
        """
        Args:
            output_dir: المجلد للحفظ
            encoding: utf-8-sig يفتح بشكل صحيح في Excel
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.encoding = encoding

    def export_all(
        self,
        pages: list[Any],
        links: list[dict[str, Any]],
        images: list[dict[str, Any]],
        headings: list[dict[str, Any]],
        schema: list[dict[str, Any]],
        redirects: list[dict[str, Any]],
        headers: list[dict[str, Any]],
        seo_issues: dict[str, Any],
        duplicate_data: dict[str, Any],
        orphan_data: dict[str, Any],
        thin_content_data: dict[str, Any],
        broken_data: dict[str, Any],
        images_analysis: dict[str, Any],
        url_issues: dict[str, Any] | None = None,
        canonical_data: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """
        تصدير كل البيانات.

        Returns:
            dict: {dataset_name: file_path}
        """
        with span("csv.export_all", output_dir=str(self.output_dir)):
            exported: dict[str, str] = {}
            url_issues = url_issues or {}
            canonical_data = canonical_data or {}

            # === Pages ===
            pages_dicts = [self._to_dict(p) for p in pages]
            exported["pages"] = self._export("pages.csv", pages_dicts)

            # === Links - فصل internal/external ===
            internal_links = [l for l in links if l.get("is_internal")]
            external_links = [
                l for l in links
                if not l.get("is_internal") and not l.get("is_special_link")
            ]
            exported["inlinks"] = self._export("inlinks.csv", internal_links)
            exported["outlinks_external"] = self._export("outlinks_external.csv", external_links)
            exported["all_links"] = self._export("all_links.csv", links)

            # === Images ===
            exported["images"] = self._export("images.csv", images)

            # === Headings ===
            exported["headings"] = self._export("headings.csv", headings)

            # === Schema ===
            # نُسطّح Schema لأنه يحتوي على raw_data dict
            schema_flat = []
            for item in schema:
                schema_flat.append(
                    {
                        "page_url": item.get("page_url", ""),
                        "format": item.get("format", ""),
                        "type": item.get("type", ""),
                        "name": item.get("name", ""),
                        # raw_data كـ JSON string
                        "raw_data_preview": str(item.get("raw_data", ""))[:500],
                    }
                )
            exported["schema"] = self._export("schema.csv", schema_flat)

            # === Redirects ===
            exported["redirects"] = self._export("redirects.csv", redirects)

            # === Headers ===
            # حذف all_headers لأنه dict كبير
            headers_simplified = [
                {k: v for k, v in h.items() if k != "all_headers"} for h in headers
            ]
            exported["headers"] = self._export("headers.csv", headers_simplified)

            # === SEO Issues ===
            exported["seo_issues"] = self._export(
                "seo_issues.csv", seo_issues.get("all_issues", [])
            )

            # === Duplicates ===
            all_duplicates = []
            for d in duplicate_data.get("duplicate_titles", []):
                for url in d["urls"]:
                    all_duplicates.append(
                        {"type": "duplicate_title", "value": d["value"], "url": url, "count": d["count"]}
                    )
            for d in duplicate_data.get("duplicate_descriptions", []):
                for url in d["urls"]:
                    all_duplicates.append(
                        {"type": "duplicate_description", "value": d["value"], "url": url, "count": d["count"]}
                    )
            for d in duplicate_data.get("duplicate_h1", []):
                for url in d["urls"]:
                    all_duplicates.append(
                        {"type": "duplicate_h1", "value": d["value"], "url": url, "count": d["count"]}
                    )
            for d in duplicate_data.get("duplicate_content", []):
                for url in d["urls"]:
                    all_duplicates.append(
                        {"type": "duplicate_content", "value": d.get("hash", ""), "url": url, "count": d["count"]}
                    )
            exported["duplicates"] = self._export("duplicates.csv", all_duplicates)

            # === Orphan Pages ===
            exported["orphans"] = self._export(
                "orphans.csv", orphan_data.get("orphan_pages", [])
            )

            # === Low Link Pages ===
            exported["low_link_pages"] = self._export(
                "low_link_pages.csv", orphan_data.get("low_link_pages", [])
            )

            # === Thin Content ===
            thin_all = thin_content_data.get("thin_content_pages", []) + thin_content_data.get(
                "critical_thin_pages", []
            )
            exported["thin_content"] = self._export("thin_content.csv", thin_all)

            # === Broken Links ===
            exported["pages_4xx"] = self._export("pages_4xx.csv", broken_data.get("pages_4xx", []))
            exported["pages_5xx"] = self._export("pages_5xx.csv", broken_data.get("pages_5xx", []))
            exported["pages_404_with_inlinks"] = self._export(
                "pages_404_with_inlinks.csv", broken_data.get("pages_404_with_inlinks", [])
            )

            # === Image Issues ===
            # نُصدّر القائمة الكاملة من الصور الخام (المحلّل يقصّ لـ 100 للتقرير/JSON
            # فقط؛ ملف CSV يجب أن يكون كاملاً للعمل عليه).
            def _img_row(im: dict[str, Any]) -> dict[str, Any]:
                return {"page_url": im.get("page_url", ""), "src": im.get("src", ""),
                        "alt": im.get("alt", ""), "extension": im.get("file_extension", "")}

            no_alt_full = ([_img_row(im) for im in images if not im.get("has_alt")]
                           if images else images_analysis.get("no_alt", []))
            no_dim_full = ([_img_row(im) for im in images if not im.get("has_explicit_dimensions")]
                           if images else images_analysis.get("no_dimensions", []))
            exported["images_no_alt"] = self._export("images_no_alt.csv", no_alt_full)
            exported["images_no_dimensions"] = self._export(
                "images_no_dimensions.csv", no_dim_full)

            exported["url_issues"] = self._export(
                "url_issues.csv", self._flatten_issue_groups(url_issues)
            )
            exported["canonical_issues"] = self._export(
                "canonical_issues.csv", self._flatten_issue_groups(canonical_data)
            )

            increment("csv.files_exported", len(exported))
            log.info(f"تم تصدير {len(exported)} ملف CSV إلى {self.output_dir}")
            return exported

    def _export(self, filename: str, data: Iterable[dict[str, Any]]) -> str:
        """تصدير قائمة dicts إلى CSV."""
        file_path = self.output_dir / filename
        rows = list(data) if not isinstance(data, list) else data

        with span("csv.export_file", filename=filename, rows=len(rows)):
            if not rows:
                # ملف فارغ مع header افتراضي
                with open(file_path, "w", encoding=self.encoding) as f:
                    f.write("no_data\n")
                increment("csv.empty_files")
                return str(file_path)

            try:
                fieldnames = self._fieldnames(rows)
                with open(file_path, "w", encoding=self.encoding, newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                    writer.writeheader()
                    for row in rows:
                        writer.writerow({k: self._csv_value(row.get(k, "")) for k in fieldnames})
                increment("csv.rows_exported", len(rows))
                log.debug(f"تم تصدير {filename} ({len(rows)} صف)")
                return str(file_path)

            except Exception as e:
                log.error(f"فشل تصدير {filename}: {e}")
                increment("csv.export_errors")
                return ""

    def _fieldnames(self, rows: list[dict[str, Any]]) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row.keys():
                if key not in seen:
                    seen.add(key)
                    names.append(key)
        return names

    def _csv_value(self, value: Any) -> Any:
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False, default=str)
        return _neutralize_formula(value)

    def _flatten_issue_groups(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for group, items in data.items():
            if group.endswith("_count") or group == "total_issues" or not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    rows.append({"issue_group": group, **item})
                else:
                    rows.append({"issue_group": group, "value": item})
        return rows

    def _to_dict(self, obj: Any) -> dict[str, Any]:
        """تحويل dataclass إلى dict."""
        if is_dataclass(obj):
            return asdict(obj)
        if isinstance(obj, dict):
            return obj
        return {"value": str(obj)}
