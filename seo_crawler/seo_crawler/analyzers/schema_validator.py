"""
analyzers/schema_validator.py
==============================
التحقق من اكتمال وصحة Schema.org للحصول على Rich Results في Google.

يفحص:
- الحقول المطلوبة (required) لكل نوع
- الحقول الموصى بها (recommended)
- الأنواع المهمة: Product, Organization, BreadcrumbList,
  FAQPage, Article, Review, LocalBusiness, Event, Recipe

مرجع: https://developers.google.com/search/docs/appearance/structured-data
"""

from typing import Any

# ============================================================
# === متطلبات كل نوع Schema ===
# ============================================================
# لكل نوع:
#   required: حقول إلزامية للظهور في Rich Results
#   recommended: حقول موصى بها (تزيد فرص الظهور)

SCHEMA_REQUIREMENTS = {
    "Product": {
        "required": ["name", "image"],
        "recommended": ["description", "brand", "offers", "aggregateRating", "review", "sku"],
        "rich_result_type": "Product snippet",
    },
    "Offer": {
        "required": ["price", "priceCurrency", "availability"],
        "recommended": ["url", "validFrom", "priceValidUntil"],
        "rich_result_type": "Merchant listing",
    },
    "Organization": {
        "required": ["name"],
        "recommended": ["url", "logo", "sameAs", "contactPoint", "address"],
        "rich_result_type": "Knowledge panel",
    },
    "LocalBusiness": {
        "required": ["name", "address"],
        "recommended": ["telephone", "openingHours", "geo", "url", "image"],
        "rich_result_type": "Local business",
    },
    "BreadcrumbList": {
        "required": ["itemListElement"],
        "recommended": [],
        "rich_result_type": "Breadcrumbs",
    },
    "FAQPage": {
        "required": ["mainEntity"],
        "recommended": [],
        "rich_result_type": "FAQ",
    },
    "Article": {
        "required": ["headline", "image", "datePublished", "author"],
        "recommended": ["dateModified", "publisher", "mainEntityOfPage", "description"],
        "rich_result_type": "Article",
    },
    "BlogPosting": {
        "required": ["headline", "image", "datePublished", "author"],
        "recommended": ["dateModified", "publisher", "description"],
        "rich_result_type": "Article",
    },
    "NewsArticle": {
        "required": ["headline", "image", "datePublished", "author"],
        "recommended": ["dateModified", "publisher", "description"],
        "rich_result_type": "Top stories",
    },
    "Recipe": {
        "required": ["name", "image", "recipeIngredient", "recipeInstructions"],
        "recommended": ["nutrition", "totalTime", "recipeYield", "aggregateRating"],
        "rich_result_type": "Recipe",
    },
    "Review": {
        "required": ["itemReviewed", "reviewRating", "author"],
        "recommended": ["datePublished", "reviewBody"],
        "rich_result_type": "Review snippet",
    },
    "AggregateRating": {
        "required": ["ratingValue", "reviewCount"],
        "recommended": ["bestRating", "worstRating"],
        "rich_result_type": "Star ratings",
    },
    "Event": {
        "required": ["name", "startDate", "location"],
        "recommended": ["endDate", "description", "image", "offers", "performer"],
        "rich_result_type": "Event",
    },
    "VideoObject": {
        "required": ["name", "description", "thumbnailUrl", "uploadDate"],
        "recommended": ["duration", "contentUrl", "embedUrl"],
        "rich_result_type": "Video",
    },
    "Person": {
        "required": ["name"],
        "recommended": ["image", "url", "jobTitle", "sameAs"],
        "rich_result_type": "Knowledge panel",
    },
    "Course": {
        "required": ["name", "description", "provider"],
        "recommended": ["offers", "hasCourseInstance"],
        "rich_result_type": "Course",
    },
    "JobPosting": {
        "required": ["title", "description", "datePosted", "hiringOrganization", "jobLocation"],
        "recommended": ["validThrough", "employmentType", "baseSalary"],
        "rich_result_type": "Job posting",
    },
    "SoftwareApplication": {
        "required": ["name", "operatingSystem", "applicationCategory"],
        "recommended": ["aggregateRating", "offers", "description"],
        "rich_result_type": "Software app",
    },
    "WebSite": {
        "required": ["name", "url"],
        "recommended": ["potentialAction"],  # SearchAction للـ Sitelinks Search Box
        "rich_result_type": "Sitelinks search box",
    },
    "WebPage": {
        "required": [],
        "recommended": ["name", "description"],
        "rich_result_type": "—",
    },
}


def _normalize_schema_data(raw_data: Any) -> dict[str, Any]:
    """Schema قد يكون JSON-LD نصاً أو dict أو list."""
    if isinstance(raw_data, str):
        try:
            import json
            return json.loads(raw_data)
        except (json.JSONDecodeError, ValueError):
            return {}
    if isinstance(raw_data, list) and raw_data:
        return raw_data[0] if isinstance(raw_data[0], dict) else {}
    if isinstance(raw_data, dict):
        return raw_data
    return {}


