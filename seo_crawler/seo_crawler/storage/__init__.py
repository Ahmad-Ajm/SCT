"""
storage — حزمة تخزين البيانات.

تستخدم SQLite بدلاً من الذاكرة لدعم مواقع كبيرة جداً.
المزايا:
- استهلاك ذاكرة أقل بكثير (50 MB لـ 100K صفحة بدلاً من 5 GB)
- queries سريعة (indexed)
- استئناف فوري بدون JSON load
- استعلامات معقدة (SQL)
- ضغط تلقائي
"""
from storage.database import CrawlDatabase
from storage.cache import APICache

__all__ = ["CrawlDatabase", "APICache"]
