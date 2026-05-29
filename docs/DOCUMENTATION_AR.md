# توثيق SCT الكامل (Simple Crawler Tool)

أداة زحف وتدقيق SEO تقني مبنية ببايثون، مع واجهة محلية وتقارير CSV/JSON/Excel/HTML/PDF،
وتكاملات اختيارية مع GSC/GA4/Lighthouse، وتقرير موحّد يربط المشاكل التقنية بالأداء البحثي.

> هذا المرجع الكامل. للبدء السريع راجع `README_ar.md`. لإعداد التكاملات راجع
> `docs/EXTERNAL_TOOLS_GUIDE_AR.md`.

## المحتويات
1. نظرة عامة والفلسفة
2. التثبيت والتشغيل
3. المعمارية وتدفق البيانات
4. خريطة الوحدات
5. أوضاع الزحف واستراتيجيات اكتشاف الروابط
6. مرجع الإعدادات الكامل
7. المخرجات
8. المحلّلات
9. التكاملات والتقرير الموحّد
10. الواجهة المرئية
11. الأمان والخصوصية
12. التوسعة (إضافة محلل/مستخرج)
13. الاختبارات والجودة
14. استكشاف الأخطاء

---

## 1) نظرة عامة والفلسفة
- **مركز زحف داخلي**: يجمع الصفحات والروابط والموارد والمشاكل التقنية.
- **يرشد لا يُكرّر**: للأداء/الوصول/الأمان العميق يرشد لأدوات مجانية (Lighthouse/axe/ZAP) ويستورد مخرجاتها.
- **اختياري وبلا مفاتيح في الكود**: كل تكامل خارجي معطّل افتراضياً؛ المفاتيح في `.env`/إعداد محلي.
- **يعمل بلا إنترنت/حسابات** للقسم التقني.

## 2) التثبيت والتشغيل

```bash
python -m pip install -r requirements.txt
# اختياري لتصيير JS وتقارير PDF:
playwright install chromium
# اختياري لـ GA4:
pip install google-analytics-data
```

**سطر الأوامر (CLI):**
```bash
python main.py --help
python main.py --mode audit --url https://example.com/
python main.py --mode competitor --url https://competitor.example/
python main.py --mode compare
python main.py --analyze-only --skip-external
python main.py --no-resume        # بدء جديد
python main.py --clear-cache
```

**الواجهة المرئية (Web UI):**
```bash
python -m pip install fastapi "uvicorn[standard]" jinja2 python-multipart
python webapp/run.py              # ثم افتح http://127.0.0.1:8000
```

## 3) المعمارية وتدفق البيانات

```
main.py (root launcher) ──► seo_crawler/seo_crawler/main.py (التنسيق)
   │
   ├─ Phase 1: الزحف   → AsyncCrawler (افتراضي) أو Crawler (sync) → SQLite
   ├─ Phase 2: التحليل → analyzers/* (تقرأ من الزاحف/DB)
   ├─ Phase 2.5: الروابط الخارجية → checkers/external_links_checker
   ├─ Phase 3: التكاملات → integrations/* (GSC/GA4/PageSpeed/Lighthouse/AWT)
   ├─ التقرير الموحّد → reporting/report_join + opportunities
   └─ Phase 4: التصدير → exporters/* (CSV/JSON/Excel/HTML/PDF/XML/metrics)

الواجهة: webapp/app.py (FastAPI) → webapp/job_runner.py يشغّل main.py كعملية فرعية،
ويتابع التقدّم عبر progress.json (SSE).
```

تدفق الزحف async (مبسّط): طابور أساسي (الرئيسية + الروابط المكتشفة BFS) ثم بذور sitemap
عند نضوبه؛ كل عامل: claim تحت قفل → فحص depth/filters/robots/SSRF → جلب → (تصيير JS اختياري)
→ استخراج → حفظ في DB (حذف-ثم-إدراج لتفادي التكرار) → اكتشاف روابط جديدة.

## 4) خريطة الوحدات

