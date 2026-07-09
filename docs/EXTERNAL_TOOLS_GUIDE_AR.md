# دليل الأدوات الخارجية لـ SCT

SCT يركّز على الزحف والتحليل الداخلي (الصفحات، الروابط، التحويلات، الموارد، المشاكل التقنية).
للمجالات المتخصصة (الأداء، إمكانية الوصول، الأمان العميق) نرشدك لأدوات مجانية قوية بدل
إعادة بنائها، ثم نستورد مخرجاتها بجانب تقارير SCT. **لا حاجة لأي مفتاح API داخل الكود.**

## متى تستخدم كل أداة؟

| الحاجة | الأداة المقترحة | كيف يستفيد SCT |
|---|---|---|
| الأداء (Core Web Vitals) | Lighthouse / PageSpeed | استيراد JSON → عرض scores |
| إمكانية الوصول (WCAG) | Lighthouse أو axe-core | استيراد JSON (لاحقاً) + فحوص بسيطة داخلية |
| الأمان العميق (DAST) | OWASP ZAP | إرشاد + استيراد لاحقاً؛ SCT يفحص الترويسات الأساسية |
| أداء البحث (Clicks/Impressions) | Google Search Console / Bing | موصل اختياري بمفاتيحك أنت |

---

## 1) Lighthouse / PageSpeed (الأداء)

SCT لا يبني محرك أداء. شغّل Lighthouse محلياً وضع ملفات JSON ليقرأها SCT.

### تثبيت وتشغيل Lighthouse CLI
```bash
npm install -g lighthouse
lighthouse https://example.com/ --output=json --output-path=./external_data/lighthouse/home.json --quiet --chrome-flags="--headless"
```
كرّر لكل صفحة مهمة (سمِّ الملفات كما تشاء؛ SCT يقرأ كل `*.json`).

### أو PageSpeed Insights
- عبر الموقع: https://pagespeed.web.dev/ ثم احفظ JSON.
- أو عبر API (اختياري) بمفتاحك في `.env`:
  ```env
  PAGESPEED_API_KEY=your-own-key
  ```

### الاستيراد إلى SCT
1. ضع ملفات JSON في `./external_data/lighthouse/`.
2. فعّل في `config.yaml`:
   ```yaml
   integrations:
     lighthouse:
       enabled: true
       folder: "./external_data/lighthouse"
   ```
3. ستجد `lighthouse_import.csv` ضمن المخرجات (performance/accessibility/best-practices/seo، 0-100).

---

## 2) Accessibility (إمكانية الوصول)

SCT يفحص أساسيات فقط (صور بلا alt، إلخ). للفحص الكامل لـ WCAG:
- **Lighthouse**: قسم accessibility (نفس خطوات الأعلى).
- **axe-core**: عبر إضافة المتصفح أو `@axe-core/cli`:
  ```bash
  npm install -g @axe-core/cli
  axe https://example.com/ --save ./external_data/axe/home.json
  ```
الاستيراد المخصص لـ axe سيُضاف لاحقاً؛ حالياً استخدم تقارير Lighthouse JSON.

---

## 3) Security (الأمان)

SCT يفحص الترويسات الأساسية تلقائياً (HTTPS, HSTS, CSP, X-Frame-Options,
X-Content-Type-Options, Referrer-Policy, Permissions-Policy, Mixed Content) — انظر
`security_issues.csv`.

للفحص الأمني العميق (DAST) استخدم **OWASP ZAP** (مجاني):
```bash
# مثال passive scan فقط (لا تشغّل active scan على موقع لا تملكه)
docker run -t ghcr.io/zaproxy/zaproxy zap-baseline.py -t https://example.com/ -J zap.json
```
ضع `zap.json` في `./external_data/zap/` (الاستيراد سيُضاف لاحقاً).
**تحذير:** لا تشغّل active scan على مواقع لا تملك إذناً بفحصها.

---

## 4) Google Search Console (أداء البحث)

