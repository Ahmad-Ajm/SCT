"""
services/export_service.py — Phase 4: تصدير CSV / Excel / JSON / XML / HTML / PDF.

نُقل من main.py في v1.12.2 (Tier 4 — أكبر service بـ~400 LOC).
يعتمد على exporters/* lazy، services/progress_service لـemit_phase،
services/integrations_summary لـgsc_summary/ga4_summary،
services/deferred_service لـdeferred_list/_summary،
services/config_service لـslugify_label،
services/export_helpers لـكل flatten helpers.

ملاحظة معماريّة: lazy imports للـexporters محافظ عليها — Excel/Sitemap/PDF
كلّها deps اختياريّة (openpyxl, defusedxml, playwright).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from services.config_service import slugify_label
from services.deferred_service import deferred_list, deferred_summary
from services.export_helpers import (
    export_pagespeed_tables,
    flatten_accessibility,
    flatten_accessibility_issues,
    flatten_cannibalization,
    flatten_hreflang_issues,
    flatten_pagespeed,
    flatten_pagespeed_opportunities,
    integrations_for_json,
)
from services.integrations_summary import ga4_summary, gsc_summary
from services.progress_service import emit_phase
from utils.logger import get_logger
from utils.monitoring import gauge, increment, span

if TYPE_CHECKING:
    from modes.base import CrawlMode

log = get_logger(__name__)


def run_export(crawler, analysis, integrations, external_check, output_dir, config, mode):
    from exporters.csv_exporter import CSVExporter
    from exporters.json_exporter import JSONExporter

    log.info("=" * 60)
    log.info("Phase 4: Export")
    log.info("=" * 60)

    formats = config["output"].get("formats", ["csv", "excel", "json"])
    encoding = config["output"].get("encoding", "utf-8-sig")
    exported_files = {}

    # طابع زمني + اسم نطاق لتسمية الملفات الرئيسية (التقرير/Excel/JSON)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    site_slug = slugify_label(config.get("site", {}).get("domain", "") or mode.name)
    excel_name = f"audit_{site_slug}_{stamp}.xlsx"
    json_name = f"audit_{site_slug}_{stamp}.json"
    report_stem = f"report_{site_slug}_{stamp}"

    pages = crawler.get_pages()
    links = crawler.get_links()
    images = crawler.get_images()
    headings = crawler.get_headings()
    schema = crawler.get_schema()
    redirects = crawler.get_redirects()
    headers = crawler.get_headers()
    excluded = getattr(crawler, "get_excluded", lambda: [])()
    excluded_counts = getattr(crawler, "excluded_counts", {}) or {}

    gauge("export.input.pages", len(pages))
    gauge("export.input.links", len(links))
    gauge("export.input.images", len(images))
    gauge("export.input.headings", len(headings))
    gauge("export.input.schema", len(schema))

    if "csv" in formats:
        log.info("→ CSV...")
        with span("export.csv", output_dir=str(output_dir / "csv")):
            csv_exporter = CSVExporter(str(output_dir / "csv"), encoding=encoding)
            csv_files = csv_exporter.export_all(
                pages=pages, links=links, images=images, headings=headings,
                schema=schema, redirects=redirects, headers=headers,
                seo_issues=analysis.get("seo_issues", {}),
                duplicate_data=analysis.get("duplicate_data", {}),
                orphan_data=analysis.get("orphan_data", {}),
                thin_content_data=analysis.get("thin_content_data", {}),
                broken_data=analysis.get("broken_data", {}),
                images_analysis=analysis.get("images_analysis", {}),
                url_issues=analysis.get("url_issues", {}),
                canonical_data=analysis.get("canonical_data", {}),
            )
            if excluded:
                csv_files["excluded_urls"] = csv_exporter._export("excluded_urls.csv", excluded)

            # v1.08: CSV للروابط المؤجَّلة — يتيح للمستخدم استعراضها/تصفيتها قبل Phase 2
            deferred_rows = deferred_list(crawler)
            if deferred_rows:
                csv_files["deferred_urls"] = csv_exporter._export(
                    "deferred_urls.csv", deferred_rows,
                )

            # تقارير redirects التفصيلية (الخطة #1)
            rd = analysis.get("redirect_data", {}) or {}
            if rd.get("redirect_chains"):
                csv_files["redirect_chains"] = csv_exporter._export(
                    "redirect_chains.csv",
                    [{"original_url": c.get("original_url"), "final_url": c.get("final_url"),
                      "chain_length": c.get("chain_length"),
                      "hops": " → ".join(h.get("from", "") for h in c.get("hops", []))}
                     for c in rd["redirect_chains"]],
                )
            if rd.get("redirect_loops"):
                csv_files["redirect_loops"] = csv_exporter._export(
                    "redirect_loops.csv",
                    [{"original_url": c.get("original_url"), "final_url": c.get("final_url"),
                      "chain_length": c.get("chain_length")} for c in rd["redirect_loops"]],
                )
            redirect_issues = []
            for r in rd.get("temporary_redirects", []):
                redirect_issues.append({"issue": "temporary_302_307", **r})
            for r in rd.get("internal_redirects", []):
                redirect_issues.append({"issue": "internal_redirect", **r})
            for c in rd.get("protocol_upgrades", []):
                redirect_issues.append({"issue": "protocol_upgrade",
                                        "from": c.get("original_url"), "to": c.get("final_url")})
            if redirect_issues:
                csv_files["redirect_issues"] = csv_exporter._export(
                    "redirect_issues.csv", redirect_issues)

            # مشاكل الأمان (الخطة #8)
            sec = analysis.get("security_data", {}) or {}
            if sec.get("issues"):
                csv_files["security_issues"] = csv_exporter._export(
                    "security_issues.csv", sec["issues"])

            # الاستخراج المخصّص (الخطة #5)
            custom_rows = getattr(crawler, "get_custom_extraction", lambda: [])()
            if custom_rows:
                csv_files["custom_extraction"] = csv_exporter._export(
                    "custom_extraction.csv", custom_rows)

            # استيراد Lighthouse (الخطة #6)
            lh_rows = (integrations or {}).get("lighthouse") or []
            if lh_rows:
                csv_files["lighthouse_import"] = csv_exporter._export(
                    "lighthouse_import.csv", lh_rows)

            # جرد الموارد (الخطة #3)
            resource_rows = getattr(crawler, "get_resources", lambda: [])()
            if resource_rows:
                csv_files["resources"] = csv_exporter._export("resources.csv", resource_rows)
                rdata = analysis.get("resources_data", {}) or {}
                issues = (rdata.get("mixed_content", []) or []) + (rdata.get("broken_resources", []) or [])
                if issues:
                    csv_files["resource_issues"] = csv_exporter._export(
                        "resource_issues.csv", issues)
            # حالة HTTP للموارد (عند تفعيل extraction.check_resource_status)
            resource_status = analysis.get("resource_status", []) or []
            if resource_status:
                csv_files["resource_status"] = csv_exporter._export(
                    "resource_status.csv", resource_status)

            # ترقيم الصفحات (rel=next/prev)
            pgd = analysis.get("pagination_data", {}) or {}
            if pgd.get("paginated_pages"):
                csv_files["pagination"] = csv_exporter._export(
                    "pagination.csv", pgd["paginated_pages"])
            if pgd.get("issues"):
                csv_files["pagination_issues"] = csv_exporter._export(
                    "pagination_issues.csv", pgd["issues"])

            # مشاكل hreflang (عدم التبادل/404/noindex…)
            hv = analysis.get("hreflang_validation", {}) or {}
            hreflang_rows = flatten_hreflang_issues(hv)
            if hreflang_rows:
                csv_files["hreflang_issues"] = csv_exporter._export(
                    "hreflang_issues.csv", hreflang_rows)

            # diff تصيير JavaScript (الخطة #4)
            js_diff = getattr(crawler, "get_js_diff", lambda: [])()
            if js_diff:
                csv_files["js_diff"] = csv_exporter._export("js_diff.csv", js_diff)

            # فحص الوصولية (axe-core) — ملخّص لكل صفحة + قائمة المخالفات
            a11y = getattr(crawler, "get_accessibility", lambda: [])()
            if a11y:
                csv_files["accessibility"] = csv_exporter._export(
                    "accessibility.csv", flatten_accessibility(a11y))
                a11y_issues = flatten_accessibility_issues(a11y)
                if a11y_issues:
                    csv_files["accessibility_issues"] = csv_exporter._export(
                        "accessibility_issues.csv", a11y_issues)

            # === التقرير الموحّد: GSC / GA4 / الأولويات ===
            if (integrations or {}).get("gsc_pages"):
                csv_files["gsc_pages"] = csv_exporter._export(
                    "gsc_pages.csv", integrations["gsc_pages"])
            if (integrations or {}).get("gsc_queries"):
                csv_files["gsc_queries"] = csv_exporter._export(
                    "gsc_queries.csv", integrations["gsc_queries"])
            if (integrations or {}).get("ga4_landing_pages"):
                csv_files["ga4_landing_pages"] = csv_exporter._export(
                    "ga4_landing_pages.csv", integrations["ga4_landing_pages"])
            if (integrations or {}).get("ga4_channels"):
                csv_files["ga4_channels"] = csv_exporter._export(
                    "ga4_channels.csv", integrations["ga4_channels"])
            if (integrations or {}).get("gsc_index_status"):
                csv_files["gsc_index_status"] = csv_exporter._export(
                    "gsc_index_status.csv", integrations["gsc_index_status"])
            opps = (analysis.get("opportunities", {}) or {}).get("opportunities")
            if opps:
                csv_files["priority_opportunities"] = csv_exporter._export(
                    "priority_opportunities.csv", opps)
            # محرّك الأولويات v2: درجة لكل صفحة + لوحة العمل
            prio = analysis.get("priority", {}) or {}
            prio_pages = prio.get("pages") or []
            if prio_pages:
                csv_files["page_priority"] = csv_exporter._export(
                    "page_priority.csv", prio_pages)
                from reporting.priority_engine import build_action_board
                board = build_action_board(prio)
                if board:
                    csv_files["action_board"] = csv_exporter._export(
                        "action_board.csv", board)

            # درجة الروابط الداخلية (PageRank داخلي) لكل صفحة
            ls = (analysis.get("link_score", {}) or {}).get("pages") or []
            if ls:
                csv_files["link_score"] = csv_exporter._export("link_score.csv", ls)

            # أزواج الصفحات المتشابهة تقريبياً (Near-Duplicate)
            nd_pairs = (analysis.get("near_duplicate", {}) or {}).get("pairs") or []
            if nd_pairs:
                csv_files["near_duplicates"] = csv_exporter._export(
                    "near_duplicates.csv", nd_pairs)

            # تحليلات GSC (IMP-1): تكلّس الكلمات + فُرَص الروابط الداخلية
            cann_rows = flatten_cannibalization(analysis.get("cannibalization", {}))
            if cann_rows:
                csv_files["keyword_cannibalization"] = csv_exporter._export(
                    "keyword_cannibalization.csv", cann_rows)
            ilo = (analysis.get("internal_link_opportunities", {}) or {}).get("opportunities") or []
            if ilo:
                csv_files["internal_link_opportunities"] = csv_exporter._export(
                    "internal_link_opportunities.csv", ilo)

            # PageSpeed Insights (عند تفعيل التكامل) — نُسطّح المقاييس الأساسية
            ps_data = (integrations or {}).get("pagespeed") or []
            ps_rows = flatten_pagespeed(ps_data)
            if ps_rows:
                csv_files["pagespeed"] = csv_exporter._export("pagespeed.csv", ps_rows)
            ps_opps = flatten_pagespeed_opportunities(ps_data)
            if ps_opps:
                csv_files["pagespeed_opportunities"] = csv_exporter._export(
                    "pagespeed_opportunities.csv", ps_opps)
            # الجداول المنظّمة العميقة (audits / network / treemap / failed) — IMP-17أ
            export_pagespeed_tables(ps_data, csv_exporter, csv_files)
            # اتجاه Core Web Vitals عبر الزمن (IMP-9)
            if (integrations or {}).get("crux_history"):
                csv_files["crux_history"] = csv_exporter._export(
                    "crux_history.csv", integrations["crux_history"])

            # توصيات الذكاء الاصطناعي (عند تفعيل التكامل)
            ai = analysis.get("ai_analysis", {}) or {}
            if ai.get("recommendations"):
                csv_files["ai_recommendations"] = csv_exporter._export(
                    "ai_recommendations.csv", ai["recommendations"])
        exported_files.update({f"csv_{k}": v for k, v in csv_files.items()})

    if "excel" in formats:
        log.info("→ Excel...")
        with span("export.excel", output_dir=str(output_dir)):
            # تثبيت تلقائي لـ openpyxl عند الحاجة (IMP-16) — v1.12 صار opt-in.
            from utils.auto_install import ensure_package
            ensure_package("openpyxl")
            try:
                from exporters.excel_exporter import ExcelExporter
            except ModuleNotFoundError as e:
                if e.name == "openpyxl":
                    log.warning("Excel export skipped: openpyxl is not installed")
                    increment("export.excel.skipped_missing_openpyxl")
                    excel_file = ""
                else:
                    raise
            else:
                excel_exporter = ExcelExporter(str(output_dir), excel_name)
                excel_file = excel_exporter.export(
                    pages=pages, links=links, images=images, headings=headings,
                    schema=schema, redirects=redirects, headers=headers,
                    seo_issues=analysis.get("seo_issues", {}),
                    duplicate_data=analysis.get("duplicate_data", {}),
                    orphan_data=analysis.get("orphan_data", {}),
                    thin_content_data=analysis.get("thin_content_data", {}),
                    broken_data=analysis.get("broken_data", {}),
                    images_analysis=analysis.get("images_analysis", {}),
                    crawl_stats=crawler.get_stats(),
                    site_url=config["site"]["start_url"],
                )
        if excel_file:
            exported_files["excel"] = excel_file

    if "json" in formats:
        log.info("→ JSON...")
        # المصفوفات الخام (روابط/صور/عناوين) قد تبلغ مئات آلاف الصفوف وتُضخّم JSON
        # لغيغابايتات يتعذّر فتحها/إعادة بناء التقرير منها. نستثنيها افتراضياً (متوفّرة
        # كاملةً في CSV/Excel/XML)، وتُضمَّن فقط عند output.json_full=true.
        json_full = bool(config["output"].get("json_full", False))
        with span("export.json", output_dir=str(output_dir)):
            json_exporter = JSONExporter(str(output_dir), json_name)
            raw_arrays: dict[str, Any] = {}
            if json_full:
                raw_arrays = {"links": links, "images": images, "headings": headings}
            else:
                raw_arrays = {"raw_arrays_omitted": {
                    "links": len(links), "images": len(images), "headings": len(headings),
                    "note": "set output.json_full=true to embed; full data is in CSV/Excel/XML",
                }}
            json_file = json_exporter.export(
                pages=pages,
                schema=schema, redirects=redirects,
                mode=mode.name,
                **raw_arrays,
                seo_issues=analysis.get("seo_issues", {}),
                duplicate_data=analysis.get("duplicate_data", {}),
                orphan_data=analysis.get("orphan_data", {}),
                thin_content_data=analysis.get("thin_content_data", {}),
                broken_data=analysis.get("broken_data", {}),
                images_analysis=analysis.get("images_analysis", {}),
                url_issues=analysis.get("url_issues", {}),
                canonical_data=analysis.get("canonical_data", {}),
                schema_validation=analysis.get("schema_validation", {}),
                hreflang_validation=analysis.get("hreflang_validation", {}),
                sitemap_diff=analysis.get("sitemap_diff", {}),
                redirect_data=analysis.get("redirect_data", {}),
                pagination_data=analysis.get("pagination_data", {}),
                external_check=external_check,
                integrations=integrations_for_json(integrations),
                excluded_urls=excluded,
                excluded_summary=excluded_counts,
                # v1.08: روابط مؤجَّلة (لم تُفحَص في Phase 1) + ملخّصها
                deferred_urls=deferred_list(crawler),
                deferred_summary=deferred_summary(crawler),
                security_data=analysis.get("security_data", {}),
                resources_data=analysis.get("resources_data", {}),
                resource_status=analysis.get("resource_status", []),
                custom_extraction=getattr(crawler, "get_custom_extraction", lambda: [])(),
                js_diff=getattr(crawler, "get_js_diff", lambda: [])(),
                accessibility=getattr(crawler, "get_accessibility", lambda: [])(),
                opportunities=analysis.get("opportunities", {}),
                priority=analysis.get("priority", {}),
                cannibalization=analysis.get("cannibalization", {}),
                internal_link_opportunities=analysis.get("internal_link_opportunities", {}),
                ai_analysis=analysis.get("ai_analysis", {}),
                gsc_summary=gsc_summary(integrations),
                ga4_summary=ga4_summary(integrations),
                site_config=config["site"],
            )
        exported_files["json"] = json_file

    if "xml" in formats:
        log.info("→ XML...")
        # سقف لصفوف XML: على المواقع الكبيرة كان links.xml يتجاوز الغيغابايت.
        # نقصّ كل مجموعة عند الحد (البيانات الكاملة في CSV/Excel). 0 = بلا حد.
        xml_max = int(config["output"].get("xml_max_rows", 50000) or 0)

        def _cap(rows: list[Any], name: str) -> list[Any]:
            if xml_max and len(rows) > xml_max:
                log.warning(
                    f"   XML {name}: {len(rows)} صف يتجاوز الحد {xml_max} — يُقتصَر في XML "
                    f"(البيانات الكاملة في CSV/Excel)"
                )
                return rows[:xml_max]
            return rows

        with span("export.xml", output_dir=str(output_dir / "xml")):
            from exporters.xml_exporter import XMLExporter

            xml_exporter = XMLExporter(str(output_dir / "xml"))
            xml_files = xml_exporter.export_all(
                pages=_cap(pages, "pages"),
                links=_cap(links, "links"),
                images=_cap(images, "images"),
                schema=_cap(schema, "schema"),
                seo_issues=analysis.get("seo_issues", {}),
            )
        exported_files.update({f"xml_{k}": v for k, v in xml_files.items()})

    # === HTML / PDF report ===
    # عند الإيقاف اليدوي نتخطّى بناء HTML/PDF (البطيء) كي تظهر تنزيلات النتائج
    # الجزئية فوراً؛ يمكن للمستخدم إعادة بناء التقرير لاحقاً من الواجهة.
    stopped_early = getattr(crawler, "_external_stop", False)
    if ("html" in formats or "pdf" in formats) and not stopped_early:
        log.info("→ HTML/PDF report...")
        from exporters.report_builder import build_report

        report_opts = config.get("report", {}) or {}
        make_pdf = "pdf" in formats

        def on_report_progress(status: str, **payload: Any) -> None:
            emit_phase(crawler, status, **payload)

        # نبني التقرير من البيانات في الذاكرة مباشرةً، لا بإعادة تحميل ملف JSON
        # الذي قد يبلغ غيغابايتات على المواقع الكبيرة (كان سبب تعليق «إعداد التقارير»).
        # التقرير يحتاج الصفحات + التحليلات + الملخّصات فقط — لا المصفوفات الخام
        # (روابط/صور/عناوين) المتوفّرة في CSV/Excel/XML.
        report_audit = {
            "site_config": config["site"],
            "pages": pages,
            "seo_issues": analysis.get("seo_issues", {}),
            "opportunities": analysis.get("opportunities", {}),
            "redirect_data": analysis.get("redirect_data", {}),
            "pagination_data": analysis.get("pagination_data", {}),
            "resources_data": analysis.get("resources_data", {}),
            "resource_status": analysis.get("resource_status", []),
            "hreflang_validation": analysis.get("hreflang_validation", {}),
            "schema_validation": analysis.get("schema_validation", {}),
            "ai_analysis": analysis.get("ai_analysis", {}),
            "gsc_summary": gsc_summary(integrations),
            "ga4_summary": ga4_summary(integrations),
        }
        with span("export.report", output_dir=str(output_dir)):
            report = build_report(
                report_audit,
                str(output_dir),
                options=report_opts,
                make_pdf=make_pdf,
                name_stem=report_stem,
                progress_callback=on_report_progress,
            )
        # نسجّل كل صيغ التقرير الناتجة (تشمل client/expert في وضع both)
        for key in ("html", "pdf", "html_client", "pdf_client", "html_expert", "pdf_expert"):
            if report.get(key):
                exported_files[key] = report[key]

    # === توليد Sitemap من الصفحات القابلة للفهرسة (IMP-5) — اختياري ===
    if config["output"].get("generate_sitemap"):
        try:
            from exporters.sitemap_generator import SitemapGenerator
            base = config.get("site", {}).get("start_url", "")
            sm = SitemapGenerator(str(output_dir), base_url=base).generate(pages)
            for i, fpath in enumerate(sm.get("files", [])):
                exported_files["sitemap" if i == 0 else f"sitemap_{i}"] = fpath
        except Exception:  # noqa: BLE001
            log.exception("Sitemap generation failed")

    gauge("export.files", len(exported_files))
    return exported_files
