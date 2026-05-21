# SCT — ملاحظات الفحص الشامل + طريقة الإصلاح

> فحص للقراءة فقط (لم يُصلَح أي شيء). المصدر: 3 وكلاء متخصصين + تحقق شخصي.
> العلامة ✅ تعني أنه جرى التحقق منها يدوياً في الكود.
> التاريخ: 2026-05-21 — يخص النسخة المعتمدة `seo_crawler/seo_crawler/`.

## كيف تقرأ هذا الملف
كل بند يحتوي: الموقع، الخطورة، الأثر، ثم **طريقة الإصلاح** المقترحة (خطوات عملية).

---

## 🔴 حرجة (Critical)

### C1 — تعليق دائم للزاحف async عند المواقع الأكبر من `max_pages` ✅
- **الموقع:** `crawler/async_core.py:315` (شرط `break`) + `crawler/async_core.py:279` (`await self.queue.join()`).
- **الأثر:** عند بلوغ `pages_crawled >= max_pages` (الافتراضي 5000) تخرج كل الـ workers بـ `break` تاركةً عناصر في الطابور لم تُسحَب. `queue.join()` ينتظر `task_done()` لكل عنصر أُضيف بـ `put()`، فيتعلّق للأبد ولا تُنتج مخرجات. يظهر فقط على المواقع التي تتجاوز روابطها القابلة للزحف `max_pages`.
- **طريقة الإصلاح:**
  1. لا تخرج بـ `break` يترك عناصر معلّقة. بدّل آلية الإنهاء لتفريغ الطابور بأمان:
     - عند بلوغ الحد، اضبط `self._stop_requested = True` بدل `break` الفوري، وفي حلقة الـ worker بعد `get()` نفِّذ `task_done()` فوراً ثم `continue` لتصريف العناصر المتبقية دون معالجتها.
  2. أو الأنسَب: لا تعتمد على `queue.join()` للإنهاء. استبدله بانتظار اكتمال الـ workers مباشرة:
     ```python
     # بدل await self.queue.join()
     await asyncio.gather(*workers)  # كل worker ينهي نفسه عبر منطق _active_workers
     ```
     مع جعل كل worker يصرّف الطابور (`get()` + `task_done()`) عند `_stop_requested` حتى يفرغ.
  3. اختبار قبول: موقع وهمي بـ 50 صفحة و`max_pages=10` يجب أن ينتهي خلال ثوانٍ لا أن يتعلّق.

### C2 — استئناف الزاحف async معطّل تماماً ✅
- **الموقع:** كامل `crawler/async_core.py` (لا `StateManager`، لا كتابة لجداول `crawl_queue`/`visited_urls`)؛ المنطق في `main.py:869-893`.
- **الأثر:** المسار async (الافتراضي) لا يحفظ/يستعيد التقدّم. المقاطعة وإعادة التشغيل (بدون `--no-resume`) تبدأ من الصفر. الاستئناف يعمل في sync فقط.
- **طريقة الإصلاح:**
  1. عند فتح DB، حمّل الحالة قبل الزحف:
     - `self.visited` ← من `db.is_visited`/جدول `visited_urls` (أضف `db.get_visited_set()`).
     - عناصر الطابور ← من `db.crawl_queue` عبر `get_next_from_queue()` بدل البدء من sitemap فقط.
  2. أثناء الزحف: بعد المطالبة بـ URL تحت `_visited_lock` نفِّذ `db.mark_visited(url)`؛ وعند `_discover_new_links` نفِّذ `db.add_to_queue(url, depth)` بالتوازي مع `queue.put`.
  3. عند الإضافة الأولية في `_prepare`، اكتب الطابور إلى `crawl_queue` كي يُستعاد.
  4. صحّح رسالة `main.py:1002` "State saved" لتعكس الواقع (انظر H3).
  5. ملاحظة: احفظ `depth` في `crawl_queue` (موجود) واستعِده بدل `depth=0` (مشكلة موجودة حتى في sync).

