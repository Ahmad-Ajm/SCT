"""
extractors/og_extractor.py
===========================
استخراج Open Graph و Twitter Card meta tags.
مهم للمشاركة على السوشال ميديا.
"""

from typing import Any
from bs4 import BeautifulSoup


def extract_og_twitter(soup: BeautifulSoup) -> dict[str, Any]:
    """
    استخراج OG و Twitter meta tags.

    Returns:
        dict: {
            # Open Graph
            "og_title": str,
            "og_description": str,
            "og_image": str,
            "og_image_width": str,
            "og_image_height": str,
            "og_image_alt": str,
            "og_url": str,
            "og_type": str,
            "og_site_name": str,
            "og_locale": str,
            "og_video": str,

            # Twitter Card
            "twitter_card": str,  # summary, summary_large_image, etc.
            "twitter_title": str,
            "twitter_description": str,
            "twitter_image": str,
            "twitter_image_alt": str,
            "twitter_site": str,
            "twitter_creator": str,
            "twitter_player": str,

            # Validation
            "has_og": bool,
            "has_twitter": bool,
            "og_complete": bool,  # title + description + image
            "twitter_complete": bool,
        }
    """
    def get_meta_property(prop: str) -> str:
        tag = soup.find("meta", attrs={"property": prop})
        if tag and tag.get("content"):
            return tag["content"].strip()
        return ""

    def get_meta_name(name: str) -> str:
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
        return ""

    # === Open Graph ===
    og = {
        "og_title": get_meta_property("og:title"),
        "og_description": get_meta_property("og:description"),
        "og_image": get_meta_property("og:image"),
        "og_image_width": get_meta_property("og:image:width"),
        "og_image_height": get_meta_property("og:image:height"),
        "og_image_alt": get_meta_property("og:image:alt"),
        "og_url": get_meta_property("og:url"),
        "og_type": get_meta_property("og:type"),
        "og_site_name": get_meta_property("og:site_name"),
        "og_locale": get_meta_property("og:locale"),
        "og_video": get_meta_property("og:video"),
    }

    # === Twitter Card ===
    twitter = {
        "twitter_card": get_meta_name("twitter:card"),
        "twitter_title": get_meta_name("twitter:title"),
        "twitter_description": get_meta_name("twitter:description"),
        "twitter_image": get_meta_name("twitter:image"),
        "twitter_image_alt": get_meta_name("twitter:image:alt"),
        "twitter_site": get_meta_name("twitter:site"),
        "twitter_creator": get_meta_name("twitter:creator"),
        "twitter_player": get_meta_name("twitter:player"),
    }

    # === Validation flags ===
    has_og = any(og.values())
    has_twitter = any(twitter.values())
    og_complete = bool(og["og_title"] and og["og_description"] and og["og_image"])
    twitter_complete = bool(
        twitter["twitter_card"] and twitter["twitter_title"] and twitter["twitter_image"]
    )

    return {
        **og,
        **twitter,
        "has_og": has_og,
        "has_twitter": has_twitter,
        "og_complete": og_complete,
        "twitter_complete": twitter_complete,
    }
