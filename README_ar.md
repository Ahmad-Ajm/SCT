# SCT - أداة زحف وتدقيق SEO

SCT هي أداة مفتوحة المصدر مبنية ببايثون لفحص SEO التقني والداخلي للمواقع. تساعدك على اكتشاف مشاكل الزحف، الفهرسة، العناوين، الوصف، الروابط، الصور، structured data، canonical، hreflang، mixed content، redirects، وتصدير تقارير قابلة للتحليل.

بدأ المشروع كأداة صغيرة لفحص موقع واحد، ثم تطور إلى Crawler متعدد الأوضاع مع زحف async، تخزين SQLite، تصدير CSV/JSON/Excel، سجلات تفصيلية، وملف `metrics.json` لقياس الأداء، وواجهة محلية متكاملة بـSSE، وتقارير HTML/PDF عربيّة RTL.

النسخة الإنجليزية متاحة في [README.md](README.md).

## الميزات

- زاحف Async مع إعدادات concurrency وdelay.
- زاحف Sync احتياطي.
- تخزين SQLite للمواقع الكبيرة.
- أوضاع تشغيل: `audit` و`competitor` و`compare`.
- قراءة `robots.txt` وsitemaps.
- التحكم في SSL verification.
- تحليل مشاكل URL hygiene + canonical.
- كشف التكرارات (العناوين/الوصف/المحتوى) + thin content.
- تحليل الروابط الداخلية المكسورة + فحص الروابط الخارجية + تحليل الصور.
- فحص Schema.org + hreflang + مقارنة sitemap مع نتائج الزحف.
- كشف mixed content + محلّل ترويسات الأمان (HSTS/CSP/X-Frame-Options/إلخ).
- جرد الموارد (CSS/JS/صور/خطوط/iframes) مع علامات mixed-content.
- استخراج مخصّص (CSS/Attribute/Text/Regex rules).
- تصيير JavaScript اختياري عبر Playwright + فرق raw-vs-rendered.
- استيراد Lighthouse/PageSpeed JSON (بلا مفاتيح).
- تكاملات Google اختيارية: GSC (+URL Inspection)، GA4، PageSpeed (+جداول Lighthouse العميقة)،
  CrUX History — كلها مطفأة افتراضياً.
- تحليلات GSC: تكلّس الكلمات وفُرَص الروابط الداخلية. ومقارنة زمنية بين زحفتين (قبل/بعد).
- درجة الروابط الداخلية (PageRank)، وكشف الصفحات شبه‑المكرّرة (SimHash + LSH)، وكاشف الصفحات اليتيمة.
- محرّك أولويات v2 + لوحة عمل: درجة متعددة العوامل لكل صفحة (شدّة × أثر × سهولة × ثقة) مع
  تصنيف نوع الصفحة وسهولة الإصلاح ومالكه، وتجميعها في «افعل الآن/يحتاج مطوّراً/…».
- مولّد `sitemap.xml`، تحكّم تكيّفي بالسرعة، قوالب منصّات جاهزة
  (زد/سلة/Shopify/WooCommerce للمتاجر، WordPress للمدوّنات/المواقع التحريريّة —
  يستبعد `?replytocom=`، `/feed/`، `/tag/`، `/author/`، `/wp-admin`،
  `/wp-json/`، `/xmlrpc.php` + 7 query params).
- ضبط المتطلبات الاختيارية (التثبيت التلقائي صار **opt-in** عبر `SCT_AUTO_INSTALL=1` بعد v1.12؛
  الافتراضي يُسجّل خطأ واضحاً باسم الحزمة وأمر `pip install …` الدقيق).
- متصفّح النتائج (تصفية/فرز/بحث) وإعدادات قابلة للتعديل بالكامل من الواجهة.
- تصدير CSV وJSON وExcel وHTML/PDF.
- واجهة مرئية محلية متكاملة (FastAPI + HTMX + SSE) مع متابعة مباشرة للزحف.
- تقارير HTML/PDF قابلة للتخصيص للعميل (عربي/RTL عبر Playwright).
- استئناف async موثوق وإعادة تشغيل آمنة بلا تكرار صفوف.
- حماية SSRF، سقف لقنابل gzip، وتحييد حقن الصيغ في CSV/Excel.
- سجلات تفصيلية وملف `metrics.json` للمراقبة.
- GitHub Actions CI.

## البدء السريع

