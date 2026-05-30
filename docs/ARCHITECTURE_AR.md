# SCT — البنية والقرارات المعمارية

> الجمهور: مطوّرون يريدون قراءة SCT أو توسيعه أو تفريعه.
> English version: [`ARCHITECTURE.md`](ARCHITECTURE.md).
> للاستخدام كمستخدم نهائي راجع [`USER_GUIDE_AR.md`](USER_GUIDE_AR.md).
> لأعلام سطر الأوامر راجع [`CLI_AR.md`](CLI_AR.md).

---

## 1) نظرة عامة

SCT أداة تدقيق SEO **محلية بالكامل**. تعمل على جهاز المستخدم، تعرض واجهة FastAPI صغيرة
على `127.0.0.1`، ولا ترسل أي شيء للخارج. كل تكامل خارجي (GSC, GA4, PageSpeed, CrUX, AI)
**اختياري ومطفأ افتراضياً**؛ اعتمادات المستخدم تبقى محلياً ولا تُلتزم في git.

```
                ┌──────────────────────────────────────────────────────┐
                │             الواجهة المرئية (FastAPI + Jinja)       │
                │   /     /jobs/<id>     /jobs/<id>/board    /logs ... │
                └──────────────┬────────────────────────┬──────────────┘
                               │ HTTP                   │ HTTP
                               ▼                        ▼
                       ┌───────────────┐       ┌────────────────┐
                       │  job_runner   │──────►│  subprocess    │
                       │  (مُنسِّق)     │       │  (main.py)     │
                       └───────┬───────┘       └────────┬───────┘
                               │                        │
                               │           ┌────────────┴──────────────┐
                               │           ▼                           ▼
                               │   ┌───────────────┐         ┌──────────────────┐
                               │   │ زاحف (async   │         │  محلّلات         │
                               │   │ aiohttp +     │────────►│  (دوال نقيّة    │
                               │   │ sync احتياط)  │         │   فوق الصفوف)   │
                               │   └────────┬───────┘         └────────┬─────────┘
                               │            │                          │
                               │            ▼                          ▼
                               │       ┌─────────┐              ┌────────────────┐
                               │       │ SQLite  │              │ التقرير:       │
                               │       │ لكل مهمة│              │ محرّك الأولوية │
                               │       └─────────┘              │ build_unified  │
                               │                                └────────┬───────┘
                               │                                         │
                               │           ┌─────────────────────────────┘
                               │           ▼
                               │   ┌─────────────────────────────────────────────┐
                               │   │ المصدّرات: CSV / Excel / XML / JSON /        │
                               │   │   HTML + PDF (Playwright) / sitemap.xml     │
                               │   └─────────────────────────────────────────────┘
                               │
                               ▼
                  ┌──────────────────────────────────────────────────────┐
                  │ تكاملات اختيارية (مطفأة افتراضياً):                  │
                  │   GSC · GA4 · PageSpeed · CrUX · Lighthouse · AWT    │
                  │   مستشار AI · فحص الوصولية axe-core                  │
                  └──────────────────────────────────────────────────────┘
```

---

## 2) خريطة الوحدات

