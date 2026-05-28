"""
extractors/custom_extractor.py
==============================
استخراج مخصّص يعرّفه المستخدم في الإعدادات (CSS selector / attribute / text / regex).

مثال إعداد (config.yaml):

custom_extraction:
  enabled: true
  rules:
    - name: product_price
      type: css
      selector: ".price"
      extract: text          # text | attr | html
    - name: canonical_href
      type: css
      selector: "link[rel='canonical']"
      extract: attr
      attr: href
    - name: sku
      type: regex
      pattern: 'SKU:\\s*([A-Z0-9-]+)'
      group: 1
"""

from __future__ import annotations

import re
from typing import Any


def compile_rules(rules: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """تحضير القواعد (تجميع regex مسبقاً، تجاهل القواعد غير الصالحة)."""
    compiled: list[dict[str, Any]] = []
    for rule in rules or []:
        name = str(rule.get("name", "")).strip()
        rtype = str(rule.get("type", "css")).lower()
        if not name:
            continue
        if rtype == "regex":
            pattern = rule.get("pattern")
            if not pattern:
                continue
            try:
                rx = re.compile(pattern, re.IGNORECASE | re.DOTALL)
            except re.error:
                continue
            compiled.append({"name": name, "type": "regex", "rx": rx,
                             "group": int(rule.get("group", 0) or 0)})
        else:  # css
            selector = rule.get("selector")
            if not selector:
                continue
            compiled.append({
                "name": name, "type": "css", "selector": selector,
                "extract": str(rule.get("extract", "text")).lower(),
                "attr": rule.get("attr", "href"),
                "all": bool(rule.get("all", False)),
            })
    return compiled


def extract_custom(
    soup: Any,
    html: str,
    compiled_rules: list[dict[str, Any]],
) -> dict[str, str]:
    """تطبيق القواعد المُجمَّعة وإرجاع {اسم القاعدة: القيمة}."""
    out: dict[str, str] = {}
    for rule in compiled_rules:
        try:
            if rule["type"] == "regex":
                m = rule["rx"].search(html or "")
                if m:
                    out[rule["name"]] = m.group(rule["group"]) if rule["group"] else m.group(0)
                else:
                    out[rule["name"]] = ""
            else:  # css
                if soup is None:
                    out[rule["name"]] = ""
                    continue
                els = soup.select(rule["selector"])
                if not els:
                    out[rule["name"]] = ""
                    continue
                vals = [_extract_one(el, rule) for el in (els if rule["all"] else els[:1])]
                out[rule["name"]] = " | ".join(v for v in vals if v) if rule["all"] else (vals[0] if vals else "")
        except Exception:
            out[rule["name"]] = ""
    return out


def _extract_one(el: Any, rule: dict[str, Any]) -> str:
    mode = rule["extract"]
    if mode == "attr":
        return str(el.get(rule["attr"], "") or "").strip()
    if mode == "html":
        return str(el).strip()
    return el.get_text(strip=True)
