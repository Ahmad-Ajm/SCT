"""
seo_crawler/services/ — قطع منفصلة كانت في main.py حتّى v1.11.

v1.12 REFACTOR-services: تفكيك main.py (2,300 LOC) إلى وحدات صغيرة لكلّ
مهمّة منفصلة (config, progress, deferred, db facade, ai, crawl, analysis,
external check, integrations, export). main.py لا تزال نقطة CLI الموحَّدة
وتُعيد تصدير كلّ الـAPI القديم للتوافق العكسي.

ترتيب الـtiers (يحدّد اتّجاه الاستيراد المسموح):
  Tier 0 (leaves):  progress_service, deferred_service, _utils
  Tier 1:           config_service, db_facade, ai_service
  Tier 2 (mid):     crawl_service, analysis_service
  Tier 3:           external_check_service, integrations_service
  Tier 4 (heavy):   export_service
  Tier 5 (orch):    integrations_only_service, compare_service

Tier أعلى يستورد من Tier أدنى — لا العكس. منع الاستيراد الدائري بنياً.
"""
