"""
analyzers/log_analyzer.py
=========================
محلّل سجلّات الويب (CLF/Combined) لاستخراج زحف Googlebot وغيرها من البوتات:
- استهلاك ميزانية الزحف لكل URL (عدد زيارات البوت + حالاتها).
- توزيع رموز الحالة (200/3xx/404/5xx) كما رآها Googlebot فعلاً.
- اكتشاف صفحات «مزحوفة بوت لكنها يتيمة» (إذا قارنّاها مع روابط الزحف لاحقاً).

كل الدوال نقية: تأخذ نصوصاً، لا I/O ولا شبكة — يسهل اختبارها وتشغيلها على أي خادم.
المُسطّحات المُصدَّرة جاهزة لـ CSV بلا تفاصيل خام ضخمة.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable, Optional

# Combined Log Format (الأكثر شيوعاً في nginx/apache):
#   ip - user [time] "METHOD path HTTP/x" status size "referrer" "user-agent"
# نسمح بنسخة بلا الحقلين الأخيرَين (Common Log Format) أيضاً.
_LOG_RE = re.compile(
    r'^(?P<ip>\S+)\s+\S+\s+\S+\s+\[(?P<ts>[^\]]+)\]\s+'
    r'"(?P<method>[A-Z]+)\s+(?P<path>[^"\s]+)\s+\S+"\s+'
    r'(?P<status>\d{3})\s+(?P<size>\S+)'
    r'(?:\s+"(?P<ref>[^"]*)"\s+"(?P<ua>[^"]*)")?'
)

# توقيعات بوتات شائعة (substring في user-agent، case-insensitive)
DEFAULT_BOTS: dict[str, str] = {
    "Googlebot": "googlebot",
    "AdsBot-Google": "adsbot-google",
    "Bingbot": "bingbot",
    "DuckDuckBot": "duckduckbot",
    "YandexBot": "yandexbot",
    "Baiduspider": "baiduspider",
    "Applebot": "applebot",
    "GPTBot": "gptbot",
    "ClaudeBot": "claudebot",
}


def detect_bot(user_agent: str, bots: Optional[dict[str, str]] = None) -> str:
    """يعيد اسم البوت إن طابق توقيعاً، وإلا سلسلة فارغة."""
    ua = (user_agent or "").lower()
    if not ua:
        return ""
    for name, needle in (bots or DEFAULT_BOTS).items():
        if needle in ua:
            return name
    return ""


def parse_log_line(line: str, bots: Optional[dict[str, str]] = None) -> Optional[dict[str, Any]]:
    """يُحلّل سطر سجلّ واحد (CLF/Combined). يعيد None لو لم يتطابق."""
    if not line or not line.strip():
        return None
    m = _LOG_RE.match(line.strip())
    if not m:
        return None
    d = m.groupdict()
    ua = d.get("ua") or ""
    bot = detect_bot(ua, bots)
    try:
        status = int(d["status"])
    except (TypeError, ValueError):
        status = 0
    try:
        size = int(d["size"]) if (d.get("size") and d["size"] != "-") else 0
    except (TypeError, ValueError):
        size = 0
    return {
        "ip": d.get("ip", ""),
        "ts": d.get("ts", ""),
        "method": d.get("method", ""),
        "path": d.get("path", ""),
        "status": status,
        "size": size,
        "user_agent": ua,
        "is_bot": bool(bot),
        "bot": bot,
    }


def analyze_log(
    lines: Iterable[str],
    bot_only: bool = True,
    max_lines: int = 2_000_000,
    bots: Optional[dict[str, str]] = None,
    top_urls: int = 5000,
) -> dict[str, Any]:
    """يُحلّل تدفّق أسطر سجلّ ويُرجع ملخّصاً + قائمة per-URL مرتّبة.

    Args:
        lines: مُكرِّر أسطر (يدعم الـstreaming من ملف ضخم بلا تحميل الكل).
        bot_only: حصر التحليل في طلبات البوتات فقط (افتراضي — للـSEO).
        max_lines: سقف معالجة لحماية الذاكرة على ملفات هائلة.
        top_urls: عدد الأعلى hits في `per_url` المُرجعة (الكلّ في summary).
    """
    per_url: dict[str, dict[str, Any]] = {}
    bot_counter: Counter = Counter()
    status_counter: Counter = Counter()
    total = parsed = bot_lines = 0

    for line in lines:
        if total >= max_lines:
            break
        total += 1
        row = parse_log_line(line, bots)
        if not row:
            continue
        parsed += 1
        if row["is_bot"]:
            bot_lines += 1
            bot_counter[row["bot"]] += 1
        if bot_only and not row["is_bot"]:
            continue
        status_counter[row["status"]] += 1
        key = row["path"]
        rec = per_url.get(key)
        if rec is None:
            rec = {
                "path": key,
                "hits": 0,
                "last_seen": "",
                "bots": Counter(),
                "statuses": Counter(),
            }
            per_url[key] = rec
        rec["hits"] += 1
        if row["ts"] > rec["last_seen"]:
            rec["last_seen"] = row["ts"]
        if row["bot"]:
            rec["bots"][row["bot"]] += 1
        rec["statuses"][row["status"]] += 1

    # تسطيح للأمام (CSV-friendly)
    rows: list[dict[str, Any]] = []
    for key, rec in per_url.items():
        statuses = rec["statuses"]
        rows.append({
            "path": key,
            "hits": rec["hits"],
            "last_seen": rec["last_seen"],
            "top_bot": (rec["bots"].most_common(1)[0][0] if rec["bots"] else ""),
            "status_200": statuses.get(200, 0),
            "status_3xx": sum(v for k, v in statuses.items() if 300 <= k < 400),
            "status_404": statuses.get(404, 0),
            "status_4xx_other": sum(
                v for k, v in statuses.items() if 400 <= k < 500 and k != 404),
            "status_5xx": sum(v for k, v in statuses.items() if 500 <= k < 600),
        })
    rows.sort(key=lambda r: r["hits"], reverse=True)
    capped = rows[: max(0, int(top_urls))]

    total_404 = sum(r["status_404"] for r in rows)
    total_5xx = sum(r["status_5xx"] for r in rows)
    return {
        "per_url": capped,
        "summary": {
            "total_lines": total,
            "parsed_lines": parsed,
            "bot_lines": bot_lines,
            "unique_urls": len(per_url),
            "top_bots": [{"bot": b, "hits": c} for b, c in bot_counter.most_common(10)],
            "status_distribution": dict(status_counter),
            "total_404": total_404,
            "total_5xx": total_5xx,
            "truncated": total >= max_lines,
        },
    }


def find_orphan_bot_urls(
    log_per_url: list[dict[str, Any]],
    crawl_urls: Iterable[str],
    primary_path_only: bool = True,
) -> list[dict[str, Any]]:
    """مسارات يزحفها Googlebot فعلاً لكن أداة الزحف لم تكتشفها (يتامى مزحوفون).

    إشارة قوية لمشاكل اكتشاف الروابط الداخلية أو محتوى يصل إليه البوت دون رابط في موقعك.
    """
    from urllib.parse import urlparse
    crawl_paths: set[str] = set()
    for u in crawl_urls or []:
        try:
            p = (urlparse(u).path or "/").rstrip("/") or "/"
        except (TypeError, ValueError):
            continue
        crawl_paths.add(p)
    out = []
    for r in log_per_url or []:
        p = (r.get("path") or "").split("?")[0] if primary_path_only else r.get("path", "")
        p = (p or "/").rstrip("/") or "/"
        if p not in crawl_paths:
            out.append(r)
    return out


# v1.04: ضمّ بيانات اللوغ مع مخرجات الزحف لإظهار «ميزانية زحف Google المهدورة»
# وترتيب جديد للأولويات يأخذ في الحسبان تكرار Google لكلّ صفحة.
def join_log_with_audit(
    log_per_url: list[dict[str, Any]],
    audit: dict[str, Any],
) -> dict[str, Any]:
    """يُدمج تقرير اللوغ مع audit JSON كاملاً ويُرجع رؤى عمليّة:

    - wasted_budget: أعلى الصفحات التي يزحفها Google كثيراً ثم تعطي 4xx/5xx (ميزانية مهدورة).
    - high_value_with_issues: صفحات يزحفها Google كثيراً ولها مشاكل في الأولوية (الأهمّ فعلاً).
    - orphan_bot_urls: صفحات يزحفها Google لم تكتشفها أداتنا (مشكلة ربط داخلي).
    - rescored_priority: ترتيب الأولويّات معاد ترجيحه بـ"تكرار Google" (الإصلاح ذو الأثر الأعلى).
    """
    from urllib.parse import urlparse
    # 1) فهرسة pages الزحف بـpath (للضمّ مع per_url من اللوغ)
    pages = audit.get("pages") or []
    by_path: dict[str, dict[str, Any]] = {}
    for p in pages:
        url = p.get("url") if isinstance(p, dict) else getattr(p, "url", "")
        if not url:
            continue
        try:
            path = (urlparse(url).path or "/").rstrip("/") or "/"
        except (TypeError, ValueError):
            continue
        by_path[path] = {
            "url": url,
            "status_code": p.get("status_code") if isinstance(p, dict) else getattr(p, "status_code", None),
            "is_indexable": p.get("is_indexable") if isinstance(p, dict) else getattr(p, "is_indexable", False),
        }

    # 2) فهرسة priority pages
    priority_pages = (audit.get("priority", {}) or {}).get("pages", []) or []
    prio_by_url: dict[str, dict[str, Any]] = {}
    for pp in priority_pages:
        url = pp.get("url", "")
        if url:
            prio_by_url[url] = pp

    # 3) المرور على per_url من اللوغ وضمّه
    wasted: list[dict[str, Any]] = []
    high_value: list[dict[str, Any]] = []
    rescored: list[dict[str, Any]] = []

    for row in (log_per_url or []):
        raw_path = (row.get("path") or "").split("?")[0]
        path = (raw_path or "/").rstrip("/") or "/"
        page = by_path.get(path)
        crawl_url = page["url"] if page else None
        hits = int(row.get("hits", 0) or 0)
        bad_hits = int(row.get("status_404", 0) or 0) + int(row.get("status_5xx", 0) or 0)

        # (أ) ميزانية مهدورة: Google يزحف الصفحة بكثرة وتعطي 4xx/5xx
        if bad_hits > 0:
            wasted.append({
                "path": path,
                "url": crawl_url or path,
                "googlebot_hits": hits,
                "googlebot_4xx": int(row.get("status_404", 0) or 0)
                                  + int(row.get("status_4xx_other", 0) or 0),
                "googlebot_5xx": int(row.get("status_5xx", 0) or 0),
                "in_audit": page is not None,
                "audit_status": (page or {}).get("status_code"),
                "last_seen": row.get("last_seen", ""),
            })

        # (ب) الأولويّة المعاد ترجيحها: نمزج درجة الأولوية مع تكرار Google
        if crawl_url and crawl_url in prio_by_url:
            pp = prio_by_url[crawl_url]
            base_score = float(pp.get("priority_score", 0) or 0)
            # log10 لتجنّب طغيان صفحة واحدة عالية الزيارات على البقيّة
            import math
            log_boost = math.log10(hits + 1) * 10
            new_score = round(base_score + log_boost, 2)
            entry = {**pp, "googlebot_hits": hits, "log_boosted_score": new_score}
            rescored.append(entry)
            # حدّ «عالية القيمة»: درجة معاد ترجيحها >= 50 وزيارات Google >= 10
            if new_score >= 50 and hits >= 10:
                high_value.append(entry)

    wasted.sort(key=lambda r: -r["googlebot_hits"])
    rescored.sort(key=lambda r: -r["log_boosted_score"])
    high_value.sort(key=lambda r: -r["log_boosted_score"])

    # 4) صفحات يزحفها Google لكنّ أداتنا لم تكتشفها (orphan bot)
    orphans = find_orphan_bot_urls(log_per_url or [], by_path.keys())

    # 5) إحصاءات ملخّصة لعرض البطاقات في الواجهة
    total_googlebot_hits = sum(int(r.get("hits", 0) or 0) for r in (log_per_url or []))
    wasted_hits = sum(r["googlebot_hits"] for r in wasted)
    return {
        "summary": {
            "total_googlebot_hits": total_googlebot_hits,
            "wasted_hits": wasted_hits,
            "wasted_pages": len(wasted),
            "high_value_pages": len(high_value),
            "orphan_bot_pages": len(orphans),
            "rescored_pages": len(rescored),
        },
        "wasted_budget": wasted[:50],
        "high_value_with_issues": high_value[:50],
        "orphan_bot_urls": orphans[:50],
        "rescored_priority": rescored[:100],
    }
