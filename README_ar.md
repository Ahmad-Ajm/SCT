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
- تصدير CSV وJSON وExcel اختيارياً.
- سجلات تفصيلية وملف `metrics.json`.
- GitHub Actions CI.

## البدء السريع

```bash
python -m pip install -r requirements.txt
python main.py --help
python main.py --mode audit --url https://example.com/
```

ولتفعيل JavaScript rendering اختيارياً:

```bash
playwright install chromium
```

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
- ملف `metrics.json` يحتوي timings وcounters وgauges وrecent events.

## خطة الواجهة والتقارير

راجع [docs/GUI_PDF_REPORTING_PLAN.md](docs/GUI_PDF_REPORTING_PLAN.md) لخطة بناء واجهة رسومية، تصدير PDF، جدولة التقارير، تخصيص PDF، وتقييم صعوبة JavaScript rendering.

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
