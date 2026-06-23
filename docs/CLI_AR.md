# SCT — مرجع سطر الأوامر

> English version: [`CLI.md`](CLI.md).
> للواجهة المرئية (المُوصى بها) راجع [`USER_GUIDE_AR.md`](USER_GUIDE_AR.md).

في SCT نقطتا دخول:

1. **`python main.py`** — يشغّل زحفاً/تدقيقاً واحداً (بلا خادم ويب).
2. **`python webapp/run.py`** — يبدأ الواجهة المرئية المحلية (FastAPI + uvicorn).

كلاهما يقرأ نفس `config.yaml` للقيم الافتراضية. أعلام CLI تتجاوز ما في الإعداد.

---

## 1) CLI الزاحف/التدقيق — `python main.py`

```
usage: main.py [-h]
               [--mode {audit,competitor,compare}]
               [--url URL]
               [--config CONFIG]
               [--sync]
               [--analyze-only]
               [--no-resume]
               [--skip-external]
               [--integrations-only]
               [--phase2]
               [--clear-cache]
```

### الأعلام

| العلم | الافتراضي | ماذا يفعل |
|---|---|---|
| `--mode {audit,competitor,compare}` | `audit` | وضع الزحف. `audit` = تدقيق كامل للموقع. `competitor` = زحف محدود لمنافس (يستعمل نفس المحلّلات بلا توقّع ملكية). `compare` = زحف عدّة مواقع من `sites_to_compare` في الإعداد وإنتاج Excel مقارن. |
| `--url URL` | (من `site.start_url`) | تجاوز رابط البداية لهذا التشغيل فقط. الدومين يُشتقّ من الرابط. |
| `--config CONFIG` | `config.yaml` | مسار ملف إعداد مختلف. |
| `--sync` | مطفأ | يستعمل الزاحف المتزامن بدل غير المتزامن. أبطأ، لكنه مفيد للتشخيص حيث يتعطّل `aiohttp`. |
| `--analyze-only` | مطفأ | يتخطّى مرحلة الزحف ويُعيد التحليل على DB SQLite سابق (تحت `state_dir`). مفيد عند تغيير عتبات المحلّلات فقط. |
| `--no-resume` | مطفأ | بدء جديد: يتجاهل أي `visited`/`queue` محفوظ ويبدأ من الصفر. |
| `--skip-external` | مطفأ | لا يفحص حالة الروابط الخارجية (أسرع). |
| `--integrations-only` | مطفأ | تخطّي الزحف كاملاً؛ يجلب فقط التكاملات (GSC/GA4/PageSpeed) ويُصدّر CSV لها. |
| `--phase2` | مطفأ | v1.08: يشغّل **Phase 2** — يستعمل `deferred_urls.csv` من المخرجات السابقة كقائمة بذور ويعطّل المصنّف (يفحص كل الروابط). يُمدّد `audit.json` القائم بدل كتابة جديد. مفيد إذا أجَّلت Phase 1 روابط ترقيم عميق/التفاف تحويلات/تركيب فلاتر، ثم قرّرت أنك تريد زحفها. |
| `--clear-cache` | مطفأ | يمسح كاش الـ API (`state/api_cache.db`) ويخرج. |

### سيناريوهات عملية

```bash
# الافتراضي: تدقيق async كامل من site.start_url
python main.py

# مسح منافس سريع مع تجاوز الرابط
python main.py --mode competitor --url https://example.com/

# استئناف بعد انهيار، لا تُعِد زحف ما زرته
python main.py

# إعادة المحلّلات دون زحف (مثلاً بعد تغيير عتبة)
python main.py --analyze-only

# تشغيل نظيف، تجاهل الحالة المحفوظة
python main.py --no-resume

# مقارنة عدّة مواقع من config.yaml::sites_to_compare
python main.py --mode compare

# جلب التكاملات فقط، بلا زحف
python main.py --integrations-only

# تشغيل Phase 2 على الروابط المؤجَّلة من التشغيل السابق
# (يُمدّد audit.json في نفس مجلّد المخرجات)
python main.py --phase2

# استعمال ملف إعداد مختلف (مثلاً لكل عميل)
python main.py --config configs/clientA.yaml

# مسح كاش API على القرص (PageSpeed/إلخ) والخروج
python main.py --clear-cache
```

