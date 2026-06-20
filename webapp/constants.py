"""
webapp/constants.py — ثوابت + جداول i18n للواجهة المرئية.

نُقلت من webapp/app.py في v1.12.3 (REFACTOR-app-routers الخطوة الأولى:
ثوابت بحتة، لا منطق، تُستخدم من routers متعدّدة + من main.py).
"""

from __future__ import annotations

from pathlib import Path

EXTRACTION_GROUPS = [
    {"id": "content", "label": "الميتا والمحتوى", "items": [
        {"key": "meta", "label": "الوسوم الوصفية (Title/Description/Robots)"},
        {"key": "headings", "label": "العناوين (H1–H6)"},
        {"key": "content", "label": "المحتوى وعدد الكلمات"},
        {"key": "canonical", "label": "Canonical"},
    ]},
    {"id": "links_media", "label": "الروابط والوسائط", "items": [
        {"key": "links", "label": "الروابط (داخلية/خارجية)"},
        {"key": "images", "label": "الصور و alt"},
    ]},
    {"id": "social", "label": "السوشال والبيانات المنظمة", "items": [
        {"key": "og", "label": "Open Graph / Twitter"},
        {"key": "hreflang", "label": "Hreflang"},
        {"key": "pagination", "label": "ترقيم الصفحات (rel=next/prev)"},
        {"key": "schema", "label": "Schema.org"},
    ]},
    {"id": "technical", "label": "التقني والأمان", "items": [
        {"key": "headers", "label": "ترويسات HTTP"},
        {"key": "mixed_content", "label": "المحتوى المختلط (Mixed Content)"},
        {"key": "resources", "label": "جرد الموارد (CSS/JS/خطوط/iframe)"},
    ]},
]

OUTPUT_FORMATS = [
    {"key": "html", "label": "HTML", "default": True},
    {"key": "pdf", "label": "PDF", "default": True},
    {"key": "excel", "label": "Excel", "default": True},
    {"key": "csv", "label": "CSV", "default": True},
    {"key": "json", "label": "JSON", "default": True},
    {"key": "xml", "label": "XML", "default": False},
]

SECTIONS = [
    {"key": "cover", "label": "الغلاف"},
    {"key": "summary", "label": "الملخص التنفيذي"},
    {"key": "issues", "label": "المشاكل حسب الأولوية"},
    {"key": "problem_pages", "label": "صفحات بمشاكل"},
    {"key": "redirects", "label": "التحويلات"},
    {"key": "schema", "label": "Schema.org"},
]
SEVERITIES = ["🔴 Critical", "🟠 High", "🟡 Medium", "🟢 Low"]

