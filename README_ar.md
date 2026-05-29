# SCT - أداة زحف وتدقيق SEO

SCT هي أداة مفتوحة المصدر مبنية ببايثون لفحص SEO التقني والداخلي للمواقع. تساعدك على اكتشاف مشاكل الزحف، الفهرسة، العناوين، الوصف، الروابط، الصور، structured data، canonical، hreflang، mixed content، redirects، وتصدير تقارير قابلة للتحليل.

بدأ المشروع كأداة صغيرة لفحص موقع واحد، ثم تطور إلى Crawler متعدد الأوضاع مع زحف async، تخزين SQLite، تصدير CSV/JSON/Excel، سجلات تفصيلية، وملف `metrics.json` لقياس الأداء.

## الميزات

- زاحف Async مع إعدادات concurrency وdelay.
- زاحف Sync احتياطي.
- تخزين SQLite للمواقع الكبيرة.
- أوضاع تشغيل: `audit` و`competitor` و`compare`.
- قراءة `robots.txt` وsitemaps.
- التحكم في SSL verification.
- تحليل مشاكل URL hygiene.
- تحليل canonical.
- كشف التكرارات في العناوين والوصف والمحتوى.
- كشف thin content.
- تحليل الروابط الداخلية المكسورة.
- فحص الروابط الخارجية.
- تحليل الصور.
- فحص Schema.org.
- فحص hreflang.
- مقارنة sitemap مع نتائج الزحف.
- كشف mixed content.
- تصيير JavaScript (Playwright) وفرق الخام مقابل المُصيَّر، والاستخراج المخصّص (CSS/XPath/Regex).
- درجة الروابط الداخلية (PageRank)، وكشف الصفحات شبه‑المكرّرة (SimHash)، وكاشف الصفحات اليتيمة.
- تكاملات Google اختيارية: GSC (+URL Inspection)، GA4، PageSpeed (+جداول Lighthouse العميقة)،
  CrUX History — كلها مطفأة افتراضياً.
- تحليلات GSC: تكلّس الكلمات وفُرَص الروابط الداخلية. ومقارنة زمنية بين زحفتين (قبل/بعد).
- تلميحات قابلة للتنفيذ لكل مشكلة (الأثر/الجهد/لماذا/كيف/درجة الأولوية).
- محرّك أولويات v2 + لوحة عمل: درجة متعددة العوامل لكل صفحة (شدّة × أثر × سهولة × ثقة) مع
  تصنيف نوع الصفحة وسهولة الإصلاح ومالكه، وتجميعها في «افعل الآن/يحتاج مطوّراً/…».
- مولّد `sitemap.xml`، تحكّم تكيّفي بالسرعة، قوالب منصّات التجارة (زد/سلة/Shopify/Woo).
- تثبيت تلقائي للمتطلبات الاختيارية (محصور بقائمة بيضاء، يُعطَّل بـ`SCT_NO_AUTO_INSTALL=1`).
- تصدير CSV وJSON وExcel اختيارياً، وتقارير HTML/PDF.
- واجهة مرئية محلية متكاملة (FastAPI + HTMX + SSE) مع متابعة مباشرة للزحف.
- تقارير HTML/PDF قابلة للتخصيص للعميل (عربي/RTL عبر Playwright).
- استئناف async موثوق وإعادة تشغيل آمنة بلا تكرار صفوف.
- حماية SSRF، سقف لقنابل gzip، وتحييد حقن الصيغ في CSV/Excel.
- سجلات تفصيلية وملف `metrics.json`.
- GitHub Actions CI.

## البدء السريع

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

## الترخيص

MIT License. راجع [LICENSE](LICENSE).
