"""
Crawler package.

Keep imports lazy so lightweight modules such as ``robots_parser`` can be used
without importing BeautifulSoup/aiohttp-dependent crawler engines.
"""

__all__ = ["Crawler", "HTTPClient", "RobotsParser", "SitemapParser"]


def __getattr__(name: str):
    if name == "Crawler":
        from crawler.core import Crawler

        return Crawler
    if name == "HTTPClient":
        from crawler.http_client import HTTPClient

        return HTTPClient
    if name == "RobotsParser":
        from crawler.robots_parser import RobotsParser

        return RobotsParser
    if name == "SitemapParser":
        from crawler.sitemap_parser import SitemapParser

        return SitemapParser
    raise AttributeError(f"module 'crawler' has no attribute {name!r}")
