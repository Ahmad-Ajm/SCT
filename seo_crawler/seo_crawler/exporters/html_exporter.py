"""
exporters/html_exporter.py
===========================
مُصدّر تقرير HTML احترافي وقابل للتخصيص (مصدر تقرير الـ PDF أيضاً).

- مستقل تماماً (لا يعتمد على Jinja2) — يبني HTML بـ Python وتهريب آمن.
- يدعم العربية/RTL والإنجليزية.
- خيارات تخصيص: اسم العميل، الشعار، اللغة، الأقسام، فلتر الخطورة، حدّ الصفوف.

الاستخدام:
    exporter = HTMLReportExporter(output_dir)
    path = exporter.export(audit_dict, options)
حيث audit_dict هو محتوى complete_audit.json (أو نفس الـ datasets).
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.logger import get_logger

log = get_logger(__name__)


DEFAULT_SECTIONS = ["cover", "summary", "opportunities", "issues", "problem_pages",
                    "search_visibility", "user_behavior", "redirects", "schema"]

# تقرير العميل: لغة مبسّطة + تقييم عام + أهم الفرص والمشاكل (بلا جداول تقنية عميقة).
CLIENT_SECTIONS = ["cover", "health", "summary", "ai", "opportunities", "issues"]

# تقرير الخبير: كل التفاصيل التقنية (يشمل أقسام الترقيم/hreflang/الموارد الجديدة).
EXPERT_SECTIONS = ["cover", "summary", "ai", "opportunities", "action_board", "issues",
                   "problem_pages", "search_visibility", "user_behavior", "redirects",
                   "pagination", "hreflang", "resources", "schema"]

# تسميات مجموعات لوحة العمل (Action Board)
_ACTION_GROUP_LABELS = {
    "do_now": ("افعل الآن", "Do now"),
    "needs_content": ("يحتاج محتوى", "Needs content"),
    "needs_developer": ("يحتاج مطوّراً", "Needs developer"),
    "needs_platform": ("يحتاج دعم المنصّة", "Needs platform support"),
    "do_later": ("افعل لاحقاً", "Do later"),
    "low_impact": ("منخفض الأثر", "Low impact"),
}
_ACTION_GROUP_ORDER = ["do_now", "needs_content", "needs_developer",
                       "needs_platform", "do_later", "low_impact"]

_SEVERITY_ORDER = ["🔴 Critical", "🟠 High", "🟡 Medium", "🟢 Low"]

_LABELS = {
    "ar": {
        "title": "تقرير تدقيق SEO",
        "generated": "تاريخ التقرير",
        "site": "الموقع",
        "pages": "الصفحات المزحوفة",
        "indexable": "قابلة للفهرسة",
        "issues": "إجمالي المشاكل",
        "summary": "الملخص التنفيذي",
        "issues_h": "المشاكل حسب الأولوية",
        "problem_pages": "أبرز الصفحات بمشاكل",
        "redirects": "التحويلات (Redirects)",
        "schema": "Schema.org",
        "affected": "المتأثرة",
        "recommendation": "التوصية",
        "url": "الرابط",
        "status": "الحالة",
        "title_col": "العنوان",
        "no_issues": "لا توجد مشاكل في هذه الفئة 🎉",
        "dir": "rtl",
        "lang": "ar",
    },
    "en": {
        "title": "SEO Audit Report",
        "generated": "Report date",
        "site": "Site",
        "pages": "Pages crawled",
        "indexable": "Indexable",
        "issues": "Total issues",
        "summary": "Executive summary",
        "issues_h": "Issues by priority",
        "problem_pages": "Top problem pages",
        "redirects": "Redirects",
        "schema": "Schema.org",
        "affected": "Affected",
        "recommendation": "Recommendation",
        "url": "URL",
        "status": "Status",
        "title_col": "Title",
        "no_issues": "No issues in this category 🎉",
        "dir": "ltr",
        "lang": "en",
    },
}

_SEVERITY_CLASS = {
    "🔴 Critical": "crit",
    "🟠 High": "high",
    "🟡 Medium": "med",
    "🟢 Low": "low",
}


def _e(value: Any) -> str:
    """تهريب HTML آمن."""
    return html.escape(str(value if value is not None else ""))


class HTMLReportExporter:
    def __init__(self, output_dir: str, filename: str = "report.html"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.file_path = self.output_dir / filename

    def export(self, audit: dict[str, Any], options: dict[str, Any] | None = None) -> str:
        options = options or {}
        lang = options.get("language", "ar")
        L = _LABELS.get(lang, _LABELS["ar"])
        # الجمهور المستهدف: client (مبسّط) | expert (تفصيلي) | both (يُعالَج في report_builder)
        audience = (options.get("audience") or "expert").lower()
        if audience == "client":
            sections = CLIENT_SECTIONS
        else:
            sections = options.get("sections") or EXPERT_SECTIONS
        severity_filter = options.get("severity_filter") or _SEVERITY_ORDER
        max_rows = int(options.get("max_rows", 100))
        if audience == "client":
            max_rows = min(max_rows, 25)  # تقرير العميل مختصر
        client_name = options.get("client_name", "")
        logo_url = options.get("logo_url", "")

        try:
            body_parts: list[str] = []
            if "cover" in sections:
                body_parts.append(self._cover(audit, L, client_name, logo_url, audience))
            if "health" in sections:
                body_parts.append(self._health(audit, L))
            if "summary" in sections:
                body_parts.append(self._summary(audit, L))
            if "ai" in sections:
                body_parts.append(self._ai(audit, L))
            if "opportunities" in sections:
                body_parts.append(self._opportunities(audit, L, max_rows))
            if "action_board" in sections:
                body_parts.append(self._action_board(audit, L, max_rows))
            if "issues" in sections:
                body_parts.append(self._issues(audit, L, severity_filter, plain=(audience == "client")))
            if "problem_pages" in sections:
                body_parts.append(self._problem_pages(audit, L, max_rows))
            if "search_visibility" in sections:
                body_parts.append(self._search_visibility(audit, L, max_rows))
            if "user_behavior" in sections:
                body_parts.append(self._user_behavior(audit, L, max_rows))
            if "redirects" in sections:
                body_parts.append(self._redirects(audit, L, max_rows))
            if "pagination" in sections:
                body_parts.append(self._pagination(audit, L, max_rows))
            if "hreflang" in sections:
                body_parts.append(self._hreflang(audit, L, max_rows))
            if "resources" in sections:
                body_parts.append(self._resources(audit, L, max_rows))
            if "schema" in sections:
                body_parts.append(self._schema(audit, L))

            doc = self._wrap(L, "\n".join(p for p in body_parts if p))
            with open(self.file_path, "w", encoding="utf-8") as f:
                f.write(doc)
            log.info(f"تم حفظ تقرير HTML: {self.file_path}")
            return str(self.file_path)
        except Exception as e:
            log.error(f"فشل تصدير HTML: {e}", exc_info=True)
            return ""

    # ------------------------------------------------------------------
    def _wrap(self, L: dict[str, str], body: str) -> str:
        return f"""<!DOCTYPE html>