```
seo_crawler/seo_crawler/
├── main.py                     المُنسِّق (run_analysis, run_export, _run_integrations_only)
├── config_presets.py           قوالب منصّات التجارة (زد/سلة/Shopify/WooCommerce)
├── crawler/
│   ├── async_core.py             الزاحف غير المتزامن (workers + queue + hook لتصيير JS)
│   ├── core.py                   الزاحف المتزامن (احتياط)
│   ├── js_renderer.py            غلاف Playwright (تصيير JS + حقن axe)
│   ├── adaptive_throttle.py      تباطؤ تكيّفي عند 429/5xx، تعافٍ مع الردود الصحّية
│   └── robots_parser.py          robots.txt مع حدّ حجم تدفّقي
├── extractors/                 مستخرجات لكل صفحة (محتوى، meta، روابط، schema…)
├── analyzers/                  محلّلات نقيّة فوق بيانات الزحف
│   ├── seo_issues.py             يجمع كل شيء في قائمة موسومة بالشدّة
│   ├── broken_links.py, duplicate_detector.py, canonical_analyzer.py, …
│   ├── link_score.py             PageRank داخلي
│   ├── near_duplicate.py         SimHash + LSH
│   ├── gsc_insights.py           تكلّس الكلمات + فُرَص الروابط
│   ├── crawl_compare.py          مقارنة قبل/بعد بين زحفتين
│   ├── log_analyzer.py           Apache/Nginx CLF + استخراج زحف Googlebot
│   ├── accessibility.py          ملخّص نتائج axe-core
│   └── hints.py                  impact/effort/why/how لكل مشكلة
├── integrations/               واجهات APIs خارجية (كلها مطفأة افتراضياً)
│   ├── google_auth.py            OAuth client_secret + token (بوابة allow_interactive)
│   ├── gsc_api.py                Search Console + URL Inspection
│   ├── ga4_api.py                GA4 Data API + Admin API (سرد الخصائص)
│   ├── pagespeed_api.py          PageSpeed + استخراج جداول Lighthouse العميقة
│   ├── crux_history.py           سلسلة Core Web Vitals الزمنية
│   └── awt_importer.py           استيراد CSV من AWT (Ahrefs Webmaster)
├── reporting/
│   ├── report_join.py            build_unified: تقني × GSC × GA4 لكل URL
│   ├── opportunities.py          compute_opportunities (الأولوية القديمة)
│   ├── priority_engine.py        v2: severity × impact × ease × confidence + Action Board
│   ├── url_detail.py             تفاصيل لكل URL للوحة التفاصيل الجانبية
│   └── report_builder.py         يُحمّل audit JSON ويُنتج HTML/PDF
├── exporters/                  csv_exporter, excel_exporter, json_exporter,
│                                xml_exporter, html_exporter, sitemap_generator
├── storage/                    قاعدة بيانات SQLite + APICache
└── utils/                      helpers (حارس SSRF، محيِّد الصيغ، normalize_url)،
                                logger، observability، auto_install

webapp/
├── app.py                      تطبيق FastAPI (routes + endpoints + /api/jobs/…)
├── job_runner.py               JobRunner: يُطلق subprocess، يتتبّع الحالة، يحذف المهام
├── run.py                      نقطة دخول uvicorn
├── static/                     app.css, i18n.js (قاموسا ar + en)
└── templates/                  index.html, job.html, board.html, compare.html, logs.html,
                                explore.html
tests/
└── test_core_behaviors.py      سلسلة اختبارات الانحدار (~70 اختباراً، كلها دون اتصال)
```

---

## 3) تدفّق البيانات (تدقيق كامل)

1. **يقدّم المستخدم النموذج** → `POST /api/start` → `JobRunner.start(overrides)`.
2. `JobRunner._build_job_config` يكتب `config.yaml` لكل مهمة تحت
   `webapp_jobs/<job_id>/`. الأسرار (مفاتيح PageSpeed/AI) تُجرَّد من الملف وتُمرَّر
   عبر `os.environ` للعملية الفرعية بدلاً منه.
3. `JobRunner.start` يطلق `python -m seo_crawler.main` كعملية ابن مع
   `SCT_PROGRESS_FILE=…` و`SCT_NONINTERACTIVE=1`.
4. **`main.main_async`** ينسّق التشغيل:
   - `run_analysis` → المحلّلات (نقيّة) تنتج قواميس `analysis["…"]`.
   - `run_integrations` → عملاء اختياريون يجلبون GSC/GA4/PageSpeed/CrUX.
   - `build_unified(pages, analysis, gsc_pages, ga4_landing_pages)` يدمج لكل URL.
   - `compute_opportunities(unified_rows)` (قديم) و
     `compute_priority(unified_rows, platform)` (v2 + Action Board).
   - `run_export` يكتب CSV / Excel / JSON / XML / HTML / PDF / sitemap.
5. **الواجهة تستطلع التقدّم** عبر `/api/jobs/<id>/events` (SSE) حتى الانتهاء.
6. **المخرجات** تُسرَد في `/api/jobs/<id>/files`؛ العروض الثانوية
   (`/board`, `/explore`, `/compare`, لوحة تفاصيل URL) تقرأ ملف audit JSON.

---

## 4) قرارات معمارية أساسية

1. **محلي بالكامل، بلا backend مركزي.** كل مستخدم يشغّل نسخته. لا تطبيق OAuth مشترك،
   لا مفتاح PageSpeed مشترك، لا قاعدة بيانات مشتركة — وبالتالي لا حصّة مشتركة يستنزفها
   مستخدم بالنيابة عن آخر.
2. **زاحف async مع احتياط sync.** الـasync أسرع 5–10×؛ الـsync يبقى للتشخيص ولبيئات
   تتعطّل فيها aiohttp.
3. **SQLite لكل مهمة** للاستئناف والنجاة من الانهيارات. `webapp_jobs/<id>/state/` لكل
   مهمة مستقلّ ويمكن حذفه دون أي أثر على المهام الأخرى.
