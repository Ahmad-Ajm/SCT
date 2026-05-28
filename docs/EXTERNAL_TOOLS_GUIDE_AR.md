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

## التقرير الموحّد

عند تفعيل GSC و/أو GA4 مع `report.unified: true`، يضيف تقرير HTML/PDF أقسام:
الظهور البحثي (GSC)، سلوك المستخدم (GA4)، و**أولويات الإصلاح** (ربط المشاكل التقنية
بالنقرات/الجلسات لترتيب أهم ما يُصلَح أولاً) — انظر `priority_opportunities.csv`.

## Bing Webmaster

موصل Bing غير منفّذ بعد (مخطّط لاحقاً). استخدم GSC حالياً.

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