موصل اختياري بمفاتيحك أنت — لا توجد أي مفاتيح داخل المستودع.
1. أنشئ مشروعاً في Google Cloud وفعّل **Search Console API**.
2. أنشئ OAuth credentials (Desktop) ونزّل JSON.
3. ضع المسار في `.env` أو الواجهة:
```env
GSC_CREDENTIALS_FILE=credentials/gsc_credentials.json
```
4. فعّل `integrations.gsc` (الواجهة أو config). أول تشغيل يفتح متصفحاً للموافقة.
الفائدة: مقارنة الصفحات المزحوفة بصفحات تحصل على نقرات/ظهور، وكشف صفحات مهمة غائبة عن الزحف.

## 5) Google Analytics 4 (سلوك المستخدم)

موصل اختياري بمفاتيحك — يحتاج: `pip install google-analytics-data`.
1. في Google Cloud فعّل **Google Analytics Data API**.
2. أنشئ **Service Account** ونزّل مفتاح JSON، ثم أضِف بريد الـ service account
   كمستخدم قارئ في خاصية GA4.
3. احصل على **Property ID** (رقم) من إعدادات GA4.
4. ضعها في `.env` أو الواجهة:
```env
GA4_CREDENTIALS_FILE=credentials/ga4_service_account.json
GA4_PROPERTY_ID=123456789
```
5. فعّل `integrations.ga4`. لا نجمع أي بيانات شخصية — مقاييس مجمّعة وعلى مستوى الصفحة فقط.

## 6) CrUX History (اتجاه Core Web Vitals الحقيقي)

اختياري — بلا تثبيت إضافي؛ يستخدم نفس مفتاح PageSpeed. واجهة **Chrome UX Report
(CrUX) History API** تُرجع قيم Core Web Vitals *الميدانيّة* (من مستخدمين حقيقيّين)
لأصل موقعك عبر الزمن — LCP وINP وCLS عند المئين p75 — لترى هل الأداء يتحسّن أم
يتراجع، لا مجرّد لقطة مخبريّة واحدة.

فعّله في نموذج الزحف (التكاملات → PageSpeed → **CrUX History**) أو في الإعداد:
```yaml
pagespeed:
  enabled: true
  api_key: "YOUR_PAGESPEED_KEY"
  crux_history: true
```
يجب تفعيل **Chrome UX Report API** في نفس مشروع Google Cloud الخاص بمفتاح
PageSpeed (APIs & Services → Enable APIs → "Chrome UX Report API"). إن لم يكن
مفعّلاً سترى سطر `403 ... blocked` في السجلّ ويتخطّى SCT الـCrUX بهدوء — بقيّة
التدقيق لا تتأثّر. المخرجات في قسم PageSpeed/CrUX من التقرير، والـJSON الخام تحت
`pagespeed_raw/` عند تفعيل `save_raw_json`.

ملاحظة: CrUX لا يملك بيانات إلّا للأصول ذات حركة Chrome كافية؛ المواقع قليلة
الزيارات تُرجع "لا تتوفّر بيانات" — وهذا طبيعيّ.

## التقرير الموحّد

عند تفعيل GSC و/أو GA4 مع `report.unified: true`، يضيف تقرير HTML/PDF أقسام:
الظهور البحثي (GSC)، سلوك المستخدم (GA4)، و**أولويات الإصلاح** (ربط المشاكل التقنية
بالنقرات/الجلسات لترتيب أهم ما يُصلَح أولاً) — انظر `priority_opportunities.csv`.

## Bing Webmaster

موصل Bing غير منفّذ بعد (مخطّط لاحقاً). استخدم GSC حالياً.

---

## Backlinks API حيّ — Ahrefs / Majestic (v1.04، مدفوع)

إضافةً إلى مستورِد AWT CSV المجّاني أعلاه (يغطّي المواقع التي تملكها/تتحقّق منها
فقط)، يوفّر SCT تكامل **Backlinks API حيّ** لأكبر مزوّدَين تجاريّين. معطّل
افتراضياً. يحتاج مفاتيح مدفوعة.

**متى تستخدم أيّاً:**
- **AWT CSV (مجّاني):** موقع تملكه ومتحقَّق منه في Ahrefs Webmaster. بلا API.
  صدّر من واجهة Ahrefs Webmaster → ضع الـCSV في `external_data/awt/`.
- **Ahrefs API حيّ (v1.04، مدفوع):** أيّ موقع (لك أو لعميل أو منافس). يحتاج
  اشتراك Ahrefs **Standard** أو أعلى (طبقة Webmaster لا تكشف الـAPI العام).
