"""
integrations/awt_importer.py
=============================
استيراد ودمج CSVs المُصدَّرة يدوياً من Ahrefs Webmaster Tools.

بما أن AWT لا يوفر API مجاني، نستورد:
- backlinks.csv: ملف Backlinks المُصدَّر
- keywords.csv: ملف Organic Keywords
- site_audit.csv: مشاكل Site Audit

الطريقة:
1. اذهب إلى ahrefs.com/webmaster-tools
2. صدّر البيانات كـ CSV
3. ضع الملفات في external_data/awt/
4. هذا السكريبت يقرأها ويدمجها مع نتائج الزحف
"""

from pathlib import Path
from typing import Any

import pandas as pd

from utils.logger import get_logger

log = get_logger(__name__)


class AWTImporter:
    """
    مستورد CSVs من Ahrefs Webmaster Tools.

    Example:
        >>> importer = AWTImporter("external_data/awt/")
        >>> backlinks = importer.load_backlinks()
        >>> keywords = importer.load_keywords()
    """

    def __init__(self, csv_folder: str):
        """
        Args:
            csv_folder: مجلد يحتوي على CSV files
        """
        self.csv_folder = Path(csv_folder)

    def load_backlinks(self, filename: str = "backlinks.csv") -> list[dict[str, Any]]:
        """
        تحميل Backlinks من CSV.

        AWT CSV typically contains:
        - Domain Rating (DR), URL Rating (UR)
        - Referring Page URL
        - Anchor Text
        - Link Type (text/image)
        - rel attributes (dofollow/nofollow/UGC/sponsored)
        - First Seen / Last Seen
        - Target URL
        """
        return self._load_csv(filename, "backlinks")

    def load_keywords(self, filename: str = "keywords.csv") -> list[dict[str, Any]]:
        """
        تحميل Organic Keywords من CSV.

        AWT CSV typically contains:
        - Keyword
        - Volume
        - Difficulty
        - Current Position
        - URL
        - Traffic
        - CPC
        """
        return self._load_csv(filename, "keywords")

    def load_referring_domains(
        self, filename: str = "referring_domains.csv"
    ) -> list[dict[str, Any]]:
        """تحميل Referring Domains."""
        return self._load_csv(filename, "referring_domains")

    def load_top_pages(self, filename: str = "top_pages.csv") -> list[dict[str, Any]]:
        """تحميل Top Pages (الصفحات الأكثر زيارات)."""
        return self._load_csv(filename, "top_pages")

    def load_site_audit(self, filename: str = "site_audit.csv") -> list[dict[str, Any]]:
        """
        تحميل نتائج Site Audit (170+ مشكلة).
        """
        return self._load_csv(filename, "site_audit")

    def _load_csv(self, filename: str, dataset_name: str) -> list[dict[str, Any]]:
        """تحميل CSV عام."""
        file_path = self.csv_folder / filename

        if not file_path.exists():
            log.warning(f"AWT CSV غير موجود: {file_path}")
            return []

        try:
            # محاولة قراءة بعدة encodings (AWT قد يستخدم UTF-8 أو UTF-16)
            for encoding in ["utf-8", "utf-8-sig", "utf-16", "cp1252"]:
                try:
                    df = pd.read_csv(file_path, encoding=encoding)
                    log.info(
                        f"AWT: تم تحميل {dataset_name} - {len(df)} صف من {file_path.name}"
                    )
                    # تنظيف أسماء الأعمدة (إزالة spaces زائدة)
                    df.columns = df.columns.str.strip()
                    return df.to_dict("records")
                except UnicodeDecodeError:
                    continue
                except Exception as e:
                    log.error(f"خطأ في قراءة {file_path}: {e}")
                    return []

            log.error(f"فشل قراءة {file_path} بأي encoding")
            return []

        except Exception as e:
            log.error(f"فشل تحميل AWT CSV {filename}: {e}")
            return []

    def merge_with_pages(
        self,
        pages_data: list[dict[str, Any]],
        keywords_data: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        دمج بيانات الكلمات المفتاحية مع pages.

        يُضيف لكل صفحة:
        - top_keywords: قائمة بأهم 5 كلمات
        - awt_traffic: حركة المرور المُقدَّرة
        - awt_keywords_count: عدد الكلمات التي ترتب عليها
        """
        if not keywords_data:
            return pages_data

        # تجميع الكلمات حسب URL
        keywords_by_url: dict[str, list[dict]] = {}
        for kw in keywords_data:
            # AWT يستخدم أسماء مختلفة للأعمدة، نجرّب عدة احتمالات
            url = kw.get("URL", kw.get("Page", kw.get("url", "")))
            if url:
                keywords_by_url.setdefault(url, []).append(kw)

        # دمج
        merged = []
        for page in pages_data:
            url = page.get("url", "")
            page_copy = dict(page)

            url_keywords = keywords_by_url.get(url, [])
            if url_keywords:
                # ترتيب حسب Volume
                url_keywords_sorted = sorted(
                    url_keywords,
                    key=lambda k: k.get("Volume", k.get("volume", 0)) or 0,
                    reverse=True,
                )

                page_copy["awt_keywords_count"] = len(url_keywords)
                page_copy["awt_top_keywords"] = [
                    k.get("Keyword", k.get("keyword", ""))
                    for k in url_keywords_sorted[:5]
                ]
                page_copy["awt_total_traffic"] = sum(
                    k.get("Traffic", k.get("traffic", 0)) or 0 for k in url_keywords
                )
            else:
                page_copy["awt_keywords_count"] = 0
                page_copy["awt_top_keywords"] = []
                page_copy["awt_total_traffic"] = 0

            merged.append(page_copy)

        return merged
