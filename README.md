# SCT - Simple Crawler Tool

أداة زحف وتدقيق SEO مبنية ببايثون. نقطة التشغيل الرسمية الآن من جذر المشروع:

```bash
python main.py --help
python main.py --mode audit
python main.py --mode competitor --url https://example.com/
python main.py --mode compare
```

## التثبيت

```bash
python -m pip install -r requirements.txt
```

ولتفعيل JavaScript rendering لاحقاً:

```bash
playwright install chromium
```

## الهيكل المعتمد

```text
Simple_Crawler_Tool_SCT/
├── main.py                  # Launcher خفيف يوجه للنسخة المعتمدة
├── config.yaml              # إعدادات دار أطلس / التشغيل من الجذر
├── requirements.txt         # الاعتمادات الرسمية
└── seo_crawler/seo_crawler/ # التطبيق الفعلي v3.0
```

النسخة المعتمدة للتطوير هي `seo_crawler/seo_crawler`. الملفات القديمة أو المكررة خارج هذا المسار لا يجب تعديلها إلا عند أرشفتها أو حذفها ضمن مرحلة تنظيف منفصلة.

## أوضاع التشغيل

| الوضع | الاستخدام |
| --- | --- |
| `audit` | تدقيق SEO كامل للموقع الأساسي |
| `competitor` | تحليل خفيف ومحترم لموقع منافس |
| `compare` | يزحف كل موقع في `sites_to_compare` ويصدر مخرجات كل موقع مع `comparison_summary.json` |

## ملاحظات تشغيل

- الأداة تحترم `robots.txt` وتستخدم تأخيراً بين الطلبات.
- التحقق من شهادات HTTPS مفعّل افتراضياً عبر `crawl.verify_ssl` و`external_check.verify_ssl`.
- عند تعذر تحميل `robots.txt` يتحكم `crawl.robots_failure_policy` بالسلوك، وتستخدم أوضاع المنافسة/المقارنة سياسة أكثر تحفظاً.
- يتضمن التدقيق الآن محللات إضافية لمشاكل URL hygiene وcanonical، وتُصدّر في JSON وملفات CSV منفصلة.
- تصدير CSV يستخدم writer مباشر لتقليل الذاكرة، وحفظ نتائج الصفحة في SQLite يتم كحزمة واحدة قدر الإمكان.
- عند التشغيل من الجذر، تُحفظ المخرجات في `output/` والحالة في `state/`.
- المراقبة التفصيلية مفعّلة من `observability` في `config.yaml`: ستجد `metrics.json` داخل مجلد كل تشغيل، ومع `logging.level: DEBUG` تظهر بداية/نهاية المراحل والدوال المهمة وتوقيتاتها.
- إذا لم تكن `openpyxl` مثبتة، يتم تخطي Excel فقط مع الاستمرار في CSV/JSON/metrics.
- وضع `--analyze-only` يقرأ من SQLite مباشرة ولا يحتاج لاستيراد محرك الزحف الكامل.
- يمكن تعديل الموقع المستهدف من `config.yaml` أو تمرير `--url`.

## النشر المفتوح

- استخدم `config.example.yaml` كقالب عام، واترك `config.yaml` لإعداداتك المحلية.
- راجع `ROADMAP.md` لمعرفة الأولويات القادمة.
- ملفات `LICENSE` و`CONTRIBUTING.md` و`SECURITY.md` و`CHANGELOG.md` جاهزة كبداية للنشر على GitHub.
- يعمل GitHub Actions من `.github/workflows/ci.yml` لتشغيل compile/tests على Python 3.10-3.12.

## الاختبارات

```bash
python -m unittest discover -s tests
```
