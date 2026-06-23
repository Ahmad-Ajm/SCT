# دليل المساهمة في SCT

شكراً لمساعدتك في تحسين SCT (أداة الزحف البسيطة). نهدف إلى أن تبقى الأداة **موثوقة**،
**شفّافة**، **محترمة للمواقع المزحوفة**، و**ثنائية اللغة** (كل نصّ يراه المستخدم يجب أن
يكون بالعربية والإنجليزية).

> The English version of this guide is in [`CONTRIBUTING.md`](CONTRIBUTING.md).
> هيكل المشروع وخريطة الوحدات والقرارات المعمارية في
> [`docs/ARCHITECTURE_AR.md`](docs/ARCHITECTURE_AR.md).

---

## 1) إعداد البيئة المحلية

يتطلّب **Python 3.10 أو أحدث**.

```bash
python -m pip install -r requirements.txt
playwright install chromium      # فقط لتصيير JS وتقارير PDF
python webapp/run.py             # ثم افتح http://127.0.0.1:8000
```

تشغيل الاختبارات:

```bash
python -B -m compileall -q seo_crawler webapp
python -B -m unittest discover -s tests
```

التحقّق من JS الواجهة:

```bash
node --check webapp/static/i18n.js
```

بوّابة الالتزام الكاملة: `compileall + unittest` + `node --check` على `i18n.js` وأي كتلة
`<script>` مضمّنة عدّلتها (مع تعرية وسوم Jinja أولاً — الطريقة في `docs/ARCHITECTURE_AR.md`).

---

## 2) نمط الكود

**بايثون:** PEP 8 + اتفاقيات المشروع التي ستراها في الوحدات الموجودة:

- استخدم type hints في كل مكان.
- `from __future__ import annotations` في أعلى كل وحدة جديدة.
- Docstrings على كل دالّة/صنف عام — العربية مقبولة للملاحظات الداخلية؛ لكن أسماء الدوال
  والمعاملات بالإنجليزية.
- فضّل **دوالاً نقيّة** للمحلّلات والـ parsers (تُختبر بسهولة دون اتصال).
- استخدم `utils.logger.get_logger(__name__)` للتسجيل — لا تستعمل `print()` في كود المكتبة.

**JavaScript** (مضمّن في القوالب + `webapp/static/i18n.js`):

- ES2015+ (arrow functions, `const`/`let`, template strings).
- لا خطوة بناء — اتركه مضمّناً/خام. لا تُدخل jQuery أو React أو bundlers.
- كل نصّ يراه المستخدم يجب أن يستخدم `data-i18n="key"` (HTML) أو `T('key', 'fallback')`
  (JS). يجب أن يكون المفتاح في قاموسَي AR و EN (راجع §4).

**HTML/CSS:** النموذج في `webapp/templates/index.html`. التبويبات أقسام مسطّحة
(`data-pane="..."`)، لا مكوّنات ثقيلة. الأنماط في `webapp/static/app.css` و`<style>`
مضمّن صغير في `index.html`.

---

## 3) قواعد الأمان (قيود صلبة — لا تخرقها)

- **لا أسرار في المستودع.** ملفات OAuth client secret، مفاتيح API، tokens، ملفات `.env`،
  وأي `*_token.json` كلها ضمن gitignore. الاعتمادات تدخل عبر `.env` أو إعداد المهمّة في
  الواجهة (يُحفظ تحت `webapp_jobs/_google/` ضمن gitignore).
- **كل التكاملات الخارجية اختيارية ومطفأة افتراضياً.** عند إضافة واحدة، القيمة الافتراضية
  في الإعداد `false`/فارغة، والأداة يجب أن تعمل بدونها.
- **لا PII** يُجمع من GA4 ولا يُرسَل لمزوّدي AI — فقط روابط وأنواع مشاكل وأرقام مجمّعة.
- **أي طلب HTTP خارجي يتبع رابطاً من المستخدم** يجب أن يمرّ بـ
  `utils.helpers.is_safe_remote_url` (حارس SSRF) ما لم يُفعّل المستخدم صراحةً «السماح
  بعناوين خاصة».
- **مخرجات CSV/Excel** يجب أن تُحيّد حقن الصيغ — استخدم `utils.helpers.neutralize_formula`.
- **تحليل XML** يجب أن يستخدم `defusedxml`، لا المكتبة القياسية.
- **التنزيلات التدفّقية بحدود حجم** لأي شيء يجلبه المستخدم (sitemap، robots.txt، رفع
  ملفات اللوغ، إلخ).
- **لا تلتزم المجلدات المُولَّدة** — `output/`، `state/`، `logs/`، `webapp_jobs/`،
  `__pycache__/`، `.pytest_cache/` كلها ضمن gitignore.

---

## 4) انضباط ثنائية اللغة (i18n)

كل نصّ يراه المستخدم في `webapp/static/i18n.js` تحت قاموسَي `ar` و `en`. بعد تعديل الواجهة،
شغّل أداة التدقيق المحلية:

```bash
python _review/i18n_audit.py
```

تقارن المفاتيح المستعملة في القوالب/JS مقابل القاموسَين وتطبع أي مفاتيح ناقصة في كل لغة.
يجب أن يبقى القاموسان **متطابقَين تماماً** (كل مفتاح في `ar` موجود في `en`).

للنصوص الديناميكية في JS، استخدم `T('key', 'AR fallback')` لكي تبقى الصفحة عاملة إن نُسيَ
مفتاح (وستلتقطه أداة التدقيق في المرّة القادمة).

