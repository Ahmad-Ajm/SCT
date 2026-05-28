"""
exporters/pdf_exporter.py
==========================
تحويل تقرير HTML إلى PDF عبر Playwright (متصفح حقيقي → دعم عربي/RTL مثالي).

نستخدم Playwright لأنه:
- مثبّت أصلاً ضمن اعتمادات المشروع.
- يدعم تشكيل العربية وRTL بشكل صحيح (عكس مكتبات PDF النقية).

إذا لم تكن Playwright متاحة (لم يُنفَّذ playwright install chromium) يُتخطّى
توليد PDF بهدوء مع إبقاء تقرير HTML.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from utils.logger import get_logger

log = get_logger(__name__)


class PDFReportExporter:
    def __init__(self, output_dir: str, filename: str = "report.pdf"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.file_path = self.output_dir / filename

    def is_available(self) -> bool:
        try:
            import playwright  # noqa: F401
            return True
        except ImportError:
            return False

    def export_from_html_file(self, html_path: str) -> Optional[str]:
        """تحويل ملف HTML موجود إلى PDF.

        إن استُدعيت داخل حلقة asyncio (مثل مرحلة التصدير في الزاحف) نُشغّل
        Playwright Sync في خيط منفصل بلا حلقة أحداث (Sync API لا يعمل داخل اللوب).
        """
        if not self.is_available():
            log.warning(
                "تخطّي توليد PDF: Playwright غير متاح. "
                "نفّذ: pip install playwright && playwright install chromium"
            )
            return None

        in_loop = False
        try:
            import asyncio
            asyncio.get_running_loop()
            in_loop = True
        except RuntimeError:
            in_loop = False

        if in_loop:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(self._render_sync, html_path).result()
        return self._render_sync(html_path)

    def _render_sync(self, html_path: str) -> Optional[str]:
        html_uri = Path(html_path).resolve().as_uri()
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                page.goto(html_uri, wait_until="networkidle")
                page.pdf(
                    path=str(self.file_path),
                    format="A4",
                    print_background=True,
                    margin={"top": "1cm", "bottom": "1cm", "left": "1cm", "right": "1cm"},
                )
                browser.close()
            log.info(f"تم حفظ تقرير PDF: {self.file_path}")
            return str(self.file_path)
        except Exception as e:
            log.error(f"فشل توليد PDF: {e}")
            return None

    async def export_from_html_file_async(self, html_path: str) -> Optional[str]:
        """نسخة async (مفيدة داخل خادم الويب)."""
        if not self.is_available():
            log.warning("تخطّي توليد PDF: Playwright غير متاح.")
            return None
        html_uri = Path(html_path).resolve().as_uri()
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page()
                await page.goto(html_uri, wait_until="networkidle")
                await page.pdf(
                    path=str(self.file_path),
                    format="A4",
                    print_background=True,
                    margin={"top": "1cm", "bottom": "1cm", "left": "1cm", "right": "1cm"},
                )
                await browser.close()
            log.info(f"تم حفظ تقرير PDF: {self.file_path}")
            return str(self.file_path)
        except Exception as e:
            log.error(f"فشل توليد PDF: {e}")
            return None