| المجلد | الدور |
|---|---|
| `crawler/` | المحرّك: `async_core.py` (الافتراضي)، `core.py` (sync)، `http_client.py`، `robots_parser.py`، `sitemap_parser.py`، `js_renderer.py` (JSRenderer + JSRendererAsync) |
| `extractors/` | استخراج لكل عنصر: meta, headings, links, images, canonical, hreflang, og, schema, content, headers, mixed_content, resources, custom |
| `analyzers/` | التحليل: broken_links, canonical_analyzer, duplicate_detector, hreflang_validator, images_analyzer, orphan_finder, redirect_analyzer, resources_analyzer, schema_validator, security_analyzer, seo_issues, sitemap_diff, thin_content, url_issues |
| `reporting/` | `report_join.py` (دمج تقني+GSC+GA4)، `opportunities.py` (الأولويات) |
| `integrations/` | GSC, GA4, PageSpeed, Lighthouse import, AWT |
| `checkers/` | فحص الروابط الخارجية async |
| `exporters/` | CSV, JSON, Excel, HTML, PDF, XML, report_builder |
| `storage/` | `database.py` (SQLite + migrations)، `cache.py` (API cache) |
| `modes/` | audit, competitor, compare, base |
| `utils/` | helpers (normalize_url, is_internal_url, is_safe_remote_url, neutralize_formula...)، logger، monitoring، state_manager |
| `webapp/` | app.py, job_runner.py, run.py, templates/, static/ |

## 5) أوضاع الزحف واستراتيجيات اكتشاف الروابط

**الأوضاع (`--mode`):**
- `audit`: تدقيق كامل لموقعك (كل المحلّلات + روابط خارجية + تكاملات).
- `competitor`: زحف خفيف ومحترم لموقع منافس.
- `compare`: يزحف عدة مواقع (`sites_to_compare`) ويُخرج `comparison_summary.json`.

**استراتيجية البذور (`crawl.seed_strategy`):**
- `homepage`: الرئيسية + اتباع الروابط فقط.
- `sitemap`: إغراق الطابور بروابط sitemap أولاً (تغطية واسعة).
- `hybrid` (موصى به): الرئيسية + الروابط أولاً، ثم sitemap كبذور مؤجَّلة.

## 6) مرجع الإعدادات الكامل (`config.yaml`)

- `site`: `start_url`، `domain`، `additional_internal_domains`، `platform_preset`
  (`zid`/`salla`/`shopify`/`woocommerce` — يضيف أنماط استبعاد موصى بها).
- `crawl`: `max_pages` (0=بلا حد)، `max_depth`، `delay_seconds`، `concurrent_requests`،
  `timeout_seconds`، `retry_attempts`، `respect_robots`، `robots_failure_policy`،
  `seed_strategy`، `verify_ssl`، `allow_private_hosts`، `max_page_size_mb`،
  `follow_redirects`، `max_redirect_hops`، `user_agent`، و`adaptive_throttle`
  (`enabled`/`min_delay`/`max_delay`/`step_up`/`step_down`/`slow_ms` — تحكّم تكيّفي بالسرعة).
- `javascript`: `enabled`، `mode` (all/sample/on_empty_content)، `max_pages`،
  `concurrency`، `block_resource_types`، `wait_until`، `timeout`، `browser`، `headless`.
- `extraction`: `extract_*` لكل عنصر (meta/headings/links/images/schema/hreflang/og/
  canonical/pagination/headers/content/mixed_content/resources)، و`check_resource_status`
  (فحص حالة HTTP لكل مورد — مكلف، مطفأ افتراضياً ويتطلّب `extract_resources`).
- `custom_extraction`: `enabled` + `rules` (css/regex).
- `filters`: `exclude_patterns`، `include_patterns` (تدعم substring و glob)،
  `allowed_content_types`، `respect_nofollow`.
- `analysis`: عتبات (thin_content، title/description lengths، url_max_length،
  `url_flag_non_ascii`...).
- `output`: `output_dir`، `formats` (csv/json/excel/html/pdf/xml)، `encoding`،
  `timestamped_folder`، `json_full` (افتراضي false — لا يُضمّن المصفوفات الخام الضخمة في JSON؛
  متوفّرة في CSV/Excel/XML)، `xml_max_rows` (سقف صفوف XML لكل مجموعة، 0 = بلا حد)،
  `generate_sitemap` (توليد `sitemap.xml` من الصفحات القابلة للفهرسة).