- **Majestic API حيّ (v1.04، مدفوع):** أيّ موقع. يحتاج مفتاح Majestic **OpenApp**.

**التوصيل** — تبويب *التكاملات والذكاء*:
1. فعّل **🔗 Backlinks (API حيّ — Ahrefs/Majestic)**.
2. اختر المزوّد (Ahrefs أو Majestic).
3. الصق مفتاحك. يُمرَّر للعمليّة الفرعيّة عبر `BACKLINKS_API_KEY` **ولا يُكتب على
   القرص أبداً** (نفس نمط PageSpeed).

أو عبر `config.yaml`:
```yaml
integrations:
  backlinks:
    enabled: true
    provider: ahrefs    # أو: majestic
    timeout: 30
```
**ما يجلبه** (كلا المزوّدَين، بنية موحّدة تحت `integrations.backlinks` في
`audit.json`): ملخّص domain-level (DR/TrustFlow، إجمالي الروابط، النطاقات
المُحيلة)، أعلى 50 نطاقاً مُحيلاً، وأعلى 30 anchor (Ahrefs فقط).

---

## مستشار الذكاء الاصطناعي (سرد اختياري — أيّ مزوّد متوافق مع OpenAI)

ترتيب الأولويّات في SCT **حتميّ** (صيغة محرّك الأولويّة رياضيّة بحتة). مستشار الذكاء
طبقة *منفصلة اختياريّة* تُحوّل التدقيق إلى سرد بلغة بسيطة: ملخّص تنفيذيّ وقائمة
توصيات مرتّبة. لا يغيّر الترتيب أبداً — يصفه فقط.

**المزوّدون المدعومون** (أيّ واجهة تتكلّم OpenAI chat-completions): OpenAI وGoogle
Gemini وDeepSeek وOpenRouter وHugging Face و**النماذج المحليّة** عبر Ollama /
LM Studio على `127.0.0.1`. اختر «نموذج محلي» في الواجهة لإبقاء كل شيء على جهازك.

**التوصيل** — تبويب *التكاملات والذكاء* → فعّل **🤖 مستشار الذكاء**، اختر المزوّد
والنموذج و(للمحلي/المخصّص) base URL، ثم الصق المفتاح. أو عبر الإعداد:
```yaml
integrations:
  ai:
    enabled: true
    provider: openai        # openai | gemini | deepseek | openrouter | huggingface | local
    model: "gpt-4o-mini"    # معرّف النموذج حسب المزوّد
    base_url: ""            # مطلوب للنقاط المحليّة/المخصّصة المتوافقة مع OpenAI
```
يُمرَّر المفتاح عبر `AI_API_KEY` **ولا يُكتب على القرص أبداً**.

**الخصوصيّة.** يُرسَل فقط: الروابط، أنواع المشاكل، وأرقام مجمّعة — لا محتوى صفحات
ولا بيانات شخصيّة. تُجرَّد query strings من الروابط قبل الإرسال (فلا يخرج
`?session=` أو `?email=` أو `?utm_*`). لأقصى خصوصيّة استخدم نموذجاً محلياً — لا
شيء يغادر `127.0.0.1`. إن أعاد المزوّد ردّاً مشوّهاً أو فارغاً، يسجّل SCT تحذيراً
ويكمل بلا نصّ ذكاء؛ التدقيق التقني لا يتأثّر.

المخرجات: `ai_recommendations.csv` + قسم ذكاء في تقرير HTML/PDF.

---

## أين تضع الملفات؟

```
external_data/
├── lighthouse/   ← ملفات Lighthouse/PageSpeed JSON
├── axe/          ← تقارير axe-core (لاحقاً)
├── zap/          ← تقارير OWASP ZAP (لاحقاً)
└── awt/          ← تصدير Ahrefs Webmaster Tools (CSV)
```
كل هذه المجلدات في `.gitignore` ولا تُرفع إلى Git.

## مبادئ
- لا مفاتيح/اعتمادات داخل الكود.
- كل تكامل اختياري ومعطّل افتراضياً.
- SCT يعمل بالكامل بدون أي أداة خارجية.
