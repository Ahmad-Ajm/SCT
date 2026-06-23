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
├── main.py                     نقطة دخول CLI رفيعة (argparse + توجيه إلى services)
├── config_presets.py           قوالب المنصّات — Zid/Salla/Shopify/Woo للمتاجر،
│                                و**WordPress** (v1.13.5) لمواقع CMS؛ `apply_preset()` +
│                                `detect_platform()` (توقيعات، Woo يفوز على التداخل)
├── services/                   v1.12 refactor: main.py 2,339 → 513 سطراً بفصل:
│   ├── analysis_service.py       run_analysis (تنسيق المحلّلات على الصفوف)
│   ├── crawl_service.py          محرّك الزحف async + sync
│   ├── export_service.py         run_export (CSV / Excel / JSON / XML / HTML / PDF / sitemap)
│   ├── integrations_service.py   run_integrations (جلب التكاملات + التخزين)
│   ├── integrations_only_service.py  run_integrations_only (مسار --integrations-only)
│   ├── compare_service.py        محرّك مقارنة الزحف الزمنية
│   ├── deferred_service.py       ربط مصنّف Phase 2 (find + inject seeds)
│   ├── progress_service.py       الكتابة في SCT_PROGRESS_FILE
│   ├── config_service.py         load_config + validate_config + دمج الطبقات
│   ├── ai_service.py             غلاف مستشار الذكاء (نصوص فقط، ليس ترتيباً)
│   ├── db_facade.py              واجهة SQLite رفيعة للخدمات
│   ├── external_check_service.py توزيع HEAD على الروابط الخارجية
│   ├── integrations_summary.py   عرض ملخّص للتكاملات لكل مهمة
│   └── export_helpers.py         تنسيقات مشتركة عبر المُصدِّرات
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
│   ├── url_classifier.py         مصنّف Phase-1/Phase-2 (v1.08)
│   └── hints.py                  impact/effort/why/how لكل مشكلة
├── integrations/               واجهات APIs خارجية (كلها مطفأة افتراضياً)
│   ├── google_auth.py            OAuth client_secret + token (بوابة allow_interactive)
│   ├── gsc_api.py                Search Console + URL Inspection
│   ├── ga4_api.py                GA4 Data API + Admin API (سرد الخصائص)
│   ├── pagespeed_api.py          PageSpeed + استخراج جداول Lighthouse العميقة
│   ├── lighthouse_importer.py    استيراد ملفات Lighthouse JSON موجودة (بلا مفتاح)
│   ├── crux_history.py           سلسلة Core Web Vitals الزمنية
│   ├── awt_importer.py           استيراد CSV من AWT (Ahrefs Webmaster)
│   ├── backlinks_api.py          حيّ v1.04: Ahrefs v3 + Majestic OpenApp (Bearer / مفتاح)
│   └── ai_advisor.py             تجريد مزوّد الذكاء (OpenAI/Anthropic/Gemini/محلي
│                                  متوافق OpenAI) — نصوص فقط
├── reporting/
│   ├── report_join.py            build_unified: تقني × GSC × GA4 لكل URL
│   ├── opportunities.py          compute_opportunities (الأولوية القديمة)
│   ├── priority_engine.py        v2: severity × impact × ease × confidence + Action Board
│   ├── url_detail.py             تفاصيل لكل URL للوحة التفاصيل الجانبية
│   └── report_builder.py         يُحمّل audit JSON ويُنتج HTML/PDF
├── exporters/                  csv_exporter, excel_exporter, json_exporter,
│                                xml_exporter, html_exporter, sitemap_generator
├── storage/                    SQLite + APICache (مع _ALLOWED_TABLES قائمة أسماء بيضاء)
└── utils/                      helpers (حارس SSRF، محيِّد الصيغ، normalize_url)،
                                logger، observability، auto_install

webapp/                         v1.12 refactor: app.py 2,098 → 143 سطراً بفصل:
├── app.py                      تطبيق FastAPI: ربط middleware + تضمين الموجّهات فقط
├── security.py                 رمز المصادقة المحلي (Bearer + ?token=)، حارس CSRF
│                                للـOrigin، حصص rate limit، استثناءات /health و/readyz
├── deps.py                     FastAPI dependencies: require_token, require_origin,
│                                rate_limited, valid_job_id
├── constants.py                ثوابت مشتركة: label_for() لتمييز JSON (v1.13.1)،
│                                ملصقات الملفات، قائمة MIME، المسارات
├── routers/                    9 موجّهات APIRouter (بدل app.py الموحَّد):
│   ├── pages.py                  صفحات HTML (`/`, `/jobs/{id}`, `/board`, `/explore`,
│   │                              `/compare`, `/logs`, `/graph`)
│   ├── jobs.py                   /api/jobs CRUD + progress + events (SSE) + phase2
│   ├── generate.py               توليد HTML/PDF/Excel/XML عند الطلب
│   ├── downloads.py              تنزيل الملفات مع مصادقة وحماية path-traversal
│   ├── analytics.py              /api/jobs/<id>/board, /url-detail, /compare
│   ├── logs.py                   /api/logs رفع + تحليل
│   ├── google_oauth.py           /api/google/upload|authorize|disconnect|status
│   ├── connections.py            مسارات اختبار التكاملات (أزرار الاختبار)
│   └── setup.py                  معالج إعداد Google من 3 خطوات
├── job_runner.py               JobRunner: يطلق subprocess، يتتبّع الحالة، يحذف المهام؛
│                                ويطبّع URLs المُدخَلة (v1.13.7)
├── run.py                      نقطة دخول uvicorn
├── static/                     app.css, i18n.js (قاموسا ar + en)
└── templates/                  index.html, job.html (مع withToken() + auto-show ثلاثي +
                                tooltips للعدّادات)، board.html, compare.html, logs.html,
                                explore.html, graph.html