- `report`: `language` (ar/en)، `audience` (`expert` تفصيلي | `client` مختصر مبسّط |
  `both` تقريران)، `client_name`، `logo_url`، `max_rows`، `unified`.
- `state`: `state_dir`، `save_interval`، `resume_if_exists`، `use_database`، `cache_ttl_days`.
- `external_check`: `enabled`، `timeout`، `concurrent`، `retry_attempts`، `verify_ssl`.
- `integrations`: `gsc` (+`url_inspection`/`inspect_max_urls` لحالة الفهرسة الحقيقية)،
  `pagespeed` (+`save_raw_json` للجداول العميقة، +`crux_history` لاتجاه CWV)، `awt`،
  `lighthouse`، `ga4`، و`ai` (مستشار الذكاء الاصطناعي:
  `enabled`/`provider`/`model`/`base_url`/`api_key`/`timeout`/`max_opportunities`)
  — كلها معطّلة افتراضياً.
- `logging`: `level`، `log_dir`، `console_output`، `file_output`، `max_log_size_mb`، `backup_count`.
- `observability`: `enabled`، `log_function_calls`، `log_url_events`، `slow_call_ms`، `slow_call_summary`.

## 7) المخرجات

داخل مجلد مخرجات (مؤرّخ افتراضياً)، أو `webapp_jobs/<job_id>/output/` للواجهة:
- `audit_<domain>_<ts>.json`: التدقيق الكامل (كل المصادر).
- `audit_<domain>_<ts>.xlsx`: Excel متعدد الأوراق (تسليم العميل).
- `report_<domain>_<ts>.html` / `.pdf`: التقرير الموحّد (يحتاج PDF: Playwright).
  في وضع `audience: both` يصدر ملفّان: `report_..._client.*` (مختصر للعميل: تقييم عام
  + أهم المشاكل بلغة واضحة) و`report_..._expert.*` (تفصيلي تقني كامل).
- `csv/`: pages, inlinks, outlinks_external, all_links, images, headings, schema, redirects,
  redirect_chains/loops/issues, headers, seo_issues, duplicates, orphans, thin_content,
  pages_4xx/5xx/404_with_inlinks, images_no_alt/no_dimensions, url_issues, canonical_issues,
  security_issues, pagination/pagination_issues, hreflang_issues, resources, resource_issues,
  resource_status, custom_extraction, excluded_urls, gsc_pages/gsc_queries,
  ga4_landing_pages/ga4_channels, priority_opportunities, ai_recommendations,
  lighthouse_import, js_diff.
- مخرجات PageSpeed العميقة (عند تفعيل التكامل): `pagespeed`, `pagespeed_opportunities`,
  و**الجداول المنظّمة**: `pagespeed_audits` (كل التدقيقات)، `pagespeed_network_requests`
  (كل الطلبات)، `pagespeed_js_treemap` (بايتات السكربتات + نسبة غير المستخدم)،
  `pagespeed_failed_audits` (المشاكل الحقيقية فقط).
- تحليلات GSC: `keyword_cannibalization` (تكلّس الكلمات)، `internal_link_opportunities`
  (صفحات بظهور عالٍ وروابط داخلية قليلة)، و`gsc_index_status` (عند تفعيل URL Inspection).
- `crux_history` (عند تفعيل CrUX History): اتجاه Core Web Vitals عبر الزمن.
- `sitemap.xml` (عند تفعيل `output.generate_sitemap`): من الصفحات القابلة للفهرسة.
- محرّك الأولويات v2: `page_priority.csv` (درجة لكل صفحة + نوعها + المالك + سهولة الإصلاح +
  تفكيك العوامل) و`action_board.csv` (لوحة عمل مرتّبة: افعل الآن / يحتاج محتوى / يحتاج مطوّراً /
  يحتاج دعم المنصّة / لاحقاً / منخفض الأثر)، وقسم «لوحة العمل» في تقرير الخبير.
- كل مشكلة في `seo_issues` تحمل الآن: `impact`/`effort`/`why_it_matters`/`how_to_fix`/`priority_score`.
- `metrics.json`: عدّادات/توقيتات/أحداث + ملخّص أبطأ المراحل.

