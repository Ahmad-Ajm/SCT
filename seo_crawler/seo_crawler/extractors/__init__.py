"""
extractors — حزمة استخراج البيانات من HTML.

كل extractor دالة pure تأخذ BeautifulSoup و/أو headers
وتُرجع dict أو list منظّمة.
"""
from extractors.canonical_extractor import extract_canonical
from extractors.content_extractor import extract_content
from extractors.headers_extractor import extract_headers
from extractors.headings_extractor import extract_headings
from extractors.hreflang_extractor import extract_hreflang
from extractors.images_extractor import extract_images
from extractors.links_extractor import extract_links
from extractors.meta_extractor import extract_meta
from extractors.mixed_content import detect_mixed_content
from extractors.og_extractor import extract_og_twitter
from extractors.schema_extractor import extract_schema

__all__ = [
    "extract_canonical",
    "extract_content",
    "extract_headers",
    "extract_headings",
    "extract_hreflang",
    "extract_images",
    "extract_links",
    "extract_meta",
    "detect_mixed_content",
    "extract_og_twitter",
    "extract_schema",
]