tests/                          v1.13 refactor: 1,414 سطراً → 6 ملفات مصنّفة
├── conftest.py                 fixtures مشتركة (DB مؤقّت، خادم HTTP مزيّف، عيّنة audit)
├── test_analyzers.py             اختبارات وحدات المحلّلات
├── test_crawler.py               الزاحف + القوالب + مصنّف URL
├── test_exporters.py             CSV / Excel / JSON / XML / HTML / sitemap
├── test_integrations.py          parsers على ردود APIs اصطناعية
├── test_priority.py              محرّك الأولوية + Action Board
├── test_utils.py                 حارس SSRF، محيِّد الصيغ، normalize_url
└── test_webapp_endpoints.py      TestClient: مصادقة، CSRF، حصص، /health، /readyz
```

---

## 3) تدفّق البيانات (تدقيق كامل)

1. **يقدّم المستخدم النموذج** → `POST /api/start` → `JobRunner.start(overrides)`.
2. `JobRunner._build_job_config` يكتب `config.yaml` لكل مهمة تحت
   `webapp_jobs/<job_id>/`. الأسرار (مفاتيح PageSpeed/AI) تُجرَّد من الملف وتُمرَّر
   عبر `os.environ` للعملية الفرعية بدلاً منه.
3. `JobRunner.start` يطلق `python -m seo_crawler.main` كعملية ابن مع
   `SCT_PROGRESS_FILE=…` و`SCT_NONINTERACTIVE=1`.
4. **`main.main_async`** ينسّق التشغيل بتفويض إلى `services/`:
   - `services.analysis_service.run_analysis` → المحلّلات (نقيّة) تنتج قواميس `analysis["…"]`.
   - `services.integrations_service.run_integrations` → عملاء اختياريون يجلبون GSC/GA4/PageSpeed/CrUX.
   - `build_unified(pages, analysis, gsc_pages, ga4_landing_pages)` يدمج لكل URL.
   - `compute_opportunities(unified_rows)` (قديم) و
     `compute_priority(unified_rows, platform)` (v2 + Action Board).
   - `services.export_service.run_export` يكتب CSV / Excel / JSON / XML / HTML / PDF / sitemap.
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
- **علم CLI جديد:** أضف إلى `argparse.ArgumentParser` في
  `seo_crawler/seo_crawler/main.py`، ثم وثّقه في **كلا** `docs/CLI.md` و
  `docs/CLI_AR.md` (جدول الأعلام + السيناريوهات + جدول متغيّرات البيئة).
  أضف اختباراً في `tests/` إذا كان العلم يُعدّل طبقة الإعداد.

---

## 6) أين تبحث عن…

| السؤال | الملف(ات) |
|---|---|
| كيف تُزحف صفحة واحدة وتُخزّن؟ | `crawler/async_core.py::_crawl_page` |
| كيف تُجمَع المشاكل وتُوسَم؟ | `analyzers/seo_issues.py` + `analyzers/hints.py` |
| كيف تُحسَب درجة الأولوية؟ | `reporting/priority_engine.py::compute_priority` |
| كيف تُتحكَّم التكاملات بالتفعيل؟ | `services/integrations_service.py::run_integrations` + `config.example.yaml::integrations` |
| كيف تصل الأسرار للعملية الفرعية؟ | `webapp/job_runner.py::_build_job_config` (`_secret_env` → بيئة `start`) |
| كيف تعرف الواجهة بحالة المهمة؟ | `/api/jobs/<id>/events` SSE (مصادقة عبر `?token=`) + `webapp_jobs/<id>/progress.json` |
| كيف تُحفظ/تُلغى الـ tokens؟ | `webapp/routers/google_oauth.py::upload\|authorize\|disconnect` + `_google_dir()` |
| كيف تُصادَق الواجهة؟ | `webapp/security.py::require_token` (Bearer أو `?token=`) + `~/.sct/local_token` |
| كيف يُربط تشغيل Phase-2؟ | `services/deferred_service.py` (find CSV + inject seeds) + `main.py::--phase2` |
| كيف تتبدّل اللغة في i18n؟ | `webapp/static/i18n.js` (يُحمَّل في كل صفحة؛ زرّ `langToggle`) |

---

## 7) الاختبارات

السلسلة كاملة **حتمية ودون اتصال** وتعمل في ثوانٍ:

```bash
python -B -m unittest discover -s tests
```

التكاملات الحيّة (GSC, GA4, PageSpeed, AI) تُختبر عبر **parsers** على ردود اصطناعية —
دون شبكة حقيقية. الزاحف يُختبر مقابل خادم HTTP صغير داخل العملية (راجع
`tests/conftest.py` للـfixtures؛ اختبارات الزاحف في `tests/test_crawler.py`
بعد تقسيم v1.13 من `test_core_behaviors.py` القديم).

راجع `CONTRIBUTING_AR.md §1` لبوّابة الالتزام الكاملة.