## 8) المحلّلات (مختصر)
- **seo_issues**: تجميع موحّد بالأولوية (Critical/High/Medium/Low) عبر 23 نوع مشكلة.
- **broken_links / redirect_analyzer**: 4xx/5xx، 404 بروابط واردة، سلاسل/حلقات redirect.
- **duplicate_detector**: عناوين/أوصاف/H1/محتوى مكرر.
- **canonical_analyzer**: loops، إلى non-200/non-indexable/خارجي، سلاسل.
- **thin_content / orphan_finder**: محتوى رقيق، صفحات يتيمة/قليلة الروابط.
- **images_analyzer**: بدون alt/أبعاد/lazy، صيغ قديمة (مع عدّ فريد).
- **schema_validator / hreflang_validator / sitemap_diff**: JSON-LD+microdata، تبادلية hreflang (روابط الإرجاع)، تغطية sitemap.
- **pagination_analyzer**: تسلسل rel=next/prev، تبادلية مكسورة، أهداف 4xx/noindex، canonical غير ذاتي على صفحات مرقّمة.
- **url_issues / security_analyzer / resources_analyzer**: نظافة URL، ترويسات الأمان، جرد الموارد (وحالتها عبر `check_resource_status`).
- **link_score / near_duplicate**: PageRank داخلي لكل صفحة، وكشف الصفحات شبه‑المكرّرة (SimHash + LSH).
- **gsc_insights**: تكلّس الكلمات (صفحات تتنافس على نفس الاستعلام) وفُرَص الروابط الداخلية
  (ظهور عالٍ + روابط واردة قليلة) من بيانات GSC.
- **hints**: يُثري كل مشكلة بـ`impact`/`effort`/`why_it_matters`/`how_to_fix`/`priority_score`.
- **crawl_compare**: مقارنة زمنية بين زحفتين لنفس الموقع (مُصلَح/جديد/باقٍ + فروق الصفحات).
- **accessibility**: تلخيص نتائج axe-core (اختياري عبر متصفّح التصيير).

## 9) التكاملات والتقرير الموحّد
- **GSC**: نقرات/ظهور/CTR/ترتيب per-page وper-query (OAuth بمفتاحك).
- **GA4**: جلسات/مستخدمون/تفاعل لصفحات الهبوط + القنوات (service account).
- **Lighthouse/PageSpeed**: استيراد JSON محلي (بلا مفاتيح) أو PageSpeed API.
- **AWT**: استيراد CSV من Ahrefs Webmaster.
- **التقرير الموحّد** (`report.unified`): يدمج تقني + GSC + GA4، ويضيف قسم **«أولويات الإصلاح»**
  حيث `priority_score = الأثر (نقرات/جلسات) × شدّة المشكلة التقنية` لترتيب أهم ما يُصلَح.
- **محرّك الأولويات v2** (`reporting/priority_engine.py`، حتمي بلا ذكاء): درجة شفّافة لكل صفحة
  `الشدّة × الأثر × سهولة الإصلاح × الثقة`، حيث الأثر = الطلب البحثي + القيمة التجارية +
  أهمية الصفحة (نوعها/عمقها/روابطها). يصنّف نوع الصفحة وسهولة الإصلاح ومالكه (محتوى/SEO/مطوّر/
  دعم المنصّة) ونطاق الأولوية، ثم يبني **لوحة عمل**. يعمل حتى بلا تكاملات.
- **مستشار الذكاء الاصطناعي** (`integrations.ai`): محايد للمزوّد عبر `requests` فقط —
  OpenAI/DeepSeek/OpenRouter/HuggingFace (متوافق مع OpenAI) و Gemini و`openai_compatible`
  للنماذج المحلية. يقرأ ملخّص التدقيق + الفرص ويُرجع ملخّصاً تنفيذياً وتوصيات مرتّبة. المفتاح
  من الإعداد المحلي أو `AI_API_KEY` (لا يُخزَّن في المستودع)، ولا تُرسَل بيانات مستخدمين (PII).