# v1.05: انتحال User-Agent لكشف مشاكل خاصّة بـbots (Cloudflare/WAF challenges)
# الـUA الافتراضي «SEOCrawlerBot/1.0» (في crawler/http_client.py) يبقى عند `ua_preset=""`.
UA_PRESETS = {
    "googlebot": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "googlebot-mobile": (
        "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.6099.118 Mobile Safari/537.36 "
        "(compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    ),
    "bingbot": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
}

# سقف حجم ملف audit JSON الذي نحمّله في الذاكرة (المستكشف/إعادة بناء التقرير).
# يمنع تعليق الخادم عند فتح أرشيف ضخم (مثل 1.7GB من زحف غير محدود قديم).
MAX_AUDIT_JSON_MB = 300

# تسميات معبّرة (عربي/إنجليزي) لملفات CSV المختصّة — تُعرض في لوحة النتائج.
CSV_LABELS: dict[str, dict[str, str]] = {
    "pages": {"ar": "كل الصفحات المزحوفة", "en": "All crawled pages"},
    "all_links": {"ar": "كل الروابط (شبكة الروابط)", "en": "All links (link graph)"},
    "inlinks": {"ar": "الروابط الواردة الداخلية", "en": "Internal inlinks"},
    "outlinks_external": {"ar": "الروابط الصادرة الخارجية", "en": "External outlinks"},
    "images": {"ar": "كل الصور", "en": "All images"},
    "images_no_alt": {"ar": "صور بلا نص بديل (alt)", "en": "Images missing alt text"},
    "images_no_dimensions": {"ar": "صور بلا أبعاد صريحة", "en": "Images missing dimensions"},
    "headings": {"ar": "العناوين H1–H6", "en": "Headings (H1–H6)"},
    "headers": {"ar": "ترويسات HTTP", "en": "HTTP response headers"},
    "schema": {"ar": "البيانات المنظّمة Schema.org", "en": "Schema.org structured data"},
    "redirects": {"ar": "التحويلات", "en": "Redirects"},
    "redirect_chains": {"ar": "سلاسل التحويل", "en": "Redirect chains"},
    "redirect_loops": {"ar": "حلقات التحويل", "en": "Redirect loops"},
    "redirect_issues": {"ar": "مشاكل التحويلات", "en": "Redirect issues"},
    "seo_issues": {"ar": "كل مشاكل SEO (حسب الأولوية)", "en": "All SEO issues (by priority)"},
    "duplicates": {"ar": "محتوى مكرّر (عناوين/أوصاف/H1)", "en": "Duplicate content (titles/desc/H1)"},
    "orphans": {"ar": "صفحات يتيمة", "en": "Orphan pages"},
    "low_link_pages": {"ar": "صفحات قليلة الروابط الداخلية", "en": "Pages with few internal links"},
    "thin_content": {"ar": "محتوى رقيق", "en": "Thin‑content pages"},
    "pages_4xx": {"ar": "صفحات أخطاء 4xx", "en": "4xx error pages"},
    "pages_5xx": {"ar": "صفحات أخطاء 5xx", "en": "5xx error pages"},
    "pages_404_with_inlinks": {"ar": "صفحات 404 بروابط واردة", "en": "404 pages with inlinks"},
    "url_issues": {"ar": "مشاكل الروابط (URL)", "en": "URL issues"},
    "canonical_issues": {"ar": "مشاكل Canonical", "en": "Canonical issues"},
    "security_issues": {"ar": "مشاكل ترويسات الأمان", "en": "Security header issues"},
    "pagination": {"ar": "ترقيم الصفحات (next/prev)", "en": "Pagination (next/prev)"},
    "pagination_issues": {"ar": "مشاكل ترقيم الصفحات", "en": "Pagination issues"},
    "hreflang_issues": {"ar": "مشاكل hreflang", "en": "Hreflang issues"},
    "resources": {"ar": "جرد الموارد", "en": "Resource inventory"},
    "resource_issues": {"ar": "مشاكل الموارد", "en": "Resource issues"},
    "resource_status": {"ar": "حالة HTTP للموارد", "en": "Resource HTTP status"},
    "excluded_urls": {"ar": "روابط مستبعَدة (مع السبب)", "en": "Excluded URLs (with reason)"},
    "priority_opportunities": {"ar": "أولويات الإصلاح", "en": "Priority opportunities"},
    "ai_recommendations": {"ar": "توصيات الذكاء الاصطناعي", "en": "AI recommendations"},
    "gsc_pages": {"ar": "GSC — صفحات", "en": "GSC — pages"},
    "gsc_queries": {"ar": "GSC — استعلامات", "en": "GSC — queries"},
    "ga4_landing_pages": {"ar": "GA4 — صفحات الهبوط", "en": "GA4 — landing pages"},
    "ga4_channels": {"ar": "GA4 — القنوات", "en": "GA4 — channels"},
    "lighthouse_import": {"ar": "استيراد Lighthouse", "en": "Lighthouse import"},
    "js_diff": {"ar": "فرق التصيير (خام↔مُصيَّر)", "en": "JS render diff (raw↔rendered)"},
    "custom_extraction": {"ar": "الاستخراج المخصّص", "en": "Custom extraction"},
}


def label_for(rel: str, lang: str = "ar") -> str:
    """تسمية معبّرة لملف ناتج حسب مساره النسبي."""
    name = Path(rel).name
    stem = Path(name).stem
    low = name.lower()
    if rel.startswith("csv/") and stem in CSV_LABELS:
        return CSV_LABELS[stem][lang]
    if low.endswith(".json"):
        return "الأرشيف الكامل (JSON)" if lang == "ar" else "Full audit archive (JSON)"
    if low.endswith(".xlsx"):
        return "مصنّف Excel" if lang == "ar" else "Excel workbook"
    if "_client" in low and low.endswith(".html"):
        return "تقرير العميل (HTML)" if lang == "ar" else "Client report (HTML)"
    if "_client" in low and low.endswith(".pdf"):
        return "تقرير العميل (PDF)" if lang == "ar" else "Client report (PDF)"
    if "_expert" in low and low.endswith(".html"):
        return "تقرير الخبير (HTML)" if lang == "ar" else "Expert report (HTML)"
    if "_expert" in low and low.endswith(".pdf"):
        return "تقرير الخبير (PDF)" if lang == "ar" else "Expert report (PDF)"
    if low.endswith(".html"):
        return "التقرير (HTML)" if lang == "ar" else "Report (HTML)"
    if low.endswith(".pdf"):
        return "التقرير (PDF)" if lang == "ar" else "Report (PDF)"
    if rel.startswith("xml/"):
        return f"XML — {stem}"
    if rel.startswith("csv/"):
        return stem.replace("_", " ")
    return name
