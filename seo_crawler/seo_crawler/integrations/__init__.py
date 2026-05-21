"""
integrations — التكاملات مع APIs خارجية.

تُفعَّل عبر config.yaml بعد توفّر المفاتيح في .env
"""
from integrations.gsc_api import GSCClient
from integrations.pagespeed_api import PageSpeedClient
from integrations.awt_importer import AWTImporter

__all__ = ["GSCClient", "PageSpeedClient", "AWTImporter"]
