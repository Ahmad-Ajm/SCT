"""
extractors/schema_extractor.py
===============================
استخراج بيانات Schema.org بصيغ:
- JSON-LD (الأشهر)
- Microdata (itemtype, itemprop)
- RDFa (محدود)
"""

import json
from typing import Any
from bs4 import BeautifulSoup


def extract_schema(soup: BeautifulSoup) -> dict[str, Any]:
    """
    استخراج كل Schema.org من الصفحة.

    Returns:
        dict: {
            "count": عدد الـ schemas
            "types": [] قائمة الأنواع (Product, Organization...)
            "raw": [] البيانات الخام
            "entries": [] تفصيل كل schema
            "has_breadcrumb": bool
            "has_organization": bool
            "has_product": bool
            "has_faq": bool
            "has_review": bool
            "has_article": bool
            "json_ld_count": int
            "microdata_count": int
            "validation_errors": [] أخطاء أساسية
        }
    """
    result: dict[str, Any] = {
        "count": 0,
        "types": [],
        "raw": [],
        "entries": [],
        "has_breadcrumb": False,
        "has_organization": False,
        "has_product": False,
        "has_faq": False,
        "has_review": False,
        "has_article": False,
        "has_local_business": False,
        "json_ld_count": 0,
        "microdata_count": 0,
        "validation_errors": [],
    }

    # === 1. JSON-LD (الأشهر والأقوى) ===
    json_ld_scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for script in json_ld_scripts:
        if not script.string:
            continue

        try:
            data = json.loads(script.string.strip())
            result["json_ld_count"] += 1
            _process_json_ld(data, result, "json-ld")
        except json.JSONDecodeError as e:
            result["validation_errors"].append(
                f"JSON-LD parse error: {str(e)[:100]}"
            )

    # === 2. Microdata ===
    microdata_items = soup.find_all(attrs={"itemtype": True})
    for item in microdata_items:
        itemtype = item.get("itemtype", "")
        if "schema.org" not in itemtype:
            continue

        result["microdata_count"] += 1
        schema_type = itemtype.rstrip("/").split("/")[-1]

        # استخراج properties
        properties = {}
        for prop_elem in item.find_all(attrs={"itemprop": True}):
            prop_name = prop_elem.get("itemprop")
            # استخراج القيمة حسب نوع العنصر
            if prop_elem.name == "meta":
                prop_value = prop_elem.get("content", "")
            elif prop_elem.name in ("img", "audio", "video"):
                prop_value = prop_elem.get("src", "")
            elif prop_elem.name == "a":
                prop_value = prop_elem.get("href", "")
            elif prop_elem.name == "time":
                prop_value = prop_elem.get("datetime", prop_elem.get_text(strip=True))
            else:
                prop_value = prop_elem.get_text(strip=True)
            properties[prop_name] = prop_value

        entry = {
            "format": "microdata",
            "type": schema_type,
            "properties": properties,
            # raw_data يسمح للمحلّل (schema_validator) بفحص الحقول المطلوبة (إصلاح H6)
            "raw_data": properties,
        }
        result["raw"].append(entry)
        result["types"].append(schema_type)
        result["entries"].append(entry)
        _flag_schema_types(schema_type, result)

    # === 3. حساب الإجمالي ===
    result["count"] = result["json_ld_count"] + result["microdata_count"]
    # إزالة التكرارات في types
    result["types"] = list(dict.fromkeys(result["types"]))

    return result


def _process_json_ld(data: Any, result: dict, format_name: str) -> None:
    """معالجة JSON-LD recursive (قد يحتوي @graph أو nested)."""
    if isinstance(data, list):
        # array من schemas
        for item in data:
            _process_json_ld(item, result, format_name)
        return

    if not isinstance(data, dict):
        return

    # @graph يحتوي على schemas متعددة
    if "@graph" in data:
        for item in data["@graph"]:
            _process_json_ld(item, result, format_name)
        return

    # Schema فردي
    schema_type = data.get("@type", "")
    if isinstance(schema_type, list):
        schema_type_str = ",".join(schema_type)
        for t in schema_type:
            result["types"].append(t)
            _flag_schema_types(t, result)
    else:
        schema_type_str = str(schema_type)
        result["types"].append(schema_type_str)
        _flag_schema_types(schema_type_str, result)

    entry = {
        "format": format_name,
        "type": schema_type_str,
        "name": data.get("name", ""),
        "raw_data": data,
    }
    result["raw"].append(entry)
    result["entries"].append(entry)


def _flag_schema_types(schema_type: str, result: dict) -> None:
    """تحديد الـ flags للأنواع المهمة."""
    if not schema_type:
        return

    type_lower = schema_type.lower()

    if "breadcrumb" in type_lower:
        result["has_breadcrumb"] = True
    if "organization" in type_lower:
        result["has_organization"] = True
    if "product" in type_lower:
        result["has_product"] = True
    if "faq" in type_lower or "faqpage" in type_lower:
        result["has_faq"] = True
    if "review" in type_lower or "aggregaterating" in type_lower:
        result["has_review"] = True
    if "article" in type_lower or "blogposting" in type_lower or "newsarticle" in type_lower:
        result["has_article"] = True
    if "localbusiness" in type_lower or "store" in type_lower:
        result["has_local_business"] = True