4. **ترتيب أولويات حتمي، الذكاء الاصطناعي للنصوص فقط.** درجة محرّك الأولويات
   (`severity × impact × ease × confidence`) صيغة شفّافة في
   `reporting/priority_engine.py`. الذكاء الاصطناعي للسرد فقط (ملخّص تنفيذي، إعادة
   صياغة مقترحة)، لا للترتيب نفسه. يبقى المنتج قابلاً للتفسير وقابلاً للإعادة ومجانياً
   التشغيل دون LLM.
5. **كل التكاملات مطفأة افتراضياً.** كل كتلة إعداد قيمتها الافتراضية `enabled: false`.
   الأداة تُجري التدقيق التقني دون أي خدمة خارجية.
6. **لا أسرار في المستودع.** `client_secret.json`، `*_token.json`، `.env`،
   و`credentials/` كلها ضمن gitignore. اعتمادات المهام تحت `webapp_jobs/_google/`
   (ضمن gitignore أيضاً).
7. **كل مستخدم/وكالة بعميل Desktop OAuth خاص بهم.** الحصّة وتحذير «تطبيق غير موثّق»
   مرتبطان بمشروع OAuth — امتلاك خاصّ بك يعزلك ويرفع سقف 100 مستخدم.
8. **ثنائية لغة بالتصميم.** كل مفتاح `data-i18n` له مدخل في `ar` و`en`
   (`webapp/static/i18n.js`). سكربت تدقيق صغير يكشف الانحراف.
9. **تدفّق + حدود حجم لكل جلب خارجي.** robots.txt (2MB)، PageSpeed JSON، رفع اللوغ
   (500MB)، رفع client_secret (64KB)، قراءة audit JSON (حارس 300MB).
10. **أمان متعدّد الطبقات.** حارس SSRF على روابط المستخدم، محيِّد حقن صيغ CSV/Excel،
    `defusedxml` للـXML، حدود قنابل gzip، فحوصات حصر تحت
    `_safe_under_jobs`/`_safe_output_file`، بوّابة `SCT_NONINTERACTIVE` في OAuth بحيث
    لا تعلّق عمليات الخلفية على متصفّح أبداً.

---

## 5) نقاط التوسعة

- **محلّل جديد:** راجع `CONTRIBUTING_AR.md §5`. النمط: «دالّة نقيّة → ربط في main →
  تصدير CSV → اختبار».
- **تكامل جديد:** راجع `CONTRIBUTING_AR.md §6`. النمط: «إعداد off-by-default → عميل
  صغير → ربط في run_integrations → بطاقة UI بزرّ اختبار».
- **صيغة تصدير جديدة:** أضف وحدة في `exporters/`، اربطها في `main.run_export`، سجّلها
  في `output.formats`.
- **تبويب UI جديد:** راجع `CONTRIBUTING_AR.md §7`. JS الموجود يلتقط `data-tab` /
  `data-pane` تلقائياً.
- **علم CLI جديد:** أضف إلى `argparse.ArgumentParser` في `main.py`، ثم وثّق في
  `docs/CLI_AR.md`.

---

## 6) أين تبحث عن…

| السؤال | الملف(ات) |
|---|---|
| كيف تُزحف صفحة واحدة وتُخزّن؟ | `crawler/async_core.py::_crawl_page` |
| كيف تُجمَع المشاكل وتُوسَم؟ | `analyzers/seo_issues.py` + `analyzers/hints.py` |
| كيف تُحسَب درجة الأولوية؟ | `reporting/priority_engine.py::compute_priority` |
| كيف تُتحكَّم التكاملات بالتفعيل؟ | `main.py::run_integrations` + `config.example.yaml::integrations` |
| كيف تصل الأسرار للعملية الفرعية؟ | `webapp/job_runner.py::_build_job_config` (`_secret_env` → بيئة `start`) |
| كيف تعرف الواجهة بحالة المهمة؟ | `/api/jobs/<id>/events` SSE + `webapp_jobs/<id>/progress.json` |
| كيف تُحفظ/تُلغى الـ tokens؟ | `webapp/app.py::/api/google/upload|authorize|disconnect` + `_google_dir()` |
| كيف تتبدّل اللغة في i18n؟ | `webapp/static/i18n.js` (يُحمَّل في كل صفحة؛ زرّ `langToggle`) |

---

## 7) الاختبارات

السلسلة كاملة **حتمية ودون اتصال** وتعمل في ثوانٍ:

```bash
python -B -m unittest discover -s tests
```

التكاملات الحيّة (GSC, GA4, PageSpeed, AI) تُختبر عبر **parsers** على ردود اصطناعية —
دون شبكة حقيقية. الزاحف يُختبر مقابل خادم HTTP صغير داخل العملية
(`tests/test_core_behaviors.py`).

راجع `CONTRIBUTING_AR.md §1` لبوّابة الالتزام الكاملة.
