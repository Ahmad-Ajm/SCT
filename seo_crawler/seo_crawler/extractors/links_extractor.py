"""
extractors/links_extractor.py
==============================
استخراج كل الروابط من الصفحة:
- Internal vs External
- Anchor text
- rel attributes (nofollow, ugc, sponsored)
- target
- يتضمن أيضاً روابط <area> في image maps
"""

from typing import Any
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from utils.helpers import is_internal_url, normalize_url


def extract_links(
    soup: BeautifulSoup,
    page_url: str,
    primary_domain: str,
    additional_domains: list[str] = None,
) -> list[dict[str, Any]]:
    """
    استخراج كل الروابط من الصفحة.

    Args:
        soup: BeautifulSoup
        page_url: رابط الصفحة الحالية (لحل الروابط النسبية)
        primary_domain: الدومين الأساسي
        additional_domains: نطاقات إضافية تُعتبر داخلية

    Returns:
        list[dict]: كل رابط بـ:
            - to_url: الرابط الكامل
            - to_url_normalized: مُطبَّع
            - anchor_text: النص الظاهر
            - title: title attribute
            - rel: rel attribute
            - target: target attribute
            - is_internal: داخلي أم خارجي
            - nofollow: nofollow؟
            - ugc: UGC؟
            - sponsored: sponsored؟
            - is_image_link: هل anchor عبارة عن صورة؟
            - link_position: ترتيب في الصفحة
            - in_navigation: في nav element؟
            - in_footer: في footer؟
    """
    links: list[dict[str, Any]] = []

    # === كشف العناصر التي تحدد سياق الرابط ===
    nav_elements = set()
    for nav in soup.find_all("nav"):
        for descendant in nav.find_all():
            nav_elements.add(id(descendant))

    footer_elements = set()
    for footer in soup.find_all("footer"):
        for descendant in footer.find_all():
            footer_elements.add(id(descendant))

    header_elements = set()
    for header in soup.find_all("header"):
        for descendant in header.find_all():
            header_elements.add(id(descendant))

    main_elements = set()
    for main in soup.find_all("main"):
        for descendant in main.find_all():
            main_elements.add(id(descendant))

    # === استخراج كل <a> ===
    for position, a_tag in enumerate(soup.find_all("a", href=True), start=1):
        href = a_tag.get("href", "").strip()

        # تخطّي روابط فارغة أو خاصة
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            # لكن نسجّلها للإحصاء
            if href:
                links.append(
                    _build_link_entry(
                        a_tag,
                        href,
                        href,
                        href,  # للروابط الخاصة، normalized = absolute = raw
                        page_url,
                        position,
                        primary_domain,
                        additional_domains,
                        nav_elements,
                        footer_elements,
                        header_elements,
                        main_elements,
                        is_special=True,
                    )
                )
            continue

        # حل URL مطلق (نحسب normalized مرة واحدة هنا ونمرره)
        try:
            absolute_url = urljoin(page_url, href)
            normalized = normalize_url(absolute_url)
        except Exception:
            continue

        links.append(
            _build_link_entry(
                a_tag,
                href,
                absolute_url,
                normalized,  # ← نمرّر القيمة المحسوبة (إصلاح Perf #1)
                page_url,
                position,
                primary_domain,
                additional_domains,
                nav_elements,
                footer_elements,
                header_elements,
                main_elements,
            )
        )

    return links


def _build_link_entry(
    a_tag,
    href_raw: str,
    absolute_url: str,
    normalized_url: str,
    page_url: str,
    position: int,
    primary_domain: str,
    additional_domains: list[str],
    nav_elements: set,
    footer_elements: set,
    header_elements: set,
    main_elements: set,
    is_special: bool = False,
) -> dict[str, Any]:
    """بناء كائن الرابط."""
    # rel attribute
    rel = a_tag.get("rel", [])
    if isinstance(rel, str):
        rel = rel.split()
    rel_lower = [r.lower() for r in rel]

    # anchor text
    anchor_text = a_tag.get_text(separator=" ", strip=True)

    # هل anchor عبارة عن صورة؟
    is_image_link = bool(a_tag.find("img")) and not anchor_text

    # تحديد السياق
    tag_id = id(a_tag)
    in_navigation = tag_id in nav_elements
    in_footer = tag_id in footer_elements
    in_header = tag_id in header_elements
    in_main = tag_id in main_elements

    # تحديد داخلي/خارجي
    if is_special:
        is_internal = False
        normalized = absolute_url  # للروابط الخاصة (mailto, tel) لا نُطبّع
    else:
        is_internal = is_internal_url(absolute_url, primary_domain, additional_domains)
        normalized = normalized_url

    return {
        "to_url": absolute_url,
        "to_url_normalized": normalized,
        "href_raw": href_raw,
        "anchor_text": anchor_text,
        "anchor_text_length": len(anchor_text),
        "title": a_tag.get("title", "").strip(),
        "rel": " ".join(rel_lower),
        "target": a_tag.get("target", "").strip(),
        "is_internal": is_internal,
        "nofollow": "nofollow" in rel_lower,
        "ugc": "ugc" in rel_lower,
        "sponsored": "sponsored" in rel_lower,
        "noopener": "noopener" in rel_lower,
        "noreferrer": "noreferrer" in rel_lower,
        "is_image_link": is_image_link,
        "link_position": position,
        "in_navigation": in_navigation,
        "in_footer": in_footer,
        "in_header": in_header,
        "in_main": in_main,
        "is_special_link": is_special,  # mailto, tel, javascript, #
    }
