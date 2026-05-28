"""
analyzers/hints.py
==================
إثراء مشاكل SEO بـ«تلميحات» قابلة للتنفيذ (IMP-8): لكل مشكلة نضيف الأثر المتوقّع، والجهد
التقديري، و«لماذا تهم» و«كيف تُصلَح» — فيصبح تقرير العميل قابلاً للتنفيذ ومرتّباً بالأولوية
(أثر ÷ جهد) بدل قائمة مشاكل جافّة.

التلميحات تُشتقّ من نوع المشكلة عبر مطابقة كلمات مفتاحية (عربية/إنجليزية)، مع احتياطي يعتمد
على شدّة المشكلة. لا يستبدل الفحوص الحتمية — يُضيف سياقاً فقط.
"""

from __future__ import annotations

from typing import Any

_IMPACT_WEIGHT = {"high": 3, "medium": 2, "low": 1}
_EFFORT_WEIGHT = {"low": 1, "medium": 2, "high": 3}
_SEVERITY_IMPACT = {
    "🔴 Critical": "high", "🟠 High": "high",
    "🟡 Medium": "medium", "🟢 Low": "low",
}

# (كلمات مفتاحية في issue_type) -> (impact, effort, why, how)
# الترتيب مهم: أول تطابق يفوز.
_CATALOG: list[tuple[tuple[str, ...], str, str, str, str]] = [
    (("broken", "404", "مكسور", "معطّل"), "high", "low",
     "الروابط المكسورة تُهدر ميزانية الزحف وتُسيء لتجربة المستخدم وإشارات الجودة.",
     "أصلِح أو وجّه (301) كل رابط مكسور إلى بديل مناسب، وأزِل الإشارات الميتة."),
    (("redirect", "chain", "تحويل", "توجيه"), "medium", "low",
     "سلاسل التحويل تُبطئ التحميل وتُضعف تمرير قيمة الروابط.",
     "اجعل كل تحويل قفزة واحدة مباشرة إلى الوجهة النهائية (301)."),
    (("canonical", "قانون", "كانونيكال"), "high", "low",
     "Canonical الخاطئ قد يمنع فهرسة الصفحة الصحيحة أو يشتّت الإشارات.",
     "اضبط canonical ليشير إلى النسخة المفضّلة الذاتية لكل صفحة."),
    (("duplicate", "مكرر", "تكرار"), "medium", "medium",
     "المحتوى/العناوين المكررة تشتّت الترتيب بين صفحات متشابهة.",
     "وحّد المحتوى المكرر أو ميّزه بعناوين/أوصاف فريدة أو canonical."),
    (("title", "عنوان"), "high", "low",
     "العنوان أقوى إشارة على الصفحة وأبرز ما يظهر في نتائج البحث.",
     "اكتب عنواناً فريداً وصفياً (~50–60 محرفاً) لكل صفحة."),
    (("description", "meta", "وصف"), "medium", "low",
     "وصف الميتا يؤثّر في نسبة النقر من نتائج البحث.",
     "اكتب وصفاً فريداً جذاباً (~120–160 محرفاً) يلخّص الصفحة."),
    (("thin", "content", "ضعيف", "محتوى"), "medium", "high",
     "المحتوى الضعيف لا يلبّي نيّة البحث وقد يُصنَّف منخفض القيمة.",
     "وسّع المحتوى ليغطّي الموضوع بعمق ويجيب أسئلة المستخدم."),
    (("image", "alt", "صور", "بديل"), "medium", "low",
     "نص alt المفقود يضرّ الوصولية وفهم محركات البحث للصور.",
     "أضِف نص alt وصفياً موجزاً لكل صورة ذات معنى."),
    (("orphan", "يتيم", "inlink", "روابط داخلية"), "high", "medium",
     "الصفحات اليتيمة يصعب اكتشافها وترتيبها لغياب الروابط الداخلية.",
     "اربط الصفحات المهمّة من تنقّل/صفحات ذات صلة بروابط داخلية وصفية."),
    (("hreflang", "lang", "لغة"), "medium", "medium",
     "hreflang الخاطئ يُربك استهداف اللغة/المنطقة في البحث.",
     "اضبط hreflang المتبادل والصحيح بين النسخ اللغوية."),
    (("speed", "performance", "lcp", "cls", "أداء", "سرعة"), "high", "high",
     "بطء التحميل يضرّ التحويل وترتيب البحث (Core Web Vitals).",
     "حسّن الصور والسكربتات والتخزين المؤقّت وقلّل ما يحجب العرض."),
    (("https", "mixed", "security", "أمان"), "high", "low",
     "مشاكل HTTPS/المحتوى المختلط تضرّ الثقة والأمان وقد تُحذّر المتصفّحات.",
     "قدّم كل الموارد عبر HTTPS وأزِل أي مرجع http مختلط."),
]


def _hint_for(issue_type: str, severity: str) -> dict[str, str]:
    t = (issue_type or "").lower()
    for keywords, impact, effort, why, how in _CATALOG:
        if any(k.lower() in t for k in keywords):
            return {"impact": impact, "effort": effort, "why": why, "how": how}
    # احتياطي: الأثر من الشدّة، الجهد متوسط
    return {
        "impact": _SEVERITY_IMPACT.get(severity, "medium"),
        "effort": "medium",
        "why": "",
        "how": "",
    }


def _priority_score(impact: str, effort: str) -> float:
    return round(_IMPACT_WEIGHT.get(impact, 2) / _EFFORT_WEIGHT.get(effort, 2), 2)


def _enrich_issue(issue: dict[str, Any]) -> dict[str, Any]:
    h = _hint_for(issue.get("issue_type", ""), issue.get("severity", ""))
    issue["impact"] = h["impact"]
    issue["effort"] = h["effort"]
    issue["why_it_matters"] = h["why"]
    issue["how_to_fix"] = h["how"]
    issue["priority_score"] = _priority_score(h["impact"], h["effort"])
    return issue


def attach_hints(seo_issues: dict[str, Any]) -> dict[str, Any]:
    """يُضيف impact/effort/why/how/priority_score لكل مشكلة عبر كل القوائم."""
    if not isinstance(seo_issues, dict):
        return seo_issues
    for issue in seo_issues.get("all_issues", []) or []:
        if isinstance(issue, dict):
            _enrich_issue(issue)
    for lst in (seo_issues.get("by_severity", {}) or {}).values():
        for issue in lst or []:
            if isinstance(issue, dict):
                _enrich_issue(issue)
    for lst in (seo_issues.get("by_category", {}) or {}).values():
        for issue in lst or []:
            if isinstance(issue, dict):
                _enrich_issue(issue)
    return seo_issues
