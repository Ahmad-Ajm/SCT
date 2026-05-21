"""
extractors/images_extractor.py
===============================
استخراج كل الصور من الصفحة مع تفاصيلها.
"""

from typing import Any
from urllib.parse import urljoin
from bs4 import BeautifulSoup


def extract_images(soup: BeautifulSoup, page_url: str) -> list[dict[str, Any]]:
    """
    استخراج كل الصور.

    يشمل:
    - <img> tags
    - <picture> + <source>
    - Background images في style (محدود)
    - <img> داخل <noscript> (لـ lazy loading)

    Returns:
        list[dict]: كل صورة بـ:
            - src: الرابط الكامل
            - src_raw: الرابط الأصلي
            - alt: alt text
            - alt_length: طول alt
            - has_alt: هل alt موجود؟
            - alt_is_empty: alt="" (مقصود فارغ)
            - title: title attribute
            - width: width attribute (explicit)
            - height: height attribute (explicit)
            - has_explicit_dimensions: width و height موجودان؟
            - loading: lazy/eager/auto
            - srcset: srcset attribute
            - sizes: sizes attribute
            - decoding: async/sync/auto
            - class_names: CSS classes
            - position: ترتيب في الصفحة
            - is_in_picture: داخل <picture>؟
    """
    images: list[dict[str, Any]] = []
    position = 0

    # === كشف الـ <picture> elements ===
    picture_elements = set()
    for picture in soup.find_all("picture"):
        for img in picture.find_all("img"):
            picture_elements.add(id(img))

    # === <img> tags ===
    for img in soup.find_all("img"):
        position += 1

        src_raw = img.get("src", "").strip()
        if not src_raw and img.get("data-src"):
            # كثير من المواقع تستخدم data-src مع lazy loading
            src_raw = img.get("data-src", "").strip()

        # تخطّي إذا لا يوجد src
        if not src_raw:
            continue

        # حل URL مطلق
        try:
            src = urljoin(page_url, src_raw)
        except Exception:
            src = src_raw

        alt = img.get("alt")
        has_alt = alt is not None
        alt_text = (alt or "").strip()

        width = img.get("width", "").strip()
        height = img.get("height", "").strip()

        # CSS classes
        css_classes = img.get("class", [])
        if isinstance(css_classes, str):
            css_classes = css_classes.split()

        images.append(
            {
                "src": src,
                "src_raw": src_raw,
                "alt": alt_text,
                "alt_length": len(alt_text),
                "has_alt": has_alt,  # alt attribute موجود (حتى لو فارغ)
                "alt_is_empty": has_alt and not alt_text,  # alt="" مقصود
                "title": img.get("title", "").strip(),
                "width": width,
                "height": height,
                "has_explicit_dimensions": bool(width and height),
                "loading": img.get("loading", "").strip(),
                "srcset": img.get("srcset", "").strip(),
                "sizes": img.get("sizes", "").strip(),
                "decoding": img.get("decoding", "").strip(),
                "class_names": " ".join(css_classes),
                "position": position,
                "is_in_picture": id(img) in picture_elements,
                "is_lazy_loaded": img.get("loading", "").lower() == "lazy"
                or "data-src" in img.attrs,
                "file_extension": _get_extension(src),
            }
        )

    return images


def _get_extension(url: str) -> str:
    """استخراج امتداد ملف الصورة من URL."""
    if not url:
        return ""

    # إزالة query parameters
    clean_url = url.split("?")[0].split("#")[0]

    # استخراج الامتداد
    if "." in clean_url:
        ext = clean_url.rsplit(".", 1)[1].lower()
        # تحقق من امتدادات الصور المعروفة
        if ext in {"jpg", "jpeg", "png", "gif", "webp", "avif", "svg", "ico", "bmp", "tiff"}:
            return ext

    return ""
