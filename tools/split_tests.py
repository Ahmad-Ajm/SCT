"""
tools/split_tests.py — v1.13 REFACTOR-tests-split executor.

يقسّم tests/test_core_behaviors.py إلى 6 ملفّات تحت tests/ بحسب فئة كلّ اختبار:
    test_crawler.py    — robots, db persistence, async_core, classifier, content/custom extractors
    test_analyzers.py  — كلّ analyzers/*
    test_integrations.py — gsc/ga4/pagespeed/crux/ai/lighthouse/backlinks
    test_exporters.py  — csv/html/excel/xml/report_builder/sitemap_generator
    test_priority.py   — priority_engine + url_detail
    test_utils.py      — helpers, monitoring, auto_install, cache, webapp infra

الـscript مكتوب لاستخدام مرّة واحدة (idempotent: يُعيد بناء الملفّات الست).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tests" / "test_core_behaviors.py"

# ============================================================
# تصنيف كلّ اختبار (مأخوذ من scout v1.11 + تعديلات)
# ============================================================
CATEGORY: dict[str, str] = {
    # --- crawler.py ---
    "test_robots_failure_policy_can_deny_when_unloaded": "crawler",
    "test_robots_parser_reads_rules_and_sitemaps": "crawler",
    "test_robots_parser_caps_oversized_response": "crawler",
    "test_local_fixture_server_serves_stable_seo_cases": "crawler",
    "test_database_saves_page_bundle_in_one_call": "crawler",
    "test_c3_no_duplicate_child_rows_on_recrawl": "crawler",
    "test_c2_resume_db_roundtrip": "crawler",
    "test_db_persists_new_security_header_columns": "crawler",
    "test_db_persists_pagination_columns": "crawler",
    "test_db_backed_getters_memoized": "crawler",
    "test_custom_extractor_css_and_regex": "crawler",
    "test_content_extractor_skips_simhash_for_short_text": "crawler",
    "test_adaptive_throttle_backs_off_and_recovers": "crawler",
    "test_platform_preset_detect_and_apply": "crawler",
    "test_discover_new_links_smoke_smoke": "crawler",
    "test_url_classifier_branches": "crawler",
    "test_inject_phase2_seeds_skips_missing_csv": "crawler",

    # --- analyzers.py ---
    "test_url_issues_analyzer_detects_common_patterns": "analyzers",
    "test_canonical_analyzer_detects_bad_targets_and_loops": "analyzers",
    "test_analyzers_accept_dict_rows": "analyzers",
    "test_redirect_chain_ordering_and_internal": "analyzers",
    "test_microdata_schema_is_validated": "analyzers",
    "test_non_ascii_urls_off_by_default": "analyzers",
    "test_images_unique_vs_occurrences": "analyzers",
    "test_security_analyzer_flags_missing_headers": "analyzers",
    "test_pagination_analyzer_sequence_and_canonical": "analyzers",
    "test_redirect_analyzer_dedups_shared_internal_hop": "analyzers",
    "test_link_score_pagerank_basic": "analyzers",
    "test_simhash_near_duplicate_detection": "analyzers",
    "test_spell_check_graceful_without_library": "analyzers",
    "test_link_score_dedups_repeated_internal_edges": "analyzers",
    "test_near_duplicate_autocorrects_invalid_bands": "analyzers",
    "test_duplicate_detector_coerces_non_string_fields": "analyzers",
    "test_gsc_cannibalization_and_link_opportunities": "analyzers",
    "test_seo_issue_hints_attached": "analyzers",
    "test_crawl_compare_fixed_new_persisting": "analyzers",
    "test_accessibility_axe_summary": "analyzers",
    "test_accessibility_axe_source_loader": "analyzers",
    "test_log_analyzer_parses_clf_and_finds_orphans": "analyzers",
    "test_status_of_handles_strings_and_none": "analyzers",

    # --- integrations.py ---
    "test_lighthouse_importer": "integrations",
    "test_ai_advisor_graceful_without_key": "integrations",
    "test_ai_advisor_openai_compatible_call_and_parse": "integrations",
    "test_ai_advisor_gemini_call": "integrations",
    "test_ai_advisor_rejects_private_base_url_ssrf": "integrations",
    "test_ai_summary_builder_compacts_audit": "integrations",
    "test_pagespeed_lighthouse_table_extraction": "integrations",
    "test_gsc_url_inspection_parser": "integrations",
    "test_crux_history_parser": "integrations",
    "test_google_listing_parsers_and_code_extractor": "integrations",
    "test_connection_test_helper_times_out": "integrations",
    "test_backlinks_provider_unknown_returns_none": "integrations",

    # --- exporters.py ---
    "test_csv_exporter_serializes_nested_values": "exporters",
    "test_html_report_generates_rtl": "exporters",
    "test_report_audience_client_vs_expert": "exporters",
    "test_report_audience_both_builds_two_files": "exporters",
    "test_images_csv_exports_all_not_capped_at_100": "exporters",
    "test_unified_join_and_opportunities": "exporters",
    "test_sitemap_generator_includes_only_eligible": "exporters",
    "test_html_report_renders_action_board": "exporters",

    # --- priority.py ---
    "test_url_detail_joins_all_sources": "priority",
    "test_priority_engine_page_type_and_ease": "priority",
    "test_priority_engine_scores_and_action_board": "priority",

    # --- utils.py ---
    "test_normalize_url_resolves_dots_keeps_trailing": "utils",
    "test_is_internal_url_strips_only_leading_www": "utils",
    "test_matches_any_pattern_substring_and_glob": "utils",
    "test_ssrf_guard_blocks_internal": "utils",
    "test_formula_neutralization": "utils",
    "test_format_duration_no_sixty_seconds": "utils",
    "test_monitoring_span_event_tolerate_reserved_attrs": "utils",
    "test_run_log_summary_counts_by_level_not_substring": "utils",
    "test_job_delete_safely_removes_folder": "utils",
    "test_job_config_maps_new_ui_options": "utils",
    "test_auto_install_present_and_refuses_unknown": "utils",
    "test_probe_token_expired_corrupt_file": "utils",
    "test_cache_key_differs_per_api_identity": "utils",
    "test_ssrf_blocks_ipv4_mapped_ipv6": "utils",
}

# الـimports المشترَكة بين كلّ ملفّات الاختبار الجديدة.
BASE_IMPORTS = """\
import csv
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