def _get_schema_type(data: dict) -> str:
    """استخراج @type من schema."""
    type_value = data.get("@type", "")
    if isinstance(type_value, list):
        return ",".join(str(t) for t in type_value)
    return str(type_value) if type_value else ""


def _check_required_fields(
    data: dict, schema_type: str
) -> tuple[list[str], list[str]]:
    """فحص الحقول المطلوبة والموصى بها."""
    requirements = SCHEMA_REQUIREMENTS.get(schema_type)
    if not requirements:
        return [], []

    missing_required = []
    missing_recommended = []

    for field in requirements["required"]:
        if field not in data or not data[field]:
            missing_required.append(field)

    for field in requirements["recommended"]:
        if field not in data or not data[field]:
            missing_recommended.append(field)

    return missing_required, missing_recommended


def validate_schemas(
    all_schemas: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    تحقّق من اكتمال كل Schema entries.

    Args:
        all_schemas: قائمة schema entries من الـ crawler
            (كل entry له: page_url, type, format, raw_data)

    Returns:
        dict مع:
        - total_schemas: عدد إجمالي
        - by_type: عدد كل نوع
        - invalid_schemas: schemas مع حقول required مفقودة
        - incomplete_schemas: schemas مع recommended مفقود
        - missing_opportunities: أنواع schema مهمة غير موجودة
        - rich_result_opportunities: ما يمكن الحصول عليه من Rich Results
        - validation_summary: ملخص
    """
    if not all_schemas:
        return {
            "total_schemas": 0,
            "by_type": {},
            "invalid_schemas": [],
            "incomplete_schemas": [],
            "rich_result_eligible": [],
            "validation_summary": {
                "total": 0,
                "valid": 0,
                "invalid": 0,
                "incomplete": 0,
            },
        }

    by_type: dict[str, int] = {}
    invalid_schemas: list[dict[str, Any]] = []
    incomplete_schemas: list[dict[str, Any]] = []
    rich_result_eligible: list[dict[str, Any]] = []

    for entry in all_schemas:
        page_url = entry.get("page_url", "")
        schema_type = entry.get("type", "")
        # دعم microdata: إن غاب raw_data نستخدم properties (إصلاح H6)
        raw_data = entry.get("raw_data") or entry.get("properties", {})

        # عدّ الأنواع
        if schema_type:
            for t in schema_type.split(","):
                t = t.strip()
                if t:
                    by_type[t] = by_type.get(t, 0) + 1

        # تطبيع البيانات
        data = _normalize_schema_data(raw_data)
        if not data:
            continue

        # فحص الحقول
        primary_type = schema_type.split(",")[0].strip() if schema_type else ""
        if primary_type in SCHEMA_REQUIREMENTS:
            missing_req, missing_rec = _check_required_fields(data, primary_type)
            requirements = SCHEMA_REQUIREMENTS[primary_type]

            schema_info = {
                "page_url": page_url,
                "schema_type": primary_type,
                "rich_result_type": requirements["rich_result_type"],
                "missing_required": missing_req,
                "missing_recommended": missing_rec,
            }

            if missing_req:
                invalid_schemas.append(schema_info)
            elif missing_rec:
                incomplete_schemas.append(schema_info)
            else:
                rich_result_eligible.append({
                    "page_url": page_url,
                    "schema_type": primary_type,
                    "rich_result_type": requirements["rich_result_type"],
                })

    # كشف الفرص الضائعة (e-commerce بدون Product schema، إلخ)
    opportunities = []

    if not by_type.get("Organization") and not by_type.get("LocalBusiness"):
        opportunities.append({
            "missing_type": "Organization",
            "benefit": "Knowledge Panel في Google",
            "where": "صفحة About / الرئيسية",
        })

    if not by_type.get("BreadcrumbList"):
        opportunities.append({
            "missing_type": "BreadcrumbList",
            "benefit": "عرض البنية في SERPs",
            "where": "كل الصفحات الداخلية",
        })

    if not by_type.get("WebSite"):
        opportunities.append({
            "missing_type": "WebSite (with SearchAction)",
            "benefit": "Sitelinks Search Box في Google",
            "where": "الصفحة الرئيسية",
        })

    return {
        "total_schemas": len(all_schemas),
        "by_type": dict(sorted(by_type.items(), key=lambda x: -x[1])),
        "invalid_schemas": invalid_schemas,
        "incomplete_schemas": incomplete_schemas,
        "rich_result_eligible": rich_result_eligible,
        "missing_opportunities": opportunities,
        "validation_summary": {
            "total": len(all_schemas),
            "valid_and_complete": len(rich_result_eligible),
            "invalid_missing_required": len(invalid_schemas),
            "incomplete_missing_recommended": len(incomplete_schemas),
            "unknown_or_custom_types": len(all_schemas)
                - len(rich_result_eligible)
                - len(invalid_schemas)
                - len(incomplete_schemas),
        },
    }