### C3 — تكرار صفوف الجداول الفرعية عند أي إعادة تشغيل ✅
- **الموقع:** `storage/database.py` — `_insert_links/_insert_images/_insert_headings/_insert_schema` و`save_redirects`؛ كلها `INSERT` عادي على جداول `AUTOINCREMENT`. `pages` فقط `INSERT OR REPLACE`.
- **الأثر:** إعادة تشغيل `python main.py` (الـ DB يبقى افتراضياً) تُعيد الزحف وتضاعف كل روابط/صور/عناوين/سكيمات/redirects → تحاليل مضخّمة (orphan/broken/inlink counts).
- **طريقة الإصلاح:**
  1. قبل إدراج صفوف صفحة، احذف صفوفها القديمة (delete-then-insert) داخل نفس الـ transaction في `save_page_bundle`:
     ```python
     conn.execute("DELETE FROM links   WHERE from_url = ?", (url,))
     conn.execute("DELETE FROM images  WHERE page_url = ?", (url,))
     conn.execute("DELETE FROM headings WHERE page_url = ?", (url,))
     conn.execute("DELETE FROM schema_entries WHERE page_url = ?", (url,))
     conn.execute("DELETE FROM redirects WHERE original_url = ?", (url,))
     ```
     (أضف فهارس على `images.page_url` و`headings.page_url` و`schema_entries.page_url` — بعضها موجود.)
  2. بديل أبسط لكنه أقل دقة: امنع إعادة الزحف أصلاً عبر إصلاح الاستئناف (C2) فلا تُعاد معالجة صفحة سبق حفظها.
  3. اختبار قبول: تشغيلان متتاليان بلا `--no-resume` يعطيان نفس عدد صفوف `links`.

---

## 🟠 عالية (High)

### H1 — تحقق robots لا يُطبَّق على وجهات الـ redirect
- **الموقع:** `crawler/async_core.py:472-512` و`crawler/core.py` (تتبع redirect في `HTTPClient`).
- **الإصلاح:** داخل حلقة تتبّع الـ redirect، قبل جلب `next_url`، نفِّذ `if self.robots and not self.robots.can_fetch(next_url): break` وسجّل تخطّياً. طبّقه في sync و async للتطابق.

### H2 — I/O متزامن يجمّد حلقة الأحداث أثناء التحضير
- **الموقع:** `crawler/async_core.py:212-252` (`_prepare` يستدعي `robots.load()` و`sitemap_parser.parse()` المتزامنين).
- **الإصلاح:** نفّذ التحميلات المتزامنة في executor:
  ```python
  await asyncio.get_running_loop().run_in_executor(None, self.robots.load)
  entries = await loop.run_in_executor(None, self.sitemap_parser.parse, sitemap_url)
  ```
  أو حوّل قراءة robots/sitemap إلى aiohttp. الحد الأدنى: `run_in_executor` يمنع تجميد اللوب.

### H3 — Ctrl+C لا يوقف زحف async بأمان + رسالة مضلِّلة
- **الموقع:** `crawler/async_core.py:278-282`؛ الرسالة في `main.py:1000-1003`.
- **الإصلاح:**
  1. ثبّت معالج إشارة على مستوى اللوب: `loop.add_signal_handler(signal.SIGINT, self._request_stop)` (على ويندوز استخدم `signal.signal` كحل بديل) يضبط `_stop_requested=True`.
  2. اجعل الـ workers تفحص `_stop_requested` وتخرج بأمان مع تصريف الطابور.
  3. لا تطبع "State saved" إلا إذا حُفظت الحالة فعلاً (مرتبط بـ C2).

### H4 — SSRF: لا حماية من الشبكة الداخلية ✅ (منطقياً)
- **الموقع:** تتبّع redirect (`http_client.py`, `async_core.py`)، `<loc>` في `sitemap_parser.py:106`، sitemaps المعلنة في `robots_parser.py`.
- **الإصلاح:** أضف دالة `is_safe_public_url(url)` تُستدعى قبل أي جلب لوجهة غير موثوقة:
  - ارفض المخططات غير `http/https`.
  - استخرِج المضيف، حُلّ الـ IP، وارفض النطاقات: `127.0.0.0/8`, `10/8`, `172.16/12`, `192.168/16`, `169.254.0.0/16` (خصوصاً `169.254.169.254`), `::1`, `fc00::/7`.
  - اختيارياً: قيّد وجهات الـ redirect على النطاق الأساسي/الإضافي.
  - فعّلها فقط (أو بصرامة أعلى) في أوضاع competitor/compare.

### H5 — قنبلة فك ضغط gzip للـ sitemap
- **الموقع:** `crawler/sitemap_parser.py:113-119` (`gzip.decompress` بلا سقف).
- **الإصلاح:** فك الضغط تدريجياً بسقف بايتات:
  ```python
  import gzip, io
  MAX = 50 * 1024 * 1024
  out = io.BytesIO()
  with gzip.GzipFile(fileobj=io.BytesIO(content)) as gz:
      while chunk := gz.read(1 << 16):
          out.write(chunk)
          if out.tell() > MAX:
              log.error("Sitemap decompressed too large"); return
  content = out.getvalue()
  ```

