"""
extractors/hreflang_extractor.py
=================================
استخراج Hreflang tags للمواقع متعددة اللغات.

يدعم:
- <link rel="alternate" hreflang="..."> في HTML
- Hreflang في HTTP Link header
- Hreflang في sitemap (يُعالج في sitemap_parser)
"""

from urllib.parse import urljoin
from bs4 import BeautifulSoup


def extract_hreflang(
    soup: BeautifulSoup, headers: dict[str, str], current_url: str
) -> list[dict[str, str]]:
    """
    استخراج كل hreflang tags.

    Returns:
        list[dict]: [
            {
                "hreflang": "ar-SA",
                "href": "https://example.com/",
                "source": "html" أو "header",
                "is_x_default": bool,
            },
            ...
        ]
    """
    results: list[dict[str, str]] = []
    seen = set()  # لتجنّب التكرار

    # === من HTML ===
    for link_tag in soup.find_all("link", rel="alternate", hreflang=True):
        hreflang = link_tag.get("hreflang", "").strip()
        href = link_tag.get("href", "").strip()

        if not hreflang or not href:
            continue

        try:
            absolute_href = urljoin(current_url, href)
        except Exception:
            absolute_href = href

        key = (hreflang.lower(), absolute_href)
        if key in seen:
            continue
        seen.add(key)

        results.append(
            {
                "hreflang": hreflang,
                "href": absolute_href,
                "href_raw": href,
                "source": "html",
                "is_x_default": hreflang.lower() == "x-default",
                "language_code": _extract_language_code(hreflang),
                "region_code": _extract_region_code(hreflang),
            }
        )

    # === من HTTP Link header ===
    link_header = headers.get("Link", "") or headers.get("link", "")
    if link_header:
        for link_part in link_header.split(","):
            link_part = link_part.strip()
            if "hreflang=" not in link_part.lower():
                continue

            # استخراج URL
            if "<" not in link_part or ">" not in link_part:
                continue

            try:
                href = link_part.split("<")[1].split(">")[0].strip()

                # استخراج hreflang
                hreflang = ""
                for param in link_part.split(";"):
                    param = param.strip()
                    if param.lower().startswith("hreflang="):
                        hreflang = param.split("=", 1)[1].strip(' "')
                        break

                if not hreflang or not href:
                    continue

                key = (hreflang.lower(), href)
                if key in seen:
                    continue
                seen.add(key)

                results.append(
                    {
                        "hreflang": hreflang,
                        "href": href,
                        "href_raw": href,
                        "source": "header",
                        "is_x_default": hreflang.lower() == "x-default",
                        "language_code": _extract_language_code(hreflang),
                        "region_code": _extract_region_code(hreflang),
                    }
                )
            except Exception:
                continue

    return results


def _extract_language_code(hreflang: str) -> str:
    """استخراج language code (مثل: ar من ar-SA)."""
    if not hreflang or hreflang.lower() == "x-default":
        return ""
    return hreflang.split("-")[0].lower()


def _extract_region_code(hreflang: str) -> str:
    """استخراج region code (مثل: SA من ar-SA)."""
    if not hreflang or "-" not in hreflang:
        return ""
    parts = hreflang.split("-", 1)
    return parts[1].upper() if len(parts) > 1 else ""
