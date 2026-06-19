"""
utils/url_classifier.py
=======================
v1.08: مصنّف URL — يقرّر هل الرابط «أساسي» (يُفحَص في Phase 1) أم «مؤجَّل»
(يُعدّ ويُحفَظ، ويُفحَص اختيارياً في Phase 2).

الفلسفة: لا نمنع المستخدم من المعلومات عن أنماط URL «الضوضائيّة» (Pagination
العميق، شاشات redirect، تركيبيات الفلاتر) — بل نُؤجّل فحصها مع إبراز عدّادها
في تقرير Phase 1، حتّى يقرّر هل تستحقّ زمن الفحص.

أنواع URL المُصنَّفة:
- sitemap        : موجود في sitemap (الأعلى أولويّة)
- navigation     : روابط القائمة الرئيسيّة / النصّ الافتتاحي (مكتشف ضمن أوّل صفحات)
- pagination_deep: ?page=N أو ?p=N حيث N > pagination_max
- redirect_wrapper: /auth/login?redirect_to=… أو /login?next=… (روابط شاشة تسجيل)
- filter_combination: تركيبات فلاتر متعدّدة (?filter[]=A&filter[]=B)
- other          : لا يطابق نمطاً معروفاً (يُفحَص — قد يكون قيّماً)

كلّ هذه عدا الأنواع الثلاثة الوسطى تُفحَص في Phase 1.
"""
from __future__ import annotations

from typing import Iterable, Optional
from urllib.parse import parse_qs, urlparse

# ── الأنواع ─────────────────────────────────────────────────────────────────
KIND_SITEMAP = "sitemap"
KIND_NAVIGATION = "navigation"
KIND_PAGINATION_DEEP = "pagination_deep"
KIND_REDIRECT_WRAPPER = "redirect_wrapper"
KIND_FILTER_COMBO = "filter_combination"
KIND_OTHER = "other"

# مسارات شاشات إعادة التوجيه الشائعة (Zid/Salla/Shopify/WC)
_REDIRECT_WRAPPER_PATHS = (
    "/auth/login", "/auth/register", "/auth/",
    "/login", "/signin", "/sign-in", "/sign_in",
    "/customer/account/login", "/account/login",
    "/wp-login.php",
)

# معاملات إعادة التوجيه (الموجودة في query بعد المسار)
_REDIRECT_PARAMS = ("redirect_to", "redirect", "next", "return_to",
                    "return_url", "continue", "url", "from")

# أسماء معاملات pagination الشائعة (لا تخلطها مع p=ID مثلاً)
_PAGINATION_PARAMS = ("page", "p", "pg", "pageno", "page_no")


class UrlClassifier:
    """مصنّف URL — يُهيَّأ مرّة واحدة في بداية الزحف، ويُستدعى لكلّ رابط مكتشف.

    Args:
        sitemap_urls: روابط sitemap (تُعتبر أساسيّة مهما حصل).
        navigation_urls: روابط القائمة/الفوتر (مكتشفة من الصفحة الرئيسيّة).
        pagination_max: أقصى عمق pagination للزحف في Phase 1. ?page=N حيث N أكبر
            من هذا يُعتبر مؤجَّلاً. 0 = لا حدّ (يفحص الكلّ).
        filter_max: أقصى عدد فلاتر متزامنة. تركيبيات أكثر تُعتبر مؤجَّلة.
    """

    def __init__(
        self,
        sitemap_urls: Optional[Iterable[str]] = None,
        navigation_urls: Optional[Iterable[str]] = None,
        pagination_max: int = 3,
        filter_max: int = 1,
    ):
        self.sitemap_set: set[str] = set(sitemap_urls or [])
        self.navigation_set: set[str] = set(navigation_urls or [])
        self.pagination_max = max(0, int(pagination_max))
        self.filter_max = max(0, int(filter_max))

    def classify(self, url: str) -> tuple[str, bool]:
        """يُرجع (kind, is_deferred) لرابط ما.

        is_deferred=True ⇒ لا يُضاف للطابور في Phase 1، يُحفَظ في deferred dict.
        """
        if not url:
            return (KIND_OTHER, False)
        if url in self.sitemap_set:
            return (KIND_SITEMAP, False)
        if url in self.navigation_set:
            return (KIND_NAVIGATION, False)

        try:
            parsed = urlparse(url)
        except (ValueError, TypeError):
            return (KIND_OTHER, False)

        path_lower = (parsed.path or "").lower()
        qs = parse_qs(parsed.query or "")

        # (أ) شاشات إعادة التوجيه — تظهر عادةً بـredirect_to=… بعد /auth/login
        for wrapper in _REDIRECT_WRAPPER_PATHS:
            if path_lower.startswith(wrapper):
                if any(p in qs for p in _REDIRECT_PARAMS):
                    return (KIND_REDIRECT_WRAPPER, True)
                # حتّى بلا redirect param، /auth/login نفسه إن وُجد في الطابور
                # نُؤجّله — لا يحوي محتوى SEO قيّماً
                return (KIND_REDIRECT_WRAPPER, True)

        # (ب) pagination عميق — نسمح بـ N <= pagination_max فقط
        if self.pagination_max > 0:
            for p in _PAGINATION_PARAMS:
                if p in qs:
                    try:
                        n = int(qs[p][0])
                        if n > self.pagination_max:
                            return (KIND_PAGINATION_DEEP, True)
                    except (ValueError, IndexError):
                        # قيمة غير رقميّة (`page=abc`) — لا نُؤجّلها، قد تكون اسم صفحة
                        pass

        # (ج) تركيبيات فلاتر — أكثر من filter_max فلتر متزامن
        filter_count = sum(
            1 for k in qs
            if k.startswith("filter") or k.endswith("[]") or k in ("category", "brand", "tag", "color", "size")
            and len(qs[k]) > 0
        )
        if self.filter_max > 0 and filter_count > self.filter_max:
            return (KIND_FILTER_COMBO, True)

        return (KIND_OTHER, False)

    # ─────────── أدوات للاختبار/التشخيص ───────────

    def update_sitemap(self, urls: Iterable[str]) -> None:
        self.sitemap_set.update(urls)

    def update_navigation(self, urls: Iterable[str]) -> None:
        self.navigation_set.update(urls)


# ───────────── أداة مساعدة عامّة (بلا حالة) للتصنيف السريع ─────────────

def classify_url(
    url: str,
    sitemap_urls: Optional[Iterable[str]] = None,
    pagination_max: int = 3,
) -> tuple[str, bool]:
    """نسخة بلا state — للحالات التي لا تحتاج فيها لكاش navigation."""
    return UrlClassifier(
        sitemap_urls=sitemap_urls, pagination_max=pagination_max,
    ).classify(url)