**أسرع طريقة — نقرة واحدة (v1.10):** انقر مزدوجاً على `START.bat` (Windows) /
نقرة يمين → «Run with PowerShell» على `START.ps1` / `./start.sh` (macOS/Linux).
المُشغّل يكتشف Python، يثبّت requirements عند أوّل تشغيل، يفتح المتصفّح على
`http://127.0.0.1:8000`، ويطبع الـlocal auth token لـ`curl`/scripts. `STOP.bat`
يُنهي الخادم.

**التشغيل و مصادقة الـAPI.** الواجهة المرئيّة تعمل على `127.0.0.1` فقط
ومحميّة بـtoken خاصّ بكلّ install في `~/.sct/local_token` بصلاحيّات `0600`.
المتصفّح يحقنه تلقائياً؛ scripts يُمرّرونه عبر
`Authorization: Bearer <token>` **أو** `?token=<token>` كـquery param. المُشغّل
يطبع القيمة عند البدء، وأيّ `/api/*` بلا token يُرجع 401 مع تلميح يذكر مسار
ملف الـtoken. نقطتا فحص للصحّة معفاتان من auth و rate limits:
`GET /health` (liveness) و `GET /readyz` (readiness — يفحص فعلاً الكتابة في
`webapp_jobs/`). الـrate limiter يضع سقف 10 طلبات/دقيقة/IP على `/api/start`
و 120/دقيقة على باقي `/api/*` — رحب لاستخدام تفاعلي؛ موثَّق هنا كي لا
تخنق automation deployment نفسها. دليل الحوادث الكامل للمشغّلين (8 سيناريوهات
مع أوامر shell + PowerShell): [`docs/RUNBOOK_AR.md`](docs/RUNBOOK_AR.md) ·
[English](docs/RUNBOOK.md).

**يدويّاً (متقدّم):**

```bash
python -m pip install -r requirements.txt
python main.py --help
python main.py --mode audit --url https://example.com/
```

ولتفعيل JavaScript rendering وتقارير PDF:

```bash
playwright install chromium
```

### الواجهة المرئية

```bash
python -m pip install fastapi "uvicorn[standard]" jinja2 python-multipart
python webapp/run.py            # ثم افتح http://127.0.0.1:8000
```

### Docker (أمر واحد، يتضمّن Chromium)

```bash
docker compose up --build       # ثم افتح http://127.0.0.1:8000
```

مبنية على صورة Playwright الرسمية، فيعمل تصيير JavaScript وتقارير PDF مباشرةً. تُحفظ المخرجات
في `./webapp_jobs`. الأسرار تُقرأ وقت التشغيل من `.env` (لا تُخبز في الصورة)، ويمكن وصل
اعتماد Google تحت `./credentials`.

### مُثبِّت Windows (بلا Docker، بلا صلاحيات admin)

```powershell
powershell -ExecutionPolicy Bypass -File installer\install.ps1
```

يُنشئ venv معزولاً، يُثبّت كل المتطلبات + Chromium لـ Playwright، ويُضيف اختصارات
سطح المكتب وقائمة ابدأ تُشغّل الواجهة المرئية. التفاصيل في `installer/README.md`.

الواجهة تتيح تخصيص الإعدادات، إدخال الرابط، اختيار الوضع، تشغيل/إيقاف الزحف ومتابعته
مباشرة (SSE)، وتنزيل تقارير HTML/PDF/Excel/JSON. مخرجات كل مهمة تُحفظ تحت
`webapp_jobs/<job_id>/`.

## الاستخدام

```bash
python main.py --mode audit
python main.py --mode audit --url https://example.com/
python main.py --mode competitor --url https://competitor.example/
python main.py --mode compare
python main.py --analyze-only --skip-external
python main.py --clear-cache
```

## هيكل المشروع

```text
Simple_Crawler_Tool_SCT/
├── main.py                  # مشغل من جذر المشروع
├── config.yaml              # إعدادات التشغيل المحلية
├── config.example.yaml      # قالب إعدادات عام وآمن للنشر
├── requirements.txt         # الاعتمادات
├── ROADMAP.md               # خارطة الطريق
├── docs/                    # خطط وتصميمات تقنية
└── seo_crawler/seo_crawler/ # التطبيق الأساسي
```

المسار المعتمد للتطوير هو `seo_crawler/seo_crawler`.

## أوضاع التشغيل

| الوضع | الاستخدام |
| --- | --- |
| `audit` | تدقيق SEO تقني كامل لموقع تملكه أو تديره. |
| `competitor` | زحف خفيف ومحترم لتحليل المنافسين. |
| `compare` | مقارنة عدة مواقع من `sites_to_compare` وتصدير ملخصات المقارنة. |

## الإعدادات

استخدم `config.example.yaml` كقالب عام، ثم انسخه إلى `config.yaml` وعدله حسب موقعك.