### H6 — Microdata schemas لا تُفحَص إطلاقاً ✅
- **الموقع:** `extractors/schema_extractor.py:95-103` (لا `raw_data`)؛ `analyzers/schema_validator.py:216,227`؛ و`storage/database.py` `_insert_schema:864`.
- **الإصلاح:**
  1. في المُستخرِج، أضف `raw_data` لإدخالات microdata:
     ```python
     entry = {"format": "microdata", "type": schema_type,
              "properties": properties, "raw_data": properties}
     ```
  2. أو في المُحلِّل، اجعل التطبيع يرجع إلى `properties` عند غياب `raw_data`:
     ```python
     raw_data = entry.get("raw_data") or entry.get("properties", {})
     ```
  3. تأكد أن `_insert_schema` يحفظ `raw_data` (JSON) فيظهر في `--analyze-only`.

### H7 — `sitemap_diff` يستقبل قائمة sitemap ناقصة أو فارغة ✅
- **الموقع:** `crawler/sitemap_parser.py:93` (`_all_entries.clear()` في كل `parse()`)؛ القراءة في `main.py:340-345`؛ و`DatabaseBackedCrawler.sitemap_parser=None` في `main.py:126`.
- **الإصلاح:**
  1. اجمع روابط sitemap عبر كل النداءات: لا تُفرّغ `_all_entries` داخل `parse()`، أو احتفظ بقائمة تراكمية على مستوى الزاحف:
     ```python
     self.all_sitemap_urls = []  # في الزاحف
     entries = self.sitemap_parser.parse(u)
     self.all_sitemap_urls.extend(e.url for e in entries)
     ```
  2. احفظ روابط sitemap في DB (جدول `crawl_metadata` أو جدول جديد) كي يعمل `--analyze-only`.
  3. في `main.py` اقرأ من المصدر التراكمي بدل `_all_entries`.

---

## 🟡 متوسطة (Medium)

### M1 — حقن صيغ في CSV/Excel (Formula Injection)
- **الموقع:** `exporters/csv_exporter.py:228-231`، `exporters/excel_exporter.py:308-314`.
- **الإصلاح:** قبل كتابة أي قيمة نصية، اهرب الأحرف البادئة الخطرة:
  ```python
  def _neutralize(v):
      s = str(v)
      return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s
  ```
  طبّقها في كاتب CSV وفي خلايا Excel.

### M2 — `normalize_url` لا يوحّد trailing slash ولا `..` ✅
- **الموقع:** `utils/helpers.py:62-87`.
- **الإصلاح:**
  1. حلّ `.`/`..` للروابط المطلقة عبر `posixpath.normpath` على الـ path (مع الحفاظ على trailing slash المقصود).
  2. وحّد trailing slash بسياسة واحدة (مثلاً إزالة الـ slash النهائي عدا الجذر `/`).
  3. صحّح الـ docstring ليطابق السلوك. انتبه: `keep_blank_values=False` يُسقط `?a=` — قرّر إن كان مقصوداً ووثّقه.

### M3 — `is_internal_url` يزيل `www.` من أي موضع ✅
- **الموقع:** `utils/helpers.py:121-122,131`.
- **الإصلاح:** أزل البادئة فقط:
  ```python
  def _strip_www(h): return h[4:] if h.startswith("www.") else h
  ```
  واستخدمها بدل `.replace("www.", "")`.

### M4 — تعارض دلالات redirects بين sync و async
- **الموقع:** `async_core.py:491-509` مقابل `core.py:539-549`.
- **الإصلاح:** وحّد التمثيل: لكل صف redirect اجعل `to_url` = الخطوة التالية المباشرة و`chain_length` = ترتيب القفزة، أو العكس — لكن في الزاحفَين معاً. عدّل `analyze_redirects` ليتوافق.

### M5 — `internal_redirects` ميزة ميتة
- **الموقع:** `analyzers/redirect_analyzer.py:46,117`.
- **الإصلاح:** املأها فعلياً: redirect حيث `from_url` و`to_url` داخليان (عبر `is_internal_url` بالنطاق الأساسي)، أو احذف الحقل إن لم يُرَد.

### M6 — ترتيب سلسلة redirect بطول الـ URL
- **الموقع:** `analyzers/redirect_analyzer.py:47`.
- **الإصلاح:** رتّب بالـ `chain_length` (أو ابنِ السلسلة بربط `from_url`→`to_url`) بدل طول النص، ثم احسب `final_url` والحلقات.

### M7 — commits لكل قفزة redirect → صفوف يتيمة
- **الموقع:** `async_core.py:500-503` (`save_redirects` داخل حلقة الجلب).
- **الإصلاح:** اجمع redirects الصفحة في قائمة محلية ومرّرها ضمن `save_page_bundle` (transaction واحدة)؛ لا تكتب redirects إلا بعد نجاح الصفحة (كما في sync).

### M8 — Excel يُفقَد بالكامل بصمت
- **الموقع:** `exporters/excel_exporter.py:185-190,308-314,153`.
- **الإصلاح:**
  1. اقتطع **كل** قيم النص لا الـ list/dict فقط: `s[:32700]`.
  2. عند مقارنات status: `code = int(self._get_attr(p, "status_code", 0) or 0)`.
  3. سجّل سبب الفشل عند `save` بدل ابتلاعه الصامت، حتى لا يضيع التقرير دون أثر.