---

## 5) إضافة محلّل جديد (Analyzer)

المحلّلات دوالٌ نقيّة فوق بيانات الزحف. النمط:

1. أنشئ `seo_crawler/seo_crawler/analyzers/<name>.py` يصدّر دالّة `analyze_<name>(...)`
   تُرجع `dict` بصيغة `{"<rows>": [...], "summary": {...}}`.
2. في `seo_crawler/seo_crawler/services/analysis_service.py::run_analysis` (منذ v1.12)، استورِدها وادعُها واحفظ النتيجة
   في `results["<name>"]`.
3. في `seo_crawler/seo_crawler/services/export_service.py::run_export` (منذ v1.12)، أضف تصدير CSV من الصفوف.
4. اختياري: أضِف قسماً في تقرير HTML بـ
   `seo_crawler/seo_crawler/exporters/html_exporter.py` (سجّله في `EXPERT_SECTIONS` أو
   `CLIENT_SECTIONS`).
5. أضِف اختبار انحدار في الملفّ المناسب من تقسيم v1.13 (`tests/test_crawler.py`،
   `test_analyzers.py`، `test_integrations.py`، `test_exporters.py`،
   `test_priority.py`، أو `test_utils.py`) بمدخلات اصطناعية — يجب أن يعمل
   دون اتصال خلال أجزاء من الثانية.

راجع `analyzers/gsc_insights.py` أو `analyzers/log_analyzer.py` كأمثلة نظيفة.

---

## 6) إضافة تكامل جديد (مطفأ افتراضياً)

1. أنشئ `seo_crawler/seo_crawler/integrations/<name>_api.py` بصنف client صغير.
2. أضف `<name>: { enabled: false, ... }` إلى `config.example.yaml` + `config.yaml`.
3. اربطه في `services/integrations_service.py::run_integrations` (منذ v1.12، محصور بـ`enabled`).
4. أضِف بطاقة في تبويب «التكاملات والذكاء» في `webapp/templates/index.html` مع checkbox
   التفعيل + حقول الإعدادات + زرّ اختبار.
5. أضِف نقطة JSON `/api/test/<name>` إن أردت زرّ «اختبار الاتصال».
6. الأسرار: لا تُكتب على القرص؛ تُمرَّر عبر `os.environ` من `job_runner._secret_env`
   (راجع كيف يُتعامَل مع `PAGESPEED_API_KEY` و`AI_API_KEY`).

---

## 7) إضافة تبويب/صفحة جديدة في الواجهة

- تبويب داخل النموذج الرئيسي: أضِف `<button data-tab="X" data-i18n="tab_X">` و
  `<div class="tabpane" data-pane="X">` في `webapp/templates/index.html`. JS الموجود
  يلتقطها تلقائياً.
- صفحة منفصلة (مثل لوحة العمل / محلّل اللوغ): أضِف route FastAPI يُرجع
  `templates.TemplateResponse("<name>.html", ...)`، القالب تحت `webapp/templates/`،
  ومفاتيح i18n عربية + إنجليزية.
- رابط ثابت في الشريط العلوي يذهب إلى `<header class="topbar">` في `index.html` **و**
  `job.html`.

---

## 8) Branching والتزامات والـ Pull Requests

- الفرع الافتراضي: `main`.
- فروع الميزات: قصيرة، أحرف صغيرة، مفصولة بشرطات (`add-foo-analyzer`).
- رسائل الالتزام: بصيغة الأمر، تغيير مركّز واحد لكل التزام (`Add foo analyzer`)،
  لا (`updated stuff`). أَشر إلى issue عند الحاجة.
- قبل فتح PR:
  ```bash
  python -B -m compileall -q seo_crawler webapp
  python -B -m unittest discover -s tests
  node --check webapp/static/i18n.js
  python _review/i18n_audit.py
  ```

---

## 9) عملية الإصدار

SCT يستخدم نظام عشريّ ذا رقمين: `1.00 → 1.01 → 1.02 → …`. كل تغيير مشحون يرفع الأرقام
بعد النقطة. الخطوات:

1. حدّث **`seo_crawler/seo_crawler/exporters/json_exporter.py`** — غيّر `_meta.version`
   إلى الرقم الجديد.
2. حدّث **`webapp/templates/index.html`** — وسم النسخة في الشريط العلوي
   `<small class="version-tag">`.
3. أضِف قسماً في رأس **`CHANGELOG.md`**: `## vX.YY — YYYY-MM-DD` مع
   `### Added / ### Fixed / ### Changed`.
4. شغّل التحقّق الكامل (§8).
5. التزِم على `main` برسالة مثل `vX.YY: <ملخّص سطر واحد>`.
6. `git push origin main`.

---

## 10) الإبلاغ عن الأخطاء / اقتراح الميزات

- الأخطاء: افتح issue على GitHub مع خطوات إعادة الإنتاج، القسم المعني من
  `webapp_jobs/<job_id>/run.log`، وبيئتك (نظام التشغيل، Python، الوضع).
- الميزات: افتح نقاشاً أو issue مع البادئة `[idea]`. البنود المُحدَّدة بوضوح تُضاف إلى
  `ROADMAP.md`.

---

بالمساهمة فأنت توافق على أنّ عملك مرخّص بترخيص MIT للمشروع (راجع [`LICENSE`](LICENSE))
وأنّك ستلتزم بـ[ميثاق السلوك](CODE_OF_CONDUCT.md).