أهم الأقسام:

- `site`: رابط البداية والدومين الأساسي.
- `crawl`: حدود الزحف، التأخير، المحاولات، robots، SSL، concurrency.
- `extraction`: العناصر التي يتم استخراجها.
- `analysis`: حدود العناوين والوصف والمحتوى والـ URL والعمق.
- `output`: صيغ التصدير ومجلد المخرجات.
- `state`: إعدادات SQLite والـ cache.
- `external_check`: فحص الروابط الخارجية.
- `observability`: اللوغ وملف metrics.

## المخرجات

افتراضياً تحفظ الأداة المخرجات داخل `output/` في مجلد باسم يحتوي التاريخ والوقت.

المخرجات تشمل:

- `complete_audit.json`
- ملفات CSV للصفحات، الروابط، الصور، العناوين، schema، redirects، SEO issues، URL issues، canonical issues.
- ملف Excel اختياري `master_audit.xlsx` إذا كانت `openpyxl` مثبتة.
- ملفّا `report.html` و`report.pdf` عند إضافة `html`/`pdf` إلى `output.formats` (الـ PDF يحتاج Playwright).
- ملف `metrics.json` يحتوي timings وcounters وgauges وrecent events.

## الواجهة والتقارير

الواجهة المرئية، وتقارير HTML/PDF القابلة للتخصيص، والتقرير الموحّد (تقني + GSC + GA4 +
أولويات متقاطعة) كلها مُنفَّذة فعلياً. لإعداد التكاملات الاختيارية (Lighthouse / GSC / GA4 / ZAP)
راجع [docs/EXTERNAL_TOOLS_GUIDE_AR.md](docs/EXTERNAL_TOOLS_GUIDE_AR.md).

## الاختبارات

```bash
python -B -m compileall -q seo_crawler/seo_crawler tests
python -B -m unittest discover -s tests
```

## ملاحظات مهمة

- الأداة تحترم `robots.txt` عند تفعيل ذلك في الإعدادات.
- استخدم concurrency منخفضاً عند زحف مواقع لا تملكها.
- JavaScript rendering اختياري ويجب تفعيله بشكل انتقائي لأنه مكلف.
- إذا لم تكن `openpyxl` مثبتة يتم تخطي Excel مع استمرار CSV/JSON/metrics.

## الوثائق

| لمن… | اقرأ |
|---|---|
| المستخدم النهائي (جولة الواجهة، التكاملات، استكشاف الأخطاء) | [`docs/USER_GUIDE_AR.md`](docs/USER_GUIDE_AR.md) · [English](docs/USER_GUIDE.md) |
| أعلام سطر الأوامر + سيناريوهات | [`docs/CLI_AR.md`](docs/CLI_AR.md) · [English](docs/CLI.md) |
| البنية، خريطة الوحدات، القرارات المعمارية | [`docs/ARCHITECTURE_AR.md`](docs/ARCHITECTURE_AR.md) · [English](docs/ARCHITECTURE.md) |
| المساهمة / توسعة الأداة | [`CONTRIBUTING_AR.md`](CONTRIBUTING_AR.md) · [English](CONTRIBUTING.md) |
| ميثاق السلوك | [`CODE_OF_CONDUCT_AR.md`](CODE_OF_CONDUCT_AR.md) · [English](CODE_OF_CONDUCT.md) |
| سياسة الأمان | [`SECURITY.md`](SECURITY.md) |
| دليل الحوادث للمشغّلين (RUNBOOK) | [`docs/RUNBOOK_AR.md`](docs/RUNBOOK_AR.md) · [English](docs/RUNBOOK.md) |
| سجلّ الإصدارات | [`CHANGELOG.md`](CHANGELOG.md) |
| ما هو مخطّط | [`ROADMAP.md`](ROADMAP.md) |
| تكاملات الأدوات الخارجية (Lighthouse, ZAP) | [`docs/EXTERNAL_TOOLS_GUIDE_AR.md`](docs/EXTERNAL_TOOLS_GUIDE_AR.md) · [English](docs/EXTERNAL_TOOLS_GUIDE.md) |
| مُثبِّت Windows | [`installer/README.md`](installer/README.md) |

## الترخيص

ترخيص MIT — Copyright (c) 2026 Ahmad-Ajm. يحقّ لك النسخ والتعديل والتوزيع والاستخدام
التجاري لهذه الأداة. راجع [LICENSE](LICENSE). المساهمات تُقبَل بنفس الترخيص (راجع
[`CONTRIBUTING_AR.md`](CONTRIBUTING_AR.md)).