### M9 — مولّدات `get_*` تُبقي cursor داخل سياق transaction
- **الموقع:** `storage/database.py:447-450` وأخواتها.
- **الإصلاح:** لا تُغلّف SELECT بـ `with self._get_connection() as conn:` (يفتح transaction). استخدم `fetchall()` للقوائم الصغيرة أو cursor مستقل صريح، وأبقِ المولّدات للاستهلاك الكامل فقط.

---

## 🟢 منخفضة/تجميلية (Low)
- **L1** `matches_any_pattern` substring لا glob (`utils/helpers.py:304`): استخدم `fnmatch`/regex إن أردت أنماطاً دقيقة، أو وثّق سلوك substring.
- **L2** sync يقرأ `response.content` كاملاً قبل القص (`http_client.py:198`): استخدم `stream=True` + قراءة chunked بسقف، كما في async.
- **L3** كشف gzip للـ sitemap لا يشمل `application/gzip` (`sitemap_parser.py:114`): أضِف `"gzip" in content_type` ومحاولة فك ضغط احتياطية مع `try/except`.
- **L4** `gsc_token.json` بصلاحيات افتراضية (`integrations/gsc_api.py:101`): اكتب الملف ثم `os.chmod(path, 0o600)`.
- **L5** `pixel_width_estimate` يغطّي 3 أحرف عربية (`utils/helpers.py:192`): وسّع جدول العرض أو استخدم قياساً تقريبياً موحّداً للعربية.
- **L6** orphan most/least يتداخلان (<40 رابطاً) (`analyzers/orphan_finder.py:98`): إن كان العدد < 40 لا تُظهر least منفصلة، أو أزل التكرار.
- **L7** عتبات thin_content غير قابلة للضبط ونصوص الوصف ثابتة (`main.py:269`, `analyzers/seo_issues.py:456,574`): مرّر `critical_threshold`/`text_ratio_threshold` من config، واجعل نصوص الوصف ديناميكية بالعتبات.
- **L8** `max_pages` overshoot (`async_core.py:315`): الوجه التجميلي لـ C1؛ يُحَل تلقائياً عند معالجة C1.

---

## 🔒 إيجابيات أمنية (لا إجراء مطلوب) ✅
- لا SQL injection (`?` placeholders + `VALID_TABLES` whitelist).
- XXE مُعالَج بـ `defusedxml` (مثبّت في requirements + تحذير fallback).
- لا deserialization خطِر (`yaml.safe_load`، لا `pickle`/object hooks).
- لا تنفيذ كود (صفر `eval/exec/os.system/subprocess`).
- لا ReDoS (تعابير خطّية).
- `verify_ssl=True` افتراضياً، الأسرار خارج VCS/السجلات/المخرجات، blake2b بدل MD5، كشف حلقات redirect/sitemap.

---

## 🧪 الاختبارات والتوثيق
- **تغطية ضعيفة:** 7 اختبارات (robots/DB bundle/CSV/url_issues/canonical). غير مغطّى: محركا الزحف، schema/hreflang/sitemap_diff/redirect/duplicate/orphan/thin/broken/seo_issues، Excel، التكاملات.
  - **الإصلاح:** أضف اختبارات وحدة للمحللات على صفوف dict (مثل dummy DB rows)، واختبار قبول end-to-end على خادم محلي يشمل HTML/sitemap/404/redirect، واختبار خاص لـ C1 (إنهاء عند `max_pages`).
- **توثيق مبالغ:** `modes/audit.py` يقول "29+ مشكلة" والفعلي 23؛ README يعلن schema_validator/sitemap_diff كاملتين رغم H6/H7.
  - **الإصلاح:** صحّح الأرقام وأضف ملاحظات قيود حتى تُعالَج H6/H7.

---

## ترتيب الأولوية المقترح للإصلاح
1. **C1** (تعليق max_pages) — الأخطر؛ يعطّل الإنتاج على المواقع الكبيرة.
2. **C2 + C3** (استئناف async + تكرار الجداول) — مترابطان؛ سلامة البيانات.
3. **H6 + H7** (microdata + sitemap_diff) — أبرز ميزتين معطّلتين جزئياً.
4. **M1 + M8** (حقن صيغ + متانة Excel) — Excel هو ملف تسليم العميل.
5. **H1/H2/H3/H4/H5** ثم باقي M ثم L.

> ملاحظة تحقّق: ادعاء "اختلال `task_done` يفسد `join()` وسط الزحف" منخفض الاحتمال (المسار محمي بـ `try/except ValueError`). التعليق المؤكَّد فعلياً هو آلية `max_pages` (C1).
