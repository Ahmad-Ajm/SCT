"""
analyzers/seo_issues.py
========================
تجميع كل مشاكل SEO المُكتشفة في تقرير موحّد مع نظام أولوية.

نظام الأولوية:
🔴 Critical — يجب إصلاحه فوراً
🟠 High — إصلاح خلال أسبوع
🟡 Medium — إصلاح خلال شهر
🟢 Low — تحسين متى أمكن
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from crawler.core import PageData


def _get(item: Any, key: str, default: Any = None) -> Any:
    """Read a field from either a PageData object or a dict row (DB-backed)."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _status(page: Any) -> int:
    """Status code as an int (DB rows may store it as str/None)."""
    try:
        return int(_get(page, "status_code", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _int(page: Any, key: str) -> int:
    try:
        return int(_get(page, key, 0) or 0)
    except (TypeError, ValueError):
        return 0


class IssueSeverity(str, Enum):
    """مستويات أولوية المشاكل."""

    CRITICAL = "🔴 Critical"
    HIGH = "🟠 High"
    MEDIUM = "🟡 Medium"
    LOW = "🟢 Low"


@dataclass
class SEOIssue:
    """مشكلة SEO واحدة."""

    severity: IssueSeverity
    category: str  # Technical / On-Page / Content / Performance
    issue_type: str  # نوع المشكلة
    description: str  # وصف
    affected_count: int = 0  # عدد الصفحات المتأثرة
    affected_urls: list[str] = field(default_factory=list)
    recommendation: str = ""  # التوصية

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity.value,
            "category": self.category,
            "issue_type": self.issue_type,
            "description": self.description,
            "affected_count": self.affected_count,
            "affected_urls_sample": self.affected_urls[:10],
            "recommendation": self.recommendation,
        }


def collect_seo_issues(
    pages: list[PageData],
    duplicate_data: dict[str, Any],
    orphan_data: dict[str, Any],
    redirect_data: dict[str, Any],
    thin_content_data: dict[str, Any],
    broken_data: dict[str, Any],
    images_data: dict[str, Any],
    url_issues: dict[str, Any] | None = None,
    canonical_data: dict[str, Any] | None = None,
    config: dict[str, Any] = None,
) -> dict[str, Any]:
    """
    تجميع كل المشاكل في تقرير موحّد.

    Returns:
        dict: {
            "all_issues": list[dict],
            "by_severity": dict[severity, list],
            "by_category": dict[category, list],
            "summary": {...},
        }
    """
    config = config or {}
    url_issues = url_issues or {}
    canonical_data = canonical_data or {}
    analysis_config = config.get("analysis", {})

    title_max = analysis_config.get("title_max_length", 60)
    title_min = analysis_config.get("title_min_length", 30)
    desc_max = analysis_config.get("description_max_length", 160)
    desc_min = analysis_config.get("description_min_length", 70)
    thin_threshold = analysis_config.get("thin_content_threshold", 300)
    thin_critical = analysis_config.get("thin_content_critical_threshold", 100)

    issues: list[SEOIssue] = []

    # ========================================================
    # === Canonical & URL Hygiene Issues ===
    # ========================================================

    if canonical_data.get("canonical_loops_count", 0) > 0:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.CRITICAL,
                category="Technical",
                issue_type="Canonical Loops",
                description=f"{canonical_data['canonical_loops_count']} صفحة فيها canonical loop",
                affected_count=canonical_data["canonical_loops_count"],
                affected_urls=[row["url"] for row in canonical_data.get("canonical_loops", [])],
                recommendation="أزل الحلقة واجعل canonical يشير إلى نسخة نهائية واحدة قابلة للفهرسة",
            )
        )

    if canonical_data.get("canonical_to_non_200_count", 0) > 0:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.CRITICAL,
                category="Technical",
                issue_type="Canonical to Non-200 URL",
                description=f"{canonical_data['canonical_to_non_200_count']} صفحة تشير canonical إلى URL غير 200",
                affected_count=canonical_data["canonical_to_non_200_count"],
                affected_urls=[row["url"] for row in canonical_data.get("canonical_to_non_200", [])],
                recommendation="اجعل canonical يشير إلى صفحة 200 قابلة للفهرسة",
            )
        )

    if canonical_data.get("canonical_to_non_indexable_count", 0) > 0:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.HIGH,
                category="Technical",
                issue_type="Canonical to Non-Indexable URL",
                description=f"{canonical_data['canonical_to_non_indexable_count']} صفحة تشير إلى canonical غير قابل للفهرسة",
                affected_count=canonical_data["canonical_to_non_indexable_count"],
                affected_urls=[row["url"] for row in canonical_data.get("canonical_to_non_indexable", [])],
                recommendation="راجع noindex/robots/canonical للصفحة الهدف",
            )
        )

    if canonical_data.get("canonical_external_count", 0) > 0:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.HIGH,
                category="Technical",
                issue_type="External Canonicals",
                description=f"{canonical_data['canonical_external_count']} صفحة تشير canonical إلى نطاق خارجي",
                affected_count=canonical_data["canonical_external_count"],
                affected_urls=[row["url"] for row in canonical_data.get("canonical_external", [])],
                recommendation="تأكد أن canonical الخارجي مقصود، وإلا استخدم canonical داخلي",
            )
        )

    if canonical_data.get("canonical_chains_count", 0) > 0:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.MEDIUM,
                category="Technical",
                issue_type="Canonical Chains",
                description=f"{canonical_data['canonical_chains_count']} سلسلة canonical متعددة الخطوات",
                affected_count=canonical_data["canonical_chains_count"],
                affected_urls=[row["url"] for row in canonical_data.get("canonical_chains", [])],
                recommendation="اجعل كل صفحة تشير مباشرة إلى canonical النهائي",
            )
        )

    if url_issues.get("long_urls_count", 0) > 0:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.MEDIUM,
                category="Technical",
                issue_type="Long URLs",
                description=f"{url_issues['long_urls_count']} URL أطول من الحد الموصى به",
                affected_count=url_issues["long_urls_count"],
                affected_urls=[row["url"] for row in url_issues.get("long_urls", [])],
                recommendation="اختصر المسارات واجعلها وصفية وقابلة للقراءة",
            )
        )

    noisy_url_count = (
        url_issues.get("too_many_query_params_count", 0)
        + url_issues.get("tracking_params_count", 0)
        + url_issues.get("duplicate_paths_count", 0)
    )
    if noisy_url_count > 0:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.MEDIUM,
                category="Technical",
                issue_type="Noisy or Duplicate URL Patterns",
                description=f"{noisy_url_count} نمط URL قد يسبب تكراراً أو هدر crawl budget",
                affected_count=noisy_url_count,
                affected_urls=[
                    row["url"] for row in (
                        url_issues.get("too_many_query_params", [])
                        + url_issues.get("tracking_params", [])
                    )
                ],
                recommendation="نظّف المعاملات غير الضرورية واضبط canonical/robots للفلاتر والتتبع",
            )
        )

    # ========================================================
    # === 🔴 CRITICAL Issues ===
    # ========================================================

    # 1. صفحات 5xx
    if broken_data.get("pages_5xx_count", 0) > 0:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.CRITICAL,
                category="Technical",
                issue_type="Server Errors (5xx)",
                description=f"{broken_data['pages_5xx_count']} صفحة تُرجع أخطاء سيرفر",
                affected_count=broken_data["pages_5xx_count"],
                affected_urls=[p["url"] for p in broken_data.get("pages_5xx", [])],
                recommendation="افحص logs السيرفر وأصلح الأخطاء فوراً",
            )
        )

    # 2. صفحات 404 لها inlinks
    if broken_data.get("pages_404_with_inlinks_count", 0) > 0:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.CRITICAL,
                category="Technical",
                issue_type="404 Pages with Inlinks",
                description=f"{broken_data['pages_404_with_inlinks_count']} صفحة 404 لها روابط داخلية",
                affected_count=broken_data["pages_404_with_inlinks_count"],
                affected_urls=[p["url"] for p in broken_data.get("pages_404_with_inlinks", [])],
                recommendation="إما إصلاح الصفحة أو إضافة Redirect 301 + تحديث الروابط الداخلية",
            )
        )

    # 3. صفحات بـ NoIndex وأهمية عالية (depth منخفض)
    noindex_critical = [
        page for page in pages
        if not _get(page, "is_indexable", False)
        and "noindex" in (
            str(_get(page, "meta_robots", "") or "") + " "
            + str(_get(page, "x_robots_tag", "") or "")
        ).lower()
        and _int(page, "depth") <= 2
        and _status(page) == 200
    ]
    if noindex_critical:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.CRITICAL,
                category="Technical",
                issue_type="NoIndex on Important Pages",
                description=f"{len(noindex_critical)} صفحة مهمة (depth ≤ 2) عليها NoIndex",
                affected_count=len(noindex_critical),
                affected_urls=[_get(p, "url", "") for p in noindex_critical],
                recommendation="راجع أن NoIndex مقصود لهذه الصفحات",
            )
        )

    # 4. Redirect Loops
    if redirect_data.get("redirect_loops_count", 0) > 0:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.CRITICAL,
                category="Technical",
                issue_type="Redirect Loops",
                description=f"{redirect_data['redirect_loops_count']} حلقة redirect",
                affected_count=redirect_data["redirect_loops_count"],
                affected_urls=[r["original_url"] for r in redirect_data.get("redirect_loops", [])],
                recommendation="أصلح الـ redirects الدائرية فوراً (تمنع الزحف)",
            )
        )

    # === Mixed Content (جديد) ===
    pages_with_mixed = [
        p for p in pages
        if _get(p, "has_mixed_content", False) and _status(p) == 200
    ]
    pages_with_active_mixed = [
        p for p in pages
        if _int(p, "mixed_content_active_count") > 0
    ]
    pages_with_form_mixed = [
        p for p in pages
        if _int(p, "mixed_content_form_count") > 0
    ]

    # Form mixed = critical (يكشف بيانات حساسة)
    if pages_with_form_mixed:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.CRITICAL,
                category="Technical",
                issue_type="Insecure Form Submission (Mixed Content)",
                description=f"{len(pages_with_form_mixed)} صفحة فيها form يُرسل عبر HTTP",
                affected_count=len(pages_with_form_mixed),
                affected_urls=[_get(p, "url", "") for p in pages_with_form_mixed],
                recommendation="بيانات النماذج تُرسَل غير مشفّرة! غيّر action إلى HTTPS فوراً",
            )
        )

    # Active mixed = high (يحجبه المتصفح)
    if pages_with_active_mixed:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.HIGH,
                category="Technical",
                issue_type="Active Mixed Content",
                description=f"{len(pages_with_active_mixed)} صفحة فيها scripts/styles HTTP",
                affected_count=len(pages_with_active_mixed),
                affected_urls=[_get(p, "url", "") for p in pages_with_active_mixed],
                recommendation="المتصفحات تحجب هذه الموارد. حدّث الـ URLs إلى HTTPS",
            )
        )

    # Passive mixed = medium (تحذير من المتصفح)
    if pages_with_mixed and not pages_with_active_mixed and not pages_with_form_mixed:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.MEDIUM,
                category="Technical",
                issue_type="Passive Mixed Content",
                description=f"{len(pages_with_mixed)} صفحة فيها صور/فيديو HTTP",
                affected_count=len(pages_with_mixed),
                affected_urls=[_get(p, "url", "") for p in pages_with_mixed],
                recommendation="حدّث روابط الصور والفيديو إلى HTTPS",
            )
        )

    # 5. Title فارغ على صفحات قابلة للفهرسة
    empty_titles = [
        page for page in pages
        if _status(page) == 200 and not _get(page, "title", "") and _get(page, "is_indexable", False)
    ]
    if empty_titles:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.CRITICAL,
                category="On-Page",
                issue_type="Missing Title",
                description=f"{len(empty_titles)} صفحة بدون Title",
                affected_count=len(empty_titles),
                affected_urls=[_get(p, "url", "") for p in empty_titles],
                recommendation="أضف Title فريد لكل صفحة (30-60 حرف)",
            )
        )

    # ========================================================
    # === 🟠 HIGH Priority Issues ===
    # ========================================================

    # 6. Title مكرر
    if duplicate_data.get("duplicate_titles_count", 0) > 0:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.HIGH,
                category="On-Page",
                issue_type="Duplicate Titles",
                description=f"{duplicate_data['duplicate_titles_count']} مجموعة بنفس Title",
                affected_count=duplicate_data.get("pages_with_duplicate_title", 0),
                affected_urls=[
                    urls
                    for d in duplicate_data.get("duplicate_titles", [])[:5]
                    for urls in d["urls"]
                ],
                recommendation="اجعل كل Title فريداً",
            )
        )

    # 7. Meta Description مفقود
    no_desc = [
        page for page in pages
        if _status(page) == 200 and not _get(page, "meta_description", "") and _get(page, "is_indexable", False)
    ]
    if no_desc:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.HIGH,
                category="On-Page",
                issue_type="Missing Meta Description",
                description=f"{len(no_desc)} صفحة بدون Meta Description",
                affected_count=len(no_desc),
                affected_urls=[_get(p, "url", "") for p in no_desc],
                recommendation=f"أضف وصف فريد ({desc_min}-{desc_max} حرف) لكل صفحة",
            )
        )

    # 8. H1 مفقود
    no_h1 = [
        page for page in pages
        if _status(page) == 200 and _int(page, "h1_count") == 0 and _get(page, "is_indexable", False)
    ]
    if no_h1:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.HIGH,
                category="On-Page",
                issue_type="Missing H1",
                description=f"{len(no_h1)} صفحة بدون H1",
                affected_count=len(no_h1),
                affected_urls=[_get(p, "url", "") for p in no_h1],
                recommendation="أضف H1 واحد فريد لكل صفحة",
            )
        )

    # 9. H1 متعدد
    multiple_h1 = [
        page for page in pages
        if _status(page) == 200 and _int(page, "h1_count") > 1
    ]
    if multiple_h1:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.HIGH,
                category="On-Page",
                issue_type="Multiple H1",
                description=f"{len(multiple_h1)} صفحة فيها أكثر من H1",
                affected_count=len(multiple_h1),
                affected_urls=[_get(p, "url", "") for p in multiple_h1],
                recommendation="استخدم H1 واحد فقط لكل صفحة",
            )
        )

    # 10. Orphan Pages
    if orphan_data.get("orphan_count", 0) > 0:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.HIGH,
                category="Technical",
                issue_type="Orphan Pages",
                description=f"{orphan_data['orphan_count']} صفحة بدون inlinks داخلية",
                affected_count=orphan_data["orphan_count"],
                affected_urls=[p["url"] for p in orphan_data.get("orphan_pages", [])],
                recommendation="أضف روابط داخلية لهذه الصفحات من صفحات ذات صلة",
            )
        )

    # 11. Critical Thin Content
    if thin_content_data.get("critical_thin_count", 0) > 0:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.HIGH,
                category="Content",
                issue_type="Critical Thin Content",
                description=f"{thin_content_data['critical_thin_count']} صفحة بأقل من {thin_critical} كلمة",
                affected_count=thin_content_data["critical_thin_count"],
                affected_urls=[p["url"] for p in thin_content_data.get("critical_thin_pages", [])],
                recommendation=f"أضف محتوى ذي قيمة ({thin_threshold}+ كلمة موصى به)",
            )
        )

    # 12. صور بدون alt كثيرة
    if images_data.get("no_alt_count", 0) > 10:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.HIGH,
                category="On-Page",
                issue_type="Images Without Alt",
                description=f"{images_data['no_alt_count']} صورة بدون alt attribute",
                affected_count=images_data["no_alt_count"],
                affected_urls=list(set(img["page_url"] for img in images_data.get("no_alt", [])))[:30],
                recommendation="أضف alt وصفي لكل صورة (مهم للـ SEO والـ Accessibility)",
            )
        )

    # ========================================================
    # === 🟡 MEDIUM Priority Issues ===
    # ========================================================

    # 13. Title طويل جداً
    long_titles = [
        page for page in pages
        if _status(page) == 200 and _int(page, "title_length") > title_max
    ]
    if long_titles:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.MEDIUM,
                category="On-Page",
                issue_type="Title Too Long",
                description=f"{len(long_titles)} صفحة Title أطول من {title_max} حرف",
                affected_count=len(long_titles),
                affected_urls=[_get(p, "url", "") for p in long_titles],
                recommendation=f"اجعل Title أقصر من {title_max} حرف",
            )
        )

    # 14. Title قصير جداً
    short_titles = [
        page for page in pages
        if _status(page) == 200 and 0 < _int(page, "title_length") < title_min
    ]
    if short_titles:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.MEDIUM,
                category="On-Page",
                issue_type="Title Too Short",
                description=f"{len(short_titles)} صفحة Title أقصر من {title_min} حرف",
                affected_count=len(short_titles),
                affected_urls=[_get(p, "url", "") for p in short_titles],
                recommendation=f"اجعل Title بين {title_min}-{title_max} حرف",
            )
        )

    # 15. Description طويل
    long_desc = [
        page for page in pages
        if _status(page) == 200 and _int(page, "meta_description_length") > desc_max
    ]
    if long_desc:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.MEDIUM,
                category="On-Page",
                issue_type="Description Too Long",
                description=f"{len(long_desc)} صفحة وصف أطول من {desc_max} حرف",
                affected_count=len(long_desc),
                affected_urls=[_get(p, "url", "") for p in long_desc],
                recommendation=f"اجعل Description أقصر من {desc_max} حرف",
            )
        )

    # 16. Description قصير
    short_desc = [
        page for page in pages
        if _status(page) == 200 and 0 < _int(page, "meta_description_length") < desc_min
    ]
    if short_desc:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.MEDIUM,
                category="On-Page",
                issue_type="Description Too Short",
                description=f"{len(short_desc)} صفحة وصف أقصر من {desc_min} حرف",
                affected_count=len(short_desc),
                affected_urls=[_get(p, "url", "") for p in short_desc],
                recommendation=f"وسّع الـ Description ({desc_min}-{desc_max} حرف)",
            )
        )

    # 17. Redirect Chains
    if redirect_data.get("redirect_chains_count", 0) > 0:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.MEDIUM,
                category="Technical",
                issue_type="Redirect Chains",
                description=f"{redirect_data['redirect_chains_count']} سلسلة redirect (>1 hop)",
                affected_count=redirect_data["redirect_chains_count"],
                affected_urls=[r["original_url"] for r in redirect_data.get("redirect_chains", [])],
                recommendation="حدّث الروابط لتشير مباشرة للوجهة النهائية",
            )
        )

    # 18. Thin Content
    if thin_content_data.get("thin_content_count", 0) > 0:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.MEDIUM,
                category="Content",
                issue_type="Thin Content",
                description=f"{thin_content_data['thin_content_count']} صفحة بمحتوى رقيق (<{thin_threshold} كلمة)",
                affected_count=thin_content_data["thin_content_count"],
                affected_urls=[p["url"] for p in thin_content_data.get("thin_content_pages", [])[:30]],
                recommendation="وسّع المحتوى أو ادمج مع صفحات أخرى",
            )
        )

    # 19. صور بدون أبعاد
    if images_data.get("no_dimensions_count", 0) > 0:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.MEDIUM,
                category="Performance",
                issue_type="Images Without Dimensions",
                description=f"{images_data['no_dimensions_count']} صورة بدون width/height",
                affected_count=images_data["no_dimensions_count"],
                affected_urls=list(set(img["page_url"] for img in images_data.get("no_dimensions", [])))[:30],
                recommendation="أضف width و height لكل صورة (يمنع CLS)",
            )
        )

    # 20. Low Link Pages
    if orphan_data.get("low_link_count", 0) > 0:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.MEDIUM,
                category="Technical",
                issue_type="Low Internal Linking",
                description=f"{orphan_data['low_link_count']} صفحة بـ 1-2 inlinks فقط",
                affected_count=orphan_data["low_link_count"],
                affected_urls=[p["url"] for p in orphan_data.get("low_link_pages", [])[:30]],
                recommendation="عزّز الربط الداخلي لهذه الصفحات",
            )
        )

    # ========================================================
    # === 🟢 LOW Priority Issues ===
    # ========================================================

    # 21. صور بصيغ قديمة
    if images_data.get("legacy_formats_count", 0) > 0:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.LOW,
                category="Performance",
                issue_type="Legacy Image Formats",
                description=f"{images_data['legacy_formats_count']} صورة بصيغ قديمة (JPG/PNG)",
                affected_count=images_data["legacy_formats_count"],
                affected_urls=[],
                recommendation="حوّل إلى WebP أو AVIF لتوفير 25-50% من الحجم",
            )
        )

    # 22. صور بدون lazy loading
    if images_data.get("not_lazy_loaded_count", 0) > 5:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.LOW,
                category="Performance",
                issue_type="Images Without Lazy Loading",
                description=f"{images_data['not_lazy_loaded_count']} صورة بدون lazy loading",
                affected_count=images_data["not_lazy_loaded_count"],
                affected_urls=[],
                recommendation='أضف loading="lazy" للصور خارج الشاشة الأولى',
            )
        )

    # 23. صفحات عميقة جداً
    deep_pages = [
        page for page in pages
        if _status(page) == 200 and _int(page, "depth") > 4
    ]
    if deep_pages:
        issues.append(
            SEOIssue(
                severity=IssueSeverity.LOW,
                category="Technical",
                issue_type="Deep Pages",
                description=f"{len(deep_pages)} صفحة على عمق >4 من الرئيسية",
                affected_count=len(deep_pages),
                affected_urls=[_get(p, "url", "") for p in deep_pages[:30]],
                recommendation="حسّن البنية لتقليل العمق",
            )
        )

    # ========================================================
    # === تنظيم النتائج ===
    # ========================================================

    all_issues = [issue.to_dict() for issue in issues]

    by_severity = {
        IssueSeverity.CRITICAL.value: [],
        IssueSeverity.HIGH.value: [],
        IssueSeverity.MEDIUM.value: [],
        IssueSeverity.LOW.value: [],
    }
    by_category: dict[str, list] = {}

    for issue in issues:
        by_severity[issue.severity.value].append(issue.to_dict())
        by_category.setdefault(issue.category, []).append(issue.to_dict())

    return {
        "all_issues": all_issues,
        "by_severity": by_severity,
        "by_category": by_category,
        "summary": {
            "total_issues": len(issues),
            "critical_count": len(by_severity[IssueSeverity.CRITICAL.value]),
            "high_count": len(by_severity[IssueSeverity.HIGH.value]),
            "medium_count": len(by_severity[IssueSeverity.MEDIUM.value]),
            "low_count": len(by_severity[IssueSeverity.LOW.value]),
            "by_category_count": {cat: len(items) for cat, items in by_category.items()},
        },
    }