# v1.13 REFACTOR-tests-split: shared fixtures
from tests.conftest import FakeResponse, MinimalPage, _FakeAIResp  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "seo_crawler" / "seo_crawler"
"""

# Imports خاصّة بكلّ فئة — ما يحتاجه كلّ ملف على module-level.
CATEGORY_IMPORTS: dict[str, str] = {
    "crawler": """\
from crawler.robots_parser import RobotsParser
from storage.database import CrawlDatabase
""",
    "analyzers": """\
from analyzers.canonical_analyzer import analyze_canonicals
from analyzers.url_issues import analyze_url_issues
from analyzers.duplicate_detector import detect_duplicates
from analyzers.broken_links import detect_broken_links
from analyzers.thin_content import detect_thin_content
from analyzers.redirect_analyzer import analyze_redirects
from analyzers.seo_issues import collect_seo_issues
from analyzers.schema_validator import validate_schemas
from storage.database import CrawlDatabase
""",
    "integrations": "",
    "exporters": """\
from exporters.csv_exporter import CSVExporter
from exporters.html_exporter import HTMLReportExporter
""",
    "priority": "",
    "utils": """\
from utils.helpers import (
    normalize_url,
    is_internal_url,
    is_safe_remote_url,
    matches_any_pattern,
    neutralize_formula,
    format_duration,
)
""",
}
COMMON_IMPORTS = BASE_IMPORTS  # alias to keep older code happy


def main() -> int:
    src_text = SRC.read_text(encoding="utf-8")
    tree = ast.parse(src_text)

    # Collect: per-test source code (including decorators)
    # Each test is a FunctionDef inside a ClassDef.
    tests_by_category: dict[str, list[str]] = {
        "crawler": [], "analyzers": [], "integrations": [],
        "exporters": [], "priority": [], "utils": [],
    }
    # Track which class owned each test (للنقاش — في النهاية كلّ الاختبارات تذهب لـTestCase موحَّد لكلّ ملف).
    src_lines = src_text.splitlines(keepends=True)

    seen: set[str] = set()
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        for item in cls.body:
            if not isinstance(item, ast.FunctionDef):
                continue
            tname = item.name
            if not tname.startswith("test_"):
                continue
            cat = CATEGORY.get(tname)
            if not cat:
                print(f"  ! UNCATEGORIZED: {tname}", file=sys.stderr)
                continue
            seen.add(tname)
            # Get source: from decorator start (إن وُجد) إلى end_lineno
            start = item.lineno - 1  # 0-indexed
            end = item.end_lineno
            method_src = "".join(src_lines[start:end])
            # نُحافظ على المستوى الأصلي للـindentation (4 مسافات داخل الكلاس)
            tests_by_category[cat].append(method_src)

    # تنبيهات
    missing = set(CATEGORY) - seen
    if missing:
        print(f"  ! Tests in CATEGORY but not found in file: {sorted(missing)}", file=sys.stderr)

    # كتابة الملفّات الستّ
    headers = {
        "crawler": (
            "tests/test_crawler.py — robots / db / async_core / classifier / extractors.\n"
            "نُقلت من test_core_behaviors.py في v1.13 REFACTOR-tests-split."
        ),
        "analyzers": (
            "tests/test_analyzers.py — كل analyzers/* + crawl_compare + log_analyzer + accessibility.\n"
            "نُقلت من test_core_behaviors.py في v1.13 REFACTOR-tests-split."
        ),
        "integrations": (
            "tests/test_integrations.py — gsc_api / ga4_api / pagespeed / crux / ai_advisor / lighthouse / backlinks.\n"
            "نُقلت من test_core_behaviors.py في v1.13 REFACTOR-tests-split."
        ),
        "exporters": (
            "tests/test_exporters.py — csv_exporter / html_exporter / report_builder / sitemap_generator.\n"
            "نُقلت من test_core_behaviors.py في v1.13 REFACTOR-tests-split."
        ),
        "priority": (
            "tests/test_priority.py — reporting/priority_engine + reporting/url_detail.\n"
            "نُقلت من test_core_behaviors.py في v1.13 REFACTOR-tests-split."
        ),
        "utils": (
            "tests/test_utils.py — utils/helpers + utils/monitoring + utils/auto_install + storage/cache + webapp infra.\n"
            "نُقلت من test_core_behaviors.py في v1.13 REFACTOR-tests-split."
        ),
    }

    out_dir = ROOT / "tests"
    for cat, methods in tests_by_category.items():
        if not methods:
            print(f"  - {cat}: (empty)")
            continue
        cls_name = f"Test{cat.capitalize()}"
        body = "".join(methods).rstrip() + "\n"
        cat_imp = CATEGORY_IMPORTS.get(cat, "")
        imports = BASE_IMPORTS + ("\n" + cat_imp if cat_imp else "")
        content = f'"""\n{headers[cat]}\n"""\n\n{imports}\n\nclass {cls_name}(unittest.TestCase):\n{body}\n'
        target = out_dir / f"test_{cat}.py"
        target.write_text(content, encoding="utf-8")
        print(f"  + {target.name}: {len(methods)} tests, {len(content.splitlines())} lines")

    return 0


if __name__ == "__main__":
    sys.exit(main())