<html lang="{L['lang']}" dir="{L['dir']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(L['title'])}</title>
<style>{_CSS}</style>
</head>
<body>
{body}
<footer class="ftr">Generated by SCT — Simple Crawler Tool</footer>
</body>
</html>"""

    def _cover(self, audit, L, client_name, logo_url, audience="expert") -> str:
        site = audit.get("site_config", {}) or {}
        site_url = site.get("start_url", "") or audit.get("mode", "")
        logo = f'<img class="logo" src="{_e(logo_url)}" alt="logo">' if logo_url else ""
        client = f'<div class="client">{_e(client_name)}</div>' if client_name else ""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        ar = L["lang"] == "ar"
        kind = ("" if audience == "expert" else
                ("تقرير مختصر للعميل" if ar else "Client summary report"))
        kind_html = f'<div class="kind">{_e(kind)}</div>' if kind else ""
        return f"""<section class="cover">
{logo}
<h1>{_e(L['title'])}</h1>
{kind_html}
{client}
<div class="site">{_e(L['site'])}: {_e(site_url)}</div>
<div class="date">{_e(L['generated'])}: {_e(now)}</div>
</section>"""

    def _health(self, audit, L) -> str:
        """تقييم عام مبسّط للعميل (0–100) بلغة واضحة + أهم فئات المشاكل."""
        ar = L["lang"] == "ar"
        pages = audit.get("pages", []) or []
        total_pages = len(pages) or 1
        summary = (audit.get("seo_issues", {}) or {}).get("summary", {}) or {}
        crit = int(summary.get("critical_count", 0) or 0)
        high = int(summary.get("high_count", 0) or 0)
        med = int(summary.get("medium_count", 0) or 0)
        low = int(summary.get("low_count", 0) or 0)
        # كثافة مشاكل مرجّحة لكل صفحة → درجة صحّة
        weighted = crit * 3 + high * 2 + med * 1 + low * 0.25
        score = max(0, min(100, round(100 - (weighted / total_pages) * 8)))
        if score >= 90:
            label, cls = ("ممتاز" if ar else "Excellent"), "low"
        elif score >= 75:
            label, cls = ("جيد" if ar else "Good"), "low"
        elif score >= 50:
            label, cls = ("متوسط" if ar else "Fair"), "med"
        elif score >= 25:
            label, cls = ("ضعيف" if ar else "Poor"), "high"
        else:
            label, cls = ("حرج" if ar else "Critical"), "crit"
        title = "التقييم العام للموقع" if ar else "Overall site health"
        # أهم 3 فئات مشاكل بلغة واضحة
        by_sev = (audit.get("seo_issues", {}) or {}).get("by_severity", {}) or {}
        top: list[tuple[str, int]] = []
        for sev in _SEVERITY_ORDER:
            for it in (by_sev.get(sev, []) or []):
                top.append((it.get("issue_type", ""), int(it.get("affected_count", 0) or 0)))
        top.sort(key=lambda x: -x[1])
        intro = ("هذا تقييم عام لصحّة الموقع من ناحية تحسين محركات البحث. كلما ارتفعت الدرجة "
                 "قلّت المشاكل التي قد تؤثّر على ظهورك في نتائج البحث."
                 if ar else
                 "This is an overall SEO health rating. A higher score means fewer issues "
                 "that could affect your visibility in search results.")
        items = "".join(
            f'<li>{_e(name)} — {_e(cnt)} {"صفحة" if ar else "pages"}</li>'
            for name, cnt in top[:3] if name
        )
        top_html = (f'<p>{"أبرز ما يُنصح بمعالجته:" if ar else "Top areas to address:"}</p>'
                    f'<ul class="plain">{items}</ul>') if items else ""
        return (f'<section><h2>{_e(title)}</h2>'
                f'<div class="health"><div class="score {cls}">{_e(score)}<span>/100</span></div>'
                f'<div class="grade {cls}">{_e(label)}</div></div>'
                f'<p class="muted">{_e(intro)}</p>{top_html}</section>')

    def _ai(self, audit, L) -> str:
        ai = audit.get("ai_analysis", {}) or {}
        if not ai or not ai.get("enabled"):
            return ""
        ar = L["lang"] == "ar"
        title = "تحليل الذكاء الاصطناعي وتوصياته" if ar else "AI analysis & recommendations"
        if ai.get("error"):
            hint = ({"missing_api_key": "لم يُضبط مفتاح API.",
                     "missing_base_url": "لم يُضبط عنوان الخدمة (base_url).",
                     "missing_model": "لم يُحدّد النموذج.",
                     "requests_not_installed": "مكتبة requests غير مثبّتة."}.get(ai["error"],
                    f"تعذّر التحليل: {ai['error']}")
                    if ar else f"AI analysis unavailable: {ai['error']}")
            return f'<section><h2>🤖 {_e(title)}</h2><p class="muted">{_e(hint)}</p></section>'
        prov = f'{ai.get("provider","")} · {ai.get("model","")}'
        summary = ai.get("summary", "") or ""
        recs = ai.get("recommendations", []) or []
        rec_html = ""
        if recs:
            items = ""
            for r in recs:
                if not isinstance(r, dict):
                    items += f'<li>{_e(r)}</li>'
                    continue
                pr = str(r.get("priority", "")).lower()
                cls = {"high": "high", "medium": "med", "low": "low"}.get(pr, "")
                why = r.get("why", "")
                action = r.get("action", "")
                items += (
                    f'<li><span class="sev {cls}" style="margin:0 0 4px">{_e(r.get("priority",""))}</span> '
                    f'<b>{_e(r.get("title",""))}</b>'
                    + (f'<div class="muted sm">{_e(why)}</div>' if why else "")
                    + (f'<div class="sm">{_e(action)}</div>' if action else "")
                    + '</li>'
                )
            rec_html = f'<ul class="plain ai-recs">{items}</ul>'
        return (f'<section><h2>🤖 {_e(title)}</h2>'
                f'<p class="muted sm">{_e(prov)}</p>'
                f'<p>{_e(summary)}</p>{rec_html}</section>')

    def _summary(self, audit, L) -> str:
        pages = audit.get("pages", []) or []
        total_pages = len(pages)
        indexable = sum(1 for p in pages if _val(p, "is_indexable"))
        summary = (audit.get("seo_issues", {}) or {}).get("summary", {}) or {}
        total_issues = summary.get("total_issues", 0)
        cards = [
            (L["pages"], total_pages, ""),
            (L["indexable"], indexable, ""),
            (L["issues"], total_issues, ""),
            ("🔴", summary.get("critical_count", 0), "crit"),
            ("🟠", summary.get("high_count", 0), "high"),
            ("🟡", summary.get("medium_count", 0), "med"),
            ("🟢", summary.get("low_count", 0), "low"),
        ]
        cells = "".join(
            f'<div class="card {cls}"><div class="num">{_e(v)}</div>'
            f'<div class="lbl">{_e(lbl)}</div></div>'
            for lbl, v, cls in cards
        )
        return f'<section><h2>{_e(L["summary"])}</h2><div class="cards">{cells}</div></section>'

    def _issues(self, audit, L, severity_filter, plain=False) -> str:
        by_sev = (audit.get("seo_issues", {}) or {}).get("by_severity", {}) or {}
        blocks = []
        for sev in _SEVERITY_ORDER:
            if sev not in severity_filter:
                continue
            items = by_sev.get(sev, []) or []
            cls = _SEVERITY_CLASS.get(sev, "")
            if not items:
                continue
            rows = ""
            for it in items:
                if plain:
                    # تقرير العميل: بلا عيّنات روابط تقنية — وصف وتوصية فقط
                    rows += (
                        f'<tr><td><b>{_e(it.get("issue_type",""))}</b><br>'
                        f'<span class="muted">{_e(it.get("description",""))}</span></td>'
                        f'<td class="ctr">{_e(it.get("affected_count",0))}</td>'
                        f'<td>{_e(it.get("recommendation",""))}</td></tr>'
                    )
                else:
                    urls = it.get("affected_urls_sample", []) or []
                    sample = "<br>".join(_e(u) for u in urls[:5])
                    rows += (
                        f'<tr><td><b>{_e(it.get("issue_type",""))}</b><br>'
                        f'<span class="muted">{_e(it.get("description",""))}</span></td>'
                        f'<td class="ctr">{_e(it.get("affected_count",0))}</td>'
                        f'<td>{_e(it.get("recommendation",""))}<div class="muted sm">{sample}</div></td></tr>'
                    )
            blocks.append(
                f'<h3 class="sev {cls}">{_e(sev)} '
                f'<span class="badge">{len(items)}</span></h3>'
                f'<table class="tbl"><thead><tr>'
                f'<th>{_e(L["issues"])}</th><th>{_e(L["affected"])}</th>'
                f'<th>{_e(L["recommendation"])}</th></tr></thead><tbody>{rows}</tbody></table>'
            )
        body = "\n".join(blocks) or f'<p class="muted">{_e(L["no_issues"])}</p>'
        return f'<section><h2>{_e(L["issues_h"])}</h2>{body}</section>'

    def _pagination(self, audit, L, max_rows) -> str:
        pg = audit.get("pagination_data", {}) or {}
        if not pg or not pg.get("total_paginated"):
            return ""
        ar = L["lang"] == "ar"
        title = "ترقيم الصفحات (rel=next/prev)" if ar else "Pagination (rel=next/prev)"
        issues = pg.get("issues", []) or []
        note = (f'{pg.get("total_paginated", 0)} صفحة مرقّمة · {len(issues)} مشكلة'
                if ar else
                f'{pg.get("total_paginated", 0)} paginated pages · {len(issues)} issues')
        table = ""
        if issues:
            hdr = ("الرابط", "المشكلة", "التفصيل") if ar else ("URL", "Issue", "Detail")
            h = "".join(f"<th>{_e(x)}</th>" for x in hdr)
            rows = "".join(
                f'<tr><td>{_e(i.get("page_url"))}</td><td>{_e(i.get("issue"))}</td>'
                f'<td class="muted sm">{_e(i.get("detail"))}</td></tr>'
                for i in issues[:max_rows])
            table = f'<table class="tbl"><thead><tr>{h}</tr></thead><tbody>{rows}</tbody></table>'
        return f'<section><h2>{_e(title)}</h2><p class="muted">{_e(note)}</p>{table}</section>'

    def _hreflang(self, audit, L, max_rows) -> str:
        hv = audit.get("hreflang_validation", {}) or {}
        if not hv or not hv.get("total_pages_with_hreflang"):
            return ""
        ar = L["lang"] == "ar"
        title = "Hreflang (المواقع متعددة اللغات)" if ar else "Hreflang (international)"
        cats = [
            ("non_reciprocal", "غير متبادل" if ar else "Non-reciprocal"),
            ("points_to_404", "يشير لـ 404" if ar else "Points to 404"),
            ("points_to_noindex", "يشير لـ noindex" if ar else "Points to noindex"),
            ("invalid_format", "تنسيق خاطئ" if ar else "Invalid format"),
            ("missing_x_default", "بلا x-default" if ar else "Missing x-default"),
            ("missing_self_reference", "بلا إشارة ذاتية" if ar else "Missing self-ref"),
        ]
        cards = "".join(
            f'<div class="card"><div class="num">{_e(hv.get(key + "_count", 0))}</div>'
            f'<div class="lbl">{_e(lbl)}</div></div>'
            for key, lbl in cats)
        return (f'<section><h2>{_e(title)}</h2>'
                f'<p class="muted">{_e(hv.get("total_pages_with_hreflang", 0))} '
                f'{"صفحة تستخدم hreflang" if ar else "pages use hreflang"}</p>'
                f'<div class="cards">{cards}</div></section>')

    def _resources(self, audit, L, max_rows) -> str:
        rd = audit.get("resources_data", {}) or {}
        status_rows = audit.get("resource_status", []) or []
        if not rd and not status_rows:
            return ""
        ar = L["lang"] == "ar"
        title = "جرد الموارد (CSS/JS/صور/خطوط)" if ar else "Resource inventory"
        cards_data = [
            ("الإجمالي" if ar else "Total", rd.get("total", 0)),
            ("فريدة" if ar else "Unique", rd.get("unique", 0)),
            ("خارجية" if ar else "External", rd.get("external_count", 0)),
            ("محتوى مختلط" if ar else "Mixed content", rd.get("mixed_content_count", 0)),
        ]
        cards = "".join(f'<div class="card"><div class="num">{_e(v)}</div>'
                        f'<div class="lbl">{_e(lbl)}</div></div>' for lbl, v in cards_data)
        broken = [r for r in status_rows if r.get("is_broken")]
        table = ""
        if broken:
            hdr = ("المورد", "النوع", "الحالة") if ar else ("Resource", "Type", "Status")
            h = "".join(f"<th>{_e(x)}</th>" for x in hdr)
            rows = "".join(
                f'<tr><td>{_e(r.get("url"))}</td><td>{_e(r.get("resource_type"))}</td>'
                f'<td class="ctr">{_e(r.get("status_code"))}</td></tr>'
                for r in broken[:max_rows])
            cap = (f'الموارد المعطوبة ({len(broken)})' if ar else f'Broken resources ({len(broken)})')
            table = (f'<h3>{_e(cap)}</h3><table class="tbl"><thead><tr>{h}</tr></thead>'
                     f'<tbody>{rows}</tbody></table>')
        return f'<section><h2>{_e(title)}</h2><div class="cards">{cards}</div>{table}</section>'

    def _opportunities(self, audit, L, max_rows) -> str:
        opp = (audit.get("opportunities", {}) or {})
        rows_data = opp.get("opportunities", []) or []
        ar = L["lang"] == "ar"
        title = "أولويات الإصلاح (تقني × أداء)" if ar else "Priority Opportunities (technical × performance)"
        if not rows_data:
            return ""
        head = (("الرابط", "الدرجة", "المشاكل", "نقرات", "ظهور", "جلسات", "أهم إصلاح")
                if ar else ("URL", "Score", "Issues", "Clicks", "Impr.", "Sessions", "Top fix"))
        rows = "".join(
            f'<tr><td>{_e(o.get("url"))}</td>'
            f'<td class="ctr"><b>{_e(o.get("priority_score"))}</b></td>'
            f'<td class="muted sm">{_e(o.get("technical_issues"))}</td>'
            f'<td class="ctr">{_e(o.get("clicks"))}</td>'
            f'<td class="ctr">{_e(o.get("impressions"))}</td>'
            f'<td class="ctr">{_e(o.get("sessions"))}</td>'
            f'<td class="muted sm">{_e(o.get("top_fix"))}</td></tr>'
            for o in rows_data[:max_rows]
        )
        hdr = "".join(f"<th>{_e(h)}</th>" for h in head)
        note = (f"{opp.get('summary',{}).get('with_traffic_and_issues',0)} صفحة بمشاكل وتجلب زيارات"
                if ar else
                f"{opp.get('summary',{}).get('with_traffic_and_issues',0)} pages with issues AND traffic")
        return (f'<section><h2>⭐ {_e(title)}</h2>'
                f'<p class="muted">{_e(note)}</p>'
                f'<table class="tbl"><thead><tr>{hdr}</tr></thead><tbody>{rows}</tbody></table></section>')

    def _action_board(self, audit, L, max_rows) -> str:
        """لوحة عمل: الصفحات مرتّبة حسب مجموعة الإجراء (افعل الآن / يحتاج مطوّراً…)."""
        prio = audit.get("priority", {}) or {}
        pages = prio.get("pages", []) or []
        if not pages:
            return ""
        ar = L["lang"] == "ar"
        title = "لوحة العمل (ماذا تُصلح أولاً؟)" if ar else "Action Board (what to fix first)"
        order = {g: i for i, g in enumerate(_ACTION_GROUP_ORDER)}
        rows_sorted = sorted(
            pages,
            key=lambda p: (order.get(p.get("action_group"), 99), -p.get("priority_score", 0)),
        )[:max_rows]
        gl = 0 if ar else 1
        head = (("المجموعة", "الرابط", "النوع", "الدرجة", "المالك", "أهم إصلاح")
                if ar else ("Group", "URL", "Type", "Score", "Owner", "Top fix"))
        body = "".join(
            f'<tr><td><b>{_e(_ACTION_GROUP_LABELS.get(p.get("action_group"), ("",""))[gl])}</b></td>'
            f'<td>{_e(p.get("url"))}</td>'
            f'<td class="muted sm">{_e(p.get("page_type"))}</td>'
            f'<td class="ctr"><b>{_e(p.get("priority_score"))}</b></td>'
            f'<td class="muted sm">{_e(p.get("owner"))}</td>'
            f'<td class="muted sm">{_e(p.get("top_fix"))}</td></tr>'
            for p in rows_sorted
        )
        hdr = "".join(f"<th>{_e(h)}</th>" for h in head)
        counts = prio.get("summary", {}).get("by_action_group", {}) or {}
        chips = " · ".join(
            f"{_ACTION_GROUP_LABELS.get(g, (g, g))[gl]}: {counts[g]}"
            for g in _ACTION_GROUP_ORDER if counts.get(g)
        )
        return (f'<section><h2>🗂️ {_e(title)}</h2>'
                f'<p class="muted">{_e(chips)}</p>'
                f'<table class="tbl"><thead><tr>{hdr}</tr></thead><tbody>{body}</tbody></table></section>')

    def _search_visibility(self, audit, L, max_rows) -> str:
        g = audit.get("gsc_summary", {}) or {}
        ar = L["lang"] == "ar"
        title = "الظهور البحثي (Google Search Console)" if ar else "Search Visibility (GSC)"
        if not g:
            hint = ("لم يُفعّل تكامل GSC. فعّله من الإعدادات لعرض النقرات/الظهور."
                    if ar else "GSC integration not enabled.")
            return f'<section><h2>🔍 {_e(title)}</h2><p class="muted">{_e(hint)}</p></section>'
        cards = [
            ("نقرات" if ar else "Clicks", g.get("total_clicks", 0)),
            ("ظهور" if ar else "Impressions", g.get("total_impressions", 0)),
            ("CTR%", g.get("avg_ctr", 0)),
            ("متوسط الترتيب" if ar else "Avg position", g.get("avg_position", 0)),
        ]
        cells = "".join(f'<div class="card"><div class="num">{_e(v)}</div>'
                        f'<div class="lbl">{_e(lbl)}</div></div>' for lbl, v in cards)
        tq = g.get("top_queries", [])[:max_rows]
        qrows = "".join(
            f'<tr><td>{_e(q.get("query"))}</td><td class="ctr">{_e(q.get("clicks"))}</td>'
            f'<td class="ctr">{_e(q.get("impressions"))}</td><td class="ctr">{_e(q.get("position"))}</td></tr>'
            for q in tq)
        qhdr = ("الاستعلام", "نقرات", "ظهور", "ترتيب") if ar else ("Query", "Clicks", "Impr.", "Pos.")
        qh = "".join(f"<th>{_e(h)}</th>" for h in qhdr)
        qtable = (f'<table class="tbl"><thead><tr>{qh}</tr></thead><tbody>{qrows}</tbody></table>'
                  if qrows else "")
        return (f'<section><h2>🔍 {_e(title)}</h2><div class="cards">{cells}</div>{qtable}</section>')

    def _user_behavior(self, audit, L, max_rows) -> str:
        a = audit.get("ga4_summary", {}) or {}
        ar = L["lang"] == "ar"
        title = "سلوك المستخدم (Google Analytics 4)" if ar else "User Behavior (GA4)"
        if not a:
            hint = ("لم يُفعّل تكامل GA4. فعّله من الإعدادات لعرض الجلسات/المستخدمين."
                    if ar else "GA4 integration not enabled.")
            return f'<section><h2>👤 {_e(title)}</h2><p class="muted">{_e(hint)}</p></section>'
        cards = [
            ("مستخدمون" if ar else "Users", a.get("total_users", 0)),
            ("جلسات" if ar else "Sessions", a.get("total_sessions", 0)),
            ("صفحات هبوط" if ar else "Landing pages", a.get("landing_pages_count", 0)),
        ]
        cells = "".join(f'<div class="card"><div class="num">{_e(v)}</div>'
                        f'<div class="lbl">{_e(lbl)}</div></div>' for lbl, v in cards)
        lp = a.get("top_landing_pages", [])[:max_rows]
        lrows = "".join(
            f'<tr><td>{_e(p.get("path"))}</td><td class="ctr">{_e(p.get("sessions"))}</td>'
            f'<td class="ctr">{_e(p.get("users"))}</td><td class="ctr">{_e(p.get("engagement_rate"))}</td></tr>'
            for p in lp)
        lhdr = ("صفحة الهبوط", "جلسات", "مستخدمون", "تفاعل%") if ar else ("Landing page", "Sessions", "Users", "Engage%")
        lh = "".join(f"<th>{_e(h)}</th>" for h in lhdr)
        ltable = (f'<table class="tbl"><thead><tr>{lh}</tr></thead><tbody>{lrows}</tbody></table>'
                  if lrows else "")
        return (f'<section><h2>👤 {_e(title)}</h2><div class="cards">{cells}</div>{ltable}</section>')

    def _problem_pages(self, audit, L, max_rows) -> str:
        pages = audit.get("pages", []) or []
        problem = [
            p for p in pages
            if _int(_val(p, "status_code")) >= 400 or _val(p, "crawl_error")
        ][:max_rows]
        if not problem:
            return ""
        rows = "".join(
            f'<tr><td>{_e(_val(p,"url"))}</td>'
            f'<td class="ctr">{_e(_val(p,"status_code"))}</td>'
            f'<td>{_e(_val(p,"crawl_error") or _val(p,"title"))}</td></tr>'
            for p in problem
        )
        return (
            f'<section><h2>{_e(L["problem_pages"])} ({len(problem)})</h2>'
            f'<table class="tbl"><thead><tr><th>{_e(L["url"])}</th>'
            f'<th>{_e(L["status"])}</th><th>{_e(L["title_col"])}</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></section>'
        )

    def _redirects(self, audit, L, max_rows) -> str:
        rd = audit.get("redirect_data", {}) or {}
        chains = rd.get("redirect_chains", []) or []
        if not chains:
            return ""
        rows = "".join(
            f'<tr><td>{_e(c.get("original_url",""))}</td>'
            f'<td>{_e(c.get("final_url",""))}</td>'
            f'<td class="ctr">{_e(c.get("chain_length",0))}</td></tr>'
            for c in chains[:max_rows]
        )
        return (
            f'<section><h2>{_e(L["redirects"])} ({len(chains)})</h2>'
            f'<table class="tbl"><thead><tr><th>From</th><th>To</th>'
            f'<th>Hops</th></tr></thead><tbody>{rows}</tbody></table></section>'
        )

    def _schema(self, audit, L) -> str:
        sv = audit.get("schema_validation", {}) or {}
        if not sv or not sv.get("total_schemas"):
            return ""
        by_type = sv.get("by_type", {}) or {}
        rows = "".join(
            f'<tr><td>{_e(t)}</td><td class="ctr">{_e(n)}</td></tr>'
            for t, n in sorted(by_type.items(), key=lambda x: -x[1])
        )
        return (
            f'<section><h2>{_e(L["schema"])}</h2>'
            f'<p class="muted">Total: {_e(sv.get("total_schemas",0))} · '
            f'Rich-eligible: {_e(len(sv.get("rich_result_eligible",[])))} · '
            f'Invalid: {_e(len(sv.get("invalid_schemas",[])))}</p>'
            f'<table class="tbl"><thead><tr><th>Type</th><th>#</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></section>'
        )


def _val(item: Any, key: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


_CSS = """
* { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", Tahoma, Arial, sans-serif;
  margin: 0; color: #1f2937; background: #fff; line-height: 1.6; }
.cover { text-align: center; padding: 60px 20px; background: #1F4E79; color: #fff; }
.cover h1 { font-size: 2.4rem; margin: 10px 0; }
.cover .client { font-size: 1.3rem; opacity: .95; }
.cover .site, .cover .date { opacity: .85; margin-top: 6px; }
.cover .logo { max-height: 80px; margin-bottom: 12px; }
section { padding: 24px 32px; border-bottom: 1px solid #eef0f3; }
h2 { color: #1F4E79; border-bottom: 2px solid #1F4E79; padding-bottom: 6px; }
.cards { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 12px; }
.card { flex: 1 1 110px; background: #f8fafc; border: 1px solid #e5e7eb;
  border-radius: 10px; padding: 14px; text-align: center; }
.card .num { font-size: 1.8rem; font-weight: 700; }
.card .lbl { color: #6b7280; font-size: .9rem; }
.card.crit { background: #FFC7CE; } .card.high { background: #FFEB9C; }
.card.med { background: #FFF2CC; } .card.low { background: #E2EFDA; }
.tbl { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: .92rem; }
.tbl th { background: #1F4E79; color: #fff; padding: 8px; text-align: start; }
.tbl td { border-bottom: 1px solid #eef0f3; padding: 8px; vertical-align: top;
  word-break: break-word; }
.tbl tr:nth-child(even) td { background: #f9fafb; }
.ctr { text-align: center; }
.muted { color: #6b7280; } .sm { font-size: .8rem; }
.sev { padding: 6px 10px; border-radius: 8px; display: inline-block; margin-top: 18px; }
.sev.crit { background: #FFC7CE; } .sev.high { background: #FFEB9C; }
.sev.med { background: #FFF2CC; } .sev.low { background: #E2EFDA; }
.badge { background: rgba(0,0,0,.15); border-radius: 20px; padding: 0 8px; font-size: .85rem; }
.cover .kind { display: inline-block; margin: 6px 0; padding: 2px 12px; font-size: .95rem;
  background: rgba(255,255,255,.2); border-radius: 20px; }
.health { display: flex; align-items: center; gap: 18px; margin: 14px 0; }
.health .score { font-size: 3rem; font-weight: 800; line-height: 1; padding: 14px 22px;
  border-radius: 14px; }
.health .score span { font-size: 1.1rem; font-weight: 500; opacity: .6; }
.health .grade { font-size: 1.4rem; font-weight: 700; padding: 6px 16px; border-radius: 10px; }
.score.crit, .grade.crit { background: #FFC7CE; } .score.high, .grade.high { background: #FFEB9C; }
.score.med, .grade.med { background: #FFF2CC; } .score.low, .grade.low { background: #E2EFDA; }
ul.plain { margin: 6px 0; padding-inline-start: 22px; } ul.plain li { margin: 3px 0; }
ul.ai-recs li { margin: 10px 0; list-style: none; }
ul.ai-recs { padding-inline-start: 0; }
.ftr { text-align: center; color: #9ca3af; padding: 20px; font-size: .85rem; }
@media print { .cover { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  section { page-break-inside: avoid; } }
"""
