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