### متغيّرات البيئة

| المتغيّر | التأثير |
|---|---|
| `PAGESPEED_API_KEY` | مفتاح PageSpeed Insights، يُقرأ كاحتياط إن كان الإعداد فارغاً. |
| `AI_API_KEY` | مفتاح مستشار الذكاء (المزوّد من الإعداد). |
| `GA4_PROPERTY_ID`, `GA4_CREDENTIALS_FILE` | قيم احتياطية لتكامل GA4. |
| `SCT_PROGRESS_FILE` | يضعه `JobRunner` تلقائياً لتُمرّر العملية الفرعية حالة المراحل/العدّادات لملف JSON تستطلعه الواجهة. |
| `SCT_NONINTERACTIVE` | يضعه `JobRunner` على `1`. عند ضبطه، لن يفتح OAuth متصفّحاً محلياً؛ يُرجع خطأً واضحاً بدل تعليق العملية الفرعية. |
| `SCT_NO_AUTO_INSTALL` | اضبطه على `1` لتعطيل مساعد التثبيت التلقائي (`utils/auto_install.py`). المكتبات الاختيارية حينها تحتاج تثبيتاً يدوياً بـ`pip`. |
| `SCT_AUTO_INSTALL` | v1.12: تفعيل صريح للمساعد التلقائي. الافتراضي **مطفأ** منذ v1.12 (كان فعّالاً). اضبطه على `1` إذا كنت بحاجة للسلوك القديم فقط. |
| `BACKLINKS_API_KEY` | تكامل v1.04 للباك‑لينك. Ahrefs v3 يستخدم `Authorization: Bearer <key>`؛ Majestic OpenApp يستخدم نفس المتغيّر. مطفأ افتراضياً — يُستعمل فقط عند تفعيل `integrations.backlinks_api` في الإعداد. |

---

## 2) مُشغّل الواجهة — `python webapp/run.py`

```
usage: run.py [-h] [--host HOST] [--port PORT] [--reload]
```

| العلم | الافتراضي | ماذا يفعل |
|---|---|---|
| `--host` | `127.0.0.1` | واجهة الشبكة. استعمل `0.0.0.0` للوصول من الشبكة المحلية. |
| `--port` | `8000` | منفذ TCP. |
| `--reload` | مطفأ | إعادة تحميل uvicorn (للتطوير فقط). |

أمثلة:

```bash
# واجهة محلية فقط على المنفذ الافتراضي
python webapp/run.py
# ثم افتح http://127.0.0.1:8000

# متاحة على الشبكة المحلية بمنفذ مخصّص
python webapp/run.py --host 0.0.0.0 --port 9000

# إعادة تحميل سريعة أثناء التطوير
python webapp/run.py --reload
```

الواجهة تعطيك كل ما يعطيه CLI، إضافةً إلى متابعة المهام، إعداد التكاملات، لوحة العمل،
لوحة تفاصيل URL، وتحليل اللوغ. للاستعمال مرّةً واحدة من سطر الأوامر، `main.py` يبقى
الخيار الأخفّ.

---

## 3) Docker — `docker compose up --build`

صورة Playwright الرسمية تتضمّن Chromium فيعمل تصيير JS وتقارير PDF مباشرةً. تُحفظ
المخرجات في `./webapp_jobs`، والأسرار تُقرأ من `.env` وقت التشغيل (لا تُخبز في الصورة).
التفاصيل في `README_ar.md`.

---

## 4) مُثبِّت Windows — `installer/install.ps1`

سكربت PowerShell بلا صلاحيات admin يُنشئ venv محلي، يثبّت المتطلبات + Chromium لـ
Playwright، ويُضيف اختصارات سطح المكتب وقائمة ابدأ تُشغّل الواجهة. التفاصيل في
`installer/README.md`.