## 10) الواجهة المرئية
- `/`: نموذج الزحف (الرابط، الوضع، استراتيجية، السرعة، ما يُجمَع، الصيغ، تنسيق التقرير
  ونوعه: خبير/عميل/كلاهما، إعدادات متقدمة: تكاملات/استخراج مخصّص/عتبات/فحص حالة الموارد).
- `/jobs/<id>`: متابعة مباشرة (SSE): مراحل، عدّاد وقت، عدّادات، إيقاف، تنزيل النتائج، إعادة بناء التقرير.
- `/jobs/<id>/explore`: مستكشف الصفحات (تصفية/فرز/بحث + تنزيل CSV للمصفّى).
- تبديل اللغة EN/AR، ومهمة واحدة نشطة في كل وقت.

## 11) الأمان والخصوصية
- لا مفاتيح/اعتمادات في المستودع؛ `.env`، `credentials/`، `external_data/`، `webapp_jobs/`، `output/`، `state/`، `logs/` في `.gitignore`.
- حماية SSRF (`is_safe_remote_url`) على وجهات الزحف/redirect/sitemap.
- XXE: `defusedxml`. قنابل gzip: سقف فك ضغط. حقن الصيغ: تحييد CSV/Excel.
- لا تشغيل فحص أمني هجومي تلقائي. لا جمع PII من GA4.
- مفاتيح الأسرار (PageSpeed، الذكاء الاصطناعي) لا تُكتب في إعداد المهمة على القرص؛ تُمرَّر
  للعملية الفرعية عبر متغيّرات بيئة (`PAGESPEED_API_KEY`، `AI_API_KEY`). مستشار الذكاء
  الاصطناعي لا يُرسل بيانات مستخدمين — فقط روابط/أنواع مشاكل/أرقام مجمّعة.

## 12) التوسعة
- **محلل جديد**: أضف `analyzers/x.py` بدالة `analyze_x(...)`, ثم استدعِها في `main.run_analysis`
  وأضِف اسمها في `modes/audit.get_analyzers()`، وصدّرها في CSV/JSON.
- **مستخرِج جديد**: أضف `extractors/x.py`, واربطه في `_extract_all` (sync+async) و`extract_x` config.
- **قاعدة استخراج مخصّص**: عبر `custom_extraction.rules` (لا كود) أو الواجهة.
- **عمود DB جديد**: أضِفه في `SCHEMA_SQL` + `_PAGE_MIGRATIONS`/`_HEADER_MIGRATIONS`.

## 13) الاختبارات والجودة
```bash
python -B -m compileall -q seo_crawler webapp
python -B -m unittest discover -s tests
```
GitHub Actions يشغّل compile/tests على Python 3.10–3.12.

## 14) استكشاف الأخطاء
- **0 صفحات/الكل فاشل**: راجع `webapp_jobs/<id>/logs/` و`run.log`؛ غالباً مشكلة شبكة/ترميز.
- **PDF لا يُولَّد**: `playwright install chromium`.
- **GA4 لا يعمل**: `pip install google-analytics-data` + property_id + اعتماد صحيح.
- **بطء**: قلّل `max_pages` أو ارفع السرعة (مع احترام الموقع)؛ الموقع نفسه قد يكون بطيئاً.
- **الإيقاف لا يُظهر تنزيلات**: تأكّد أنك على نسخة فيها معالجة SIGBREAK (الإصدار الحالي).
- **قراءة اللوغ**: شريط tqdm مُعطّل في الواجهة (run.log نظيف؛ التقدّم الحيّ من `progress.json`).
  أخطاء الجلب المؤقتة (شبكة/مهلة، أُعيدت المحاولة) تظهر كسطر WARNING وعدّاد، وتُحصى أيضاً في
  `metrics.json` (`crawler.fetch.errors`). الروابط الخارجية المحجوبة (401/403/429) تُعرض
  منفصلة عن «المعطوبة» لأنها حجب من السيرفر لا أعطال.
- **ملفات الصور بلا alt/أبعاد**: `images_no_alt.csv` و`images_no_dimensions.csv` تحوي كل
  الحالات (غير مقصوصة)؛ بينما عيّنة التقرير/JSON محدودة لأغراض العرض فقط.
