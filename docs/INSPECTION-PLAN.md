# SCT — خطة الفحص التدريجية الشاملة (v2)

خطة فحص من **الأساس إلى الطرف** لأداة **SCT (Simple Crawler Tool)** تغطّي: الاستدعاءات، التعريفات/العقود، الأمان، المنطق، سير العمل، مسار البيانات، قاعدة البيانات (SQLite per-job)، **عزل بيانات المهام**، الفحص الساكن والأدوات، الديون التقنية، الأكواد الميتة، الأداء والصمود والتشغيل والرصد، والواجهات (a11y/RTL/responsive)، مع **جاهزيّة النشر مفتوح المصدر**.

> مبنيّة على مسح فعليّ للشيفرة (~15,000 LOC، أسطول فحص 14 بُعداً، v1.13.22). الأدلّة بصيغة `file:line` / `csv.column`.
> مرجع النقاط: `docs/CLI.md` (`main.py`) · `docs/USER_GUIDE.md` (webapp) · `docs/ARCHITECTURE.md` (module map).
> اصطلاح: ✅ نجاح · ⚠️ ملاحظة · ❌ فشل يوقف الانتقال.

---

## §0 — خريطة أنواع الفحص (هل الخطة تشملها؟)

| نوع الفحص | مشمول | أين | الأداة/الطريقة |
|---|---|---|---|
| وظيفي / تكامل / سيناريو | ✅ | مراحل 0–7 | يدوي + `python -m unittest` |
| الاستدعاءات (API/authz) | ✅ | 1، 8، 12 | curl + `Authorization: Bearer` + `?token=` |
| التعريفات/العقود (schemas/types) | ✅ | 12 | OpenAPI diff، pydantic في FastAPI form |
| الأمان (SSRF/CSRF/authz/أسرار) | ✅ | 8 + 8-ملحق | Bearer token + Origin guard + rate limits |
| **عزل بيانات المهام** | ✅ | **10** | path-traversal + `_valid_job_id` regex |
| المنطق / آلة الحالة | ✅ | 13 | job lifecycle (running→partial/complete/failed/stopped) |
| مسار البيانات (hop-by-hop) | ✅ | 14 | Crawl → SQLite → Analyze → Export |
| قاعدة البيانات (SQLite per-job) | ✅ | 11 | `crawl_audit.db` + `_ALLOWED_TABLES` |
| حقول مكرّرة/مهملة/زائدة في CSV/JSON | ✅ | 11، 17 | grep + audit JSON `raw_arrays_omitted` |
| الفحص الساكن (lint/type/SAST) | ✅ | 15 | `ruff` مقصود؛ mypy/bandit ناقصان |
| الاعتماديات/CVE + أسرار | ✅ | 15 | `pip-audit` (CI advisory)؛ `gitleaks` مقترح |
| الديون التقنية | ✅ | 16 | ~5 مخاطر معماريّة كامنة (audit 2026-06-24) |
| الأكواد الميتة | ✅ | 17 | `ruff F401,F841`؛ `vulture` مقترح |
| الأداء/التحميل/soak | ✅ | 18 | crawl 33k pages (4س + 40د تحليل) |
| الصمود/الفوضى/إعادة الإقلاع | ✅ | 18 | Ctrl+C أثناء المراحل + terminate |
| التشغيل/النشر/التراجع | ✅ | 9، 18 | `START.bat` / `docker compose` / `installer/` |
| الرصد (سجلّ/مقاييس/تتبّع) | ✅ | 18 | `metrics.json` + `run.log` + `progress.json` |
| الواجهات: a11y/RTL/responsive | ✅ | 19 | axe-core (v1.13.18)، RTL أصلي |
| التكاملات الخارجيّة (Google) | ✅ | 2، 23 | GSC/GA4/PSI/CrUX + OAuth flow |
| التكاملات المدفوعة | ✅ | 23 | Ahrefs v3 / Majestic OpenApp / AI providers |
| **جاهزيّة OSS للنشر** | ✅ | **20** | LICENSE, README, SECURITY, CHANGELOG, CI |
| **قوالب المنصّات (presets)** | ✅ | **21** | Zid, Salla, Shopify, Woo, WordPress |
| **Reports / Downloads** | ✅ | **22** | CSV/JSON/Excel/XML/HTML/PDF/sitemap |
| **Priority Engine v2 + Action Board** | ✅ | **24** | severity × impact × ease × confidence |
| **Release artifact النهائي** | ✅ | **25** | version bump + tag + CHANGELOG + push |
| **توافق الوثائق مع الكود** | ✅ | **26** | ARCHITECTURE/USER_GUIDE/CLI/RUNBOOK/README |
| **دورة حياة مفاتيح API الخارجية** | ✅ | **27** | GSC OAuth tokens + PSI/AI keys via `.env` |
| **حماية بيانات المهام على القرص** | ✅ | **28** | atomic writes v1.13.16 F45 + Storage Sense |
| **القبول النهائي والتوقيع** | ✅ | **29** | معايير القبول للـMIT release |

---

## §A — الثغرات المؤكّدة → سجلّ منفصل

الثغرات الفعلية التي كشفها الفحص العميق (14-dimension audit، 2026-06-24) وحالة إصلاح كلٍّ في **CHANGELOG.md**:

- ✅ **9 blockers** أُصلحت في v1.13.17 (Top-10 audit fixes) — OAuth CSRF، XSS، credential leak، crawler race، CSV formula injection…
- ✅ **1 مؤجَّل عمداً**: F53 (token في URL) — يحتاج ticket-cookie refactor
- ✅ **F57 صُنّف "already-correct"** بحسب تصميم v1.13.15 B2

> قاعدة التسليم: لا نشر مع ثغرة **حاجبة (blocking)** مفتوحة إلا بقبول مخاطر مكتوب في CHANGELOG (المرحلة 29).

---

# القسم الأول — الفحص الوظيفي (Runbook تشغيلي)

## المرحلة 0 — البيئة والتبعيّات
| # | الفحص | كيف | المتوقّع |
|---|---|---|---|
| 0.1 | Python 3.10+ | `python --version` | 3.10 → 3.13 (Python 3.10 EoL 2026-10-04) |
| 0.2 | pip requirements | `pip install -r requirements.txt` | لا فشل |
| 0.3 | Playwright + Chromium | `python -m playwright install chromium` | مثبّت (لازم لـJS render + PDF) |
| 0.4 | Optional deps (Excel/GA4) | `pip show openpyxl google-analytics-data` | mismatch يُعطي تحذير لا crash |
| 0.5 | `.env` / secrets | ملفّ موجود، مفاتيح PSI/AI فيه | gitignored ✅ |

## المرحلة 1 — الأساس (webapp + auth + health)
| # | الفحص | كيف | المتوقّع |
|---|---|---|---|
| 1.1 | إقلاع webapp | `python webapp/run.py` | «Application startup complete» + `~/.sct/local_token` مُنشأ |
| 1.2 | الصحّة | `curl http://127.0.0.1:8000/health` + `/readyz` | 200 لكليهما (بلا auth) |
| 1.3 | `/api/*` بلا token | `curl -i http://127.0.0.1:8000/api/requirements` | 401 + رسالة تشرح مسار الملفّ |
| 1.4 | `/api/*` مع Bearer | `curl -H "Authorization: Bearer $(cat ~/.sct/local_token)" .../api/requirements` | 200 |
| 1.5 | `/api/*` مع `?token=` | `curl ".../api/requirements?token=$(cat ~/.sct/local_token)"` | 200 (SSE + `<a href>` يعتمدان على هذا) |
| 1.6 | Rate limits | 11 طلب `/api/start` في دقيقة | الحادي عشر → 429 |
| 1.7 | CSRF Origin guard | `curl -H "Origin: https://evil.example" -X POST .../api/start` | 403 |
| 1.8 | `/jobs/` → redirect | `curl -i .../jobs/` (v1.13.19) | 302 إلى `/` |
| 1.9 | `/jobs/<invalid>` → redirect | `curl -i .../jobs/_google` (v1.13.22) | 302 إلى `/` |

## المرحلة 2 — التكاملات (Google)
| # | الفحص | كيف | المتوقّع |
|---|---|---|---|
| 2.1 | رفع `client_secret.json` | POST `/api/google/upload` | 200 + الملفّ في `webapp_jobs/_google/` (mode 0600) |
| 2.2 | OAuth authorize (state) | POST `/api/google/authorize-url` (v1.13.17 F31) | state 32-byte محفوظ + رابط auth صحيح |
| 2.3 | OAuth callback بـstate خاطئ | POST callback بـstate مختلف | 400 |
| 2.4 | OAuth `_paste_flows` concurrency | 2 authorize-url متزامنَين ثم callback الأوّل | كلاهما ينجح مستقلاً (F32) |
| 2.5 | GSC token refresh | انتظر انتهاء expiry → طلب GSC | يُتجدَّد تلقائياً (atomic write) |
| 2.6 | `/api/google/status` | `curl .../api/google/status` | `{"expired":false, "connected":true}` بعد الربط |
| 2.7 | Disconnect | POST `/api/google/disconnect` | tokens تُحذف من القرص |

## المرحلة 3 — Crawl على موقع lab (بسيط، بلا تكاملات)
| # | الفحص | كيف | المتوقّع |
|---|---|---|---|
| 3.1 | بدء crawl | POST `/api/start` بـ`url=https://example.com` + `max_pages=20` | job_id في response + progress.json يُنشأ |
| 3.2 | SSE stream | `curl .../api/jobs/<id>/events?token=...` | events متتالية (data, end) |
| 3.3 | Progress polling | `curl .../api/jobs/<id>/progress` | pages_crawled + phase_label live |
| 3.4 | Job page HTML | `curl .../jobs/<id>` | HTML صحيح + `token` مُحقن |
| 3.5 | نهاية طبيعيّة | انتظر end → job.json | status=complete + result.json مسار موجود |
| 3.6 | CSV files | `ls webapp_jobs/<id>/output/csv/` | 21 ملف على الأقلّ (pages, links, images, seo_issues…) |

## المرحلة 4 — إعدادات متقدّمة
| # | الفحص | المتوقّع |
|---|---|---|
| 4.1 | Platform preset (Zid/Salla/Shopify/Woo/WordPress) | يستبعد ~15,000 URL على متجر Zid |
| 4.2 | JS render (v1.13.18) | Chromium يعمل + `js_rendered=true` في pages.csv |
| 4.3 | Accessibility check (v1.13.18) | `accessibility.csv` + `accessibility_issues.csv` (v1.13.22 F أصلح allow_cdn) |
| 4.4 | Include/exclude patterns | `?exclude=*/checkout*` يستبعد كل السلة |
| 4.5 | User-Agent presets (Googlebot/Bingbot) | يكشف Cloudflare bot challenges |
| 4.6 | Adaptive throttle | 429s يبطئ تلقائياً |
| 4.7 | Generate sitemap | `sitemap.xml` يُنتَج من indexable pages |
| 4.8 | Custom extraction rules | CSS/XPath/regex rules تُطبَّق |

## المرحلة 5 — Crawls على منصّات حقيقيّة
| # | الفحص | المتوقّع |
|---|---|---|
| 5.1 | WordPress (internal-wp-alt-test.example أو internal-zid-test.example) | preset يستبعد `?replytocom=`, `/feed/`, `/tag/`, `/wp-admin` |
| 5.2 | Zid store (internal-zid-test.example) | preset يستبعد `?sort_by`, `/cart`, `/checkout` |
| 5.3 | Cloudflare-protected site | 403 Just a moment... تُحصى في `pages_4xx.csv` |
| 5.4 | Large sitemap (>50k URLs) | `deferred_urls.csv` يحوي pagination-deep + filter-combinations |
| 5.5 | Multilingual site (hreflang) | `hreflang_issues.csv` غير-متبادَل صحيح |

## المرحلة 6 — تدفّقات المستخدم (UI)
| # | الفحص | المتوقّع |
|---|---|---|
| 6.1 | Stop button (v1.13.15/16) | badge=stopped فوراً + partial export خلال ~60s + downloads تظهر تلقائياً |
| 6.2 | Force-kill (v1.13.21 F2) | subprocess يموت فوراً + status=stopped بلا race |
| 6.3 | Phase 2 (deferred URLs) | يستأنف من `deferred_urls.csv` + يُمدِّد audit.json |
| 6.4 | Generate HTML/PDF | on-demand — Playwright يُحضّر Chromium أوّل مرّة (30-60s) |
| 6.5 | Generate Excel/XML | ينتج من `audit.json` بلا حاجة لـcrawl جديد |
| 6.6 | Download ZIP-all | كل المخرجات مضغوطة (يحترم `_safe_under_jobs` guard) |
| 6.7 | Explore page | `/jobs/<id>/explore` — فلترة + بحث + sort على pages |
| 6.8 | Action Board | `/jobs/<id>/board` — do-now/dev/platform/content مصنّفة |
| 6.9 | Compare (crawl-over-time) | `/jobs/<id>/compare` — fixed/new/persisting issues |
| 6.10 | Graph view (v1.13.22) | `/jobs/<id>/graph` — يقرأ من inlinks.csv عند نقص audit["links"] |
| 6.11 | Welcome banner (v1.13.21) | يظهر على كل تحميل — ✕ يخفيه دائماً عبر localStorage |
| 6.12 | Recent jobs list | يعرض حتى 15 مهمّة + `عرض`/`حذف` — v1.13.20 self-heal |

## المرحلة 7 — الصمود والفشل
| # | الفحص | المتوقّع |
|---|---|---|
| 7.1 | Subprocess crash (kill -9) | `_watch` يلتقط الخروج + writes status=failed |
| 7.2 | AI provider أو PSI ساقط | analyzer يستمرّ (log.exception + fallback فارغ) |
| 7.3 | SSRF على `?url=http://169.254.169.254/` | `is_safe_remote_url` يرفض (v1.09) |
| 7.4 | gzip bomb | صفحة > cap تُتخطّى بلا OOM |
| 7.5 | Playwright timeout | JS render يفشل → صفحة تُحفَظ كـHTML خام |
| 7.6 | 500 على أيّ endpoint | global exception handler → `{"error":"internal_error","request_id":...}` بدل leak |
| 7.7 | webapp restart أثناء crawl | subprocess مستقلّ → يكمل بلا تأثّر |
| 7.8 | Ctrl+C على webapp | uvicorn SIGTERM → subprocess يبقى (subprocess.Popen) |

---

# القسم الثاني — الفحص البنيوي والعميق

## المرحلة 8 — الأمان (SSRF + CSRF + Injection + XSS) 🔐
| # | الفحص | كيف | المتوقّع |
|---|---|---|---|
| 8.1 | SSRF على `crawl.start_url` | `?url=http://127.0.0.1:8000/` → 400 | مرفوض قبل subprocess spawn (v1.09-B5) |
| 8.2 | SSRF على redirect chains | صفحة تُوجّه إلى `10.0.0.1` | مرفوض في المنتصف |
| 8.3 | SSRF على JS renderer (v1.13.17 F04) | `allow_private_hosts` param صريح | لا `getattr` fallback إلى False |
| 8.4 | Argv injection | `?mode=--eval` أو `?url=--rm-rf` | mode whitelist + url validate (v1.09-B4) |
| 8.5 | SQL injection على table names | `_ALLOWED_TABLES` frozenset (v1.10-A2) | كلّ f-string interpolation مُصفَّى |
| 8.6 | Path traversal في download | `?file=../../etc/passwd` | `_safe_under_jobs` يرفض |
| 8.7 | XSS في graph.html (v1.09-B3) | payload في audit JSON URL | escape كامل عبر `_esc()` (v1.13.17 F49/F50) |
| 8.8 | XSS في client_name/logo_url | `<script>` في form | `_safeLogoUrl()` يرفض غير http(s) (F52) |
| 8.9 | Formula injection في CSV | ` =SUM(1+1)` مع مسافة بادئة | strip whitespace قبل الفحص (v1.13.17 F21) |
| 8.10 | Origin CSRF guard | `Origin: https://evil.com` على POST | 403 |
| 8.11 | Token leak في logs | `grep -i "bearer\|token" webapp_jobs/*/run.log` | 0 hits |
| 8.12 | Secret leak في `job.json` | `_strip_sensitive_in_place` (v1.13.17 F61) | credentials_file/api_key/token غير موجودة |

## المرحلة 10 — عزل بيانات المهام (Data Isolation) 🔑
> النموذج: كل مهمّة تحت `webapp_jobs/<job_id>/` مع `job_id` صيغته صارمة `^\d{8}_\d{6}_[0-9a-f]{6}$` (v1.09-B4). SCT محلي single-user، لكنّ الملفّات downloadable → عزل الأسرار مطلوب.

| # | الفحص | كيف | المتوقّع |
|---|---|---|---|
| 10.1 | Path traversal في job_id | `GET /api/jobs/../../etc/passwd` | 400 (`_valid_job_id` يرفض) |
| 10.2 | Path traversal في download | `?file=../../<sibling_job>/audit.json` | مرفوض عبر `_safe_output_file` |
| 10.3 | Job.json يحوي عناوين URLs فقط | grep credentials في `webapp_jobs/*/job.json` | 0 hits |
| 10.4 | config.yaml بلا secrets (v1.13.17 F61) | grep api_key في `webapp_jobs/*/config.yaml` | 0 hits (تُمرَّر عبر env vars) |
| 10.5 | SSE isolation | client مسجَّل على job A لا يستقبل events job B | separate stream per job_id |
| 10.6 | Log file bytes cap | `run.log` > 500MB لا يُحمَّل في log-board OOM guard (v1.09-B4) | حدّ صارم |
| 10.7 | ZIP download يحترم guards | `download-all` يجمع فقط ملفّات تحت job_dir | لا exfiltration خارجيّ |
| 10.8 | `webapp_jobs/_google/` isolation | tokens بصلاحيات 0600 | مقروءة من مالك العمليّة فقط |

## المرحلة 11 — تدقيق قاعدة البيانات (SQLite per-job) 🗄️
> `webapp_jobs/<id>/state/crawl_audit.db` (per-job) + `webapp_jobs/<id>/state/api_cache.db`. الجداول: pages, links, images, headings, http_headers, schema_entries, redirects, external_link_status, crawl_queue, visited_urls, deferred_urls, resources.

| # | الفحص | SQL / كيف | المتوقّع |
|---|---|---|---|
| 11.1 | `_ALLOWED_TABLES` completeness | grep table names في `database.py` مقابل `_ALLOWED_TABLES` | كلّ table في القائمة |
| 11.2 | busy_timeout | `PRAGMA busy_timeout;` | 5000 (v1.10-C1 M-4) |
| 11.3 | WAL mode | `PRAGMA journal_mode;` | wal (writer + readers متزامنون) |
| 11.4 | Foreign keys | `PRAGMA foreign_keys;` | لا شرط قاسٍ (سرعة أولاً) |
| 11.5 | Schema drift بعد v1.13 | migration script + backfill | idempotent |
| 11.6 | Race على mark_visited | 15 workers متزامنون | لا duplicate visited_urls (v1.13.17 F01 lock) |
| 11.7 | Deferred dict race | discover → check_cap → append (F02) | atomic تحت `_deferred_lock` |
| 11.8 | Audit JSON `raw_arrays_omitted` | `links`/`images`/`headings` غير موجودة في JSON | ✅ مقصود منذ v1.13 |
| 11.9 | Full audit dump (`output.json_full: true`) | audit JSON > 300MB | لا يُحمَّل في UI (guard) |
| 11.10 | api_cache TTL | entries > 24س | تُستبعد على القراءة |
| 11.11 | Cache identity (v1.09-B7) | نفس URL + headers مختلفة | مفتاح كاش مختلف |
| 11.12 | SQLite version | يحتاج 3.35+ لبعض PRAGMAs | حدّ أدنى موثّق في README |

## المرحلة 12 — العقود والتعريفات (Contracts/Schemas) 📜
> FastAPI + Pydantic منذ v1.10 (Envelope غير موحّد — `data: Any` في بعض المسارات).

| # | الفحص | كيف | المتوقّع |
|---|---|---|---|
| 12.1 | OpenAPI snapshot | `curl .../openapi.json > base.json` | ثبات schema، diff بعد كل نسخة |
| 12.2 | Form field validation | `?max_pages=abc` (v1.13.17 A1-1) | `_safe_int` fallback بدل HTTP 500 |
| 12.3 | Error response consistency | `{"error":"internal_error","request_id":"..."}` (v1.10-A3) | لا leak file paths/repr |
| 12.4 | audit JSON `_meta.version` | v1.13.22 حالياً | يتطابق مع `json_exporter.py` |
| 12.5 | CSV column stability | header of `pages.csv` مقابل CHANGELOG breaking-changes | لا إضافة/حذف بلا bump minor |
| 12.6 | JSON responses UTF-8 | Arabic chars في content | `ensure_ascii=False` |
| 12.7 | Priority engine schema | `page_priority.csv` + `action_board.csv` | كل columns موثّقة |

## المرحلة 13 — المنطق وآلة الحالة (Job Lifecycle) 🔁
> `starting → running → (analyzing → integrations → exporting) → complete | partial_max_pages | stopped | failed`

| # | الفحص | كيف | المتوقّع |
|---|---|---|---|
| 13.1 | Terminal state consistency | job.json + progress.json يقولان نفس الشيء | v1.13.11 F5 sync |
| 13.2 | Stop before signal (v1.13.15 B1) | `stop()` يكتب "stopped" قبل send_signal | `_watch` يرى marker بلا race |
| 13.3 | Force-kill same pattern (v1.13.21 F2) | lookup+write+kill داخل قفل واحد | لا orphan proc |
| 13.4 | E-Stop shortcut (v1.13.16) | Stop أثناء crawl → skip integrations + AI → export pages فقط | export يكتمل خلال grace 60s |
| 13.5 | KeyboardInterrupt around phases | Ctrl+C أثناء analysis | falls-through إلى export partial (v1.13.15 B2) |
| 13.6 | Phase 2 idempotency | phase2 مرّتين على نفس job | reentrancy guard (v1.09-B12) |
| 13.7 | Return codes | `rc=0` complete · `rc!=0` failed · `rc=130` KeyboardInterrupt | مصنّفة صحيح في `_watch` |
| 13.8 | Progress phase_label | crawling → analyzing → exporting → stopped | phaseBox يختفي على terminal (v1.13.16) |
| 13.9 | `_hasFiles(result)` gate (v1.13.16) | result={} فارغ لا يفعّل `_safeFinish` | يُنتظر ملفّ فعلي |
| 13.10 | Concurrent generate race (v1.13.17 F47) | HTML + PDF بالتوازي | per-job lock — لا يستبدل result |

## المرحلة 14 — تتبّع مسار البيانات (Data-flow) 🔎
7 hops: `sitemap fetch → URL queue → fetch page → SQLite insert → analyzer read → integrations merge → export (CSV/JSON)`

| # | الفحص | نقطة الرصد | المتوقّع |
|---|---|---|---|
| 14.1 | H1 sitemap parse | `run.log: → N URL مُستخرج من` | count صحيح |
| 14.2 | H2 URL queue → visited | `visited_urls` count = pages_crawled | مطابق |
| 14.3 | H3 fetch → SQLite | `pages` table + `http_headers` | صف لكل صفحة |
| 14.4 | H4 links extraction | `all_links.csv` = `links` table | مطابق |
| 14.5 | H5 analyzer reads (v1.09-B2 status code coercion) | 4xx/5xx كسلسلة أو رقم | يُعامَل صحيح في كل analyzer |
| 14.6 | H6 integrations merge (unified) | `unified_rows` = pages × GSC × GA4 | join keys صحيحة |
| 14.7 | H7 export → CSV/JSON | 21 CSV + audit.json | complete + valid |
| 14.8 | metrics.json completeness | counters + gauges + events | مسجَّل لكل مرحلة |
| 14.9 | run.log tokens leak | grep secrets | 0 hits |
| 14.10 | atomic writes (v1.13.16 F45) | crash mid-write | job.json/progress.json ليس نصف-مكتوب |
| 14.11 | Log file handle (v1.13.17 F46) | parent يُغلق stdout handle | لا Windows "file in use" |

## المرحلة 15 — الفحص الساكن والأدوات (Static / Tooling) 🧰
| الأداة | الحالة | الأمر |
|---|---|---|
| ruff | ✅ موجود | `ruff check webapp seo_crawler tests` |
| compileall | ✅ موجود | `python -m compileall -q webapp seo_crawler tests` |
| pytest / unittest | ✅ 94 اختبار (v1.13.22) | `python -m unittest discover -s tests` |
| pytest --cov | ⚠️ يُضاف | `pip install pytest-cov && pytest --cov=webapp --cov=seo_crawler` |
| pip-audit | ✅ في CI (advisory) | `pip-audit -r requirements.txt --strict` |
| **mypy** | ❌ يُضاف | `mypy webapp seo_crawler` |
| **bandit** | ❌ يُضاف | `bandit -r webapp seo_crawler -x tests` |
| **gitleaks** (أسرار) | ❌ يُضاف | `gitleaks detect --source .` |
| **vulture** (dead code) | ❌ يُضاف | `vulture webapp seo_crawler --min-confidence 80` |
| **axe/pa11y على webapp** | ❌ يُضاف | `pa11y http://127.0.0.1:8000/` |
| GitHub Actions CI | ✅ موجود | `ci.yml` — Linux + Windows |
| Dockerfile multi-stage | ✅ v1.11 E | `docker build .` |

## المرحلة 16 — الديون التقنية (Technical Debt) 🧱
> **5 مخاطر معماريّة كامنة** كشفها deep audit (2026-06-24):

| # | البند | الدليل / الإجراء |
|---|---|---|
| 16.1 | `except Exception: pass` منتشر | `database.py`, `progress_service.py`, `snapshot_state`, exporters, `backlinks_api.py` — أضف log |
| 16.2 | Module-level mutable globals | `_RATE_BUCKETS`, `_procs`, `_set_counter`, `_gen_locks` — thread-safety مراجَعة |
| 16.3 | Non-atomic writes خارج v1.13.16 F45 | sitemap generator, excel exporter, OAuth client_secret upload — نفس pattern |
| 16.4 | URL normalization inconsistency | `url_classifier` case-sensitive، `normalize_url` يهمل `keep_blank_values` — توحيد |
| 16.5 | Blind trust في APIs الخارجيّة | `_sf`/`_si` مطبَّق في `report_join.py` فقط — cascade إلى priority_engine + integrations_summary + log_analyzer |
| 16.6 | ملفّات ضخمة | `async_core.py` ~1600 LOC + `main.py` (بعد refactor v1.12 صار 513 LOC) — راقب النموّ |
| 16.7 | ~47 `noqa: BLE001` | كلّ واحد له سبب موثّق؟ |
| 16.8 | Duplicate helpers | `_iso_datetime` / `_split_values` عبر ملفّات → shared module |
| 16.9 | Magic numbers | timeouts/limits → `constants.py` |
| 16.10 | requirements-pinned.txt | مثبّت؛ `pip list --outdated` دوري |

## المرحلة 17 — الأكواد الميتة (Dead Code) 🧹
| # | العنصر | الدليل |
|---|---|---|
| 17.1 | `data-tip-key` غير مُفعَّل | 6 بطاقات في job.html — إمّا فعّل نظام tooltip أو أزل (documented — planned v1.14) |
| 17.2 | `_extract_oauth_code` بعد v1.13.17 F31 | كان str→str، الآن wrapper حول `_extract_oauth_parts` | حافظ عليه لتوافق tests |
| 17.3 | Unused fields في `audit.json` | `raw_arrays_omitted` marker يوثّقها | مقصود |
| 17.4 | endpoints بلا واجهة | قابِل كل `@router.get` مقابل fetch/href في templates | 0 orphans |
| 17.5 | Legacy code | pre-v1.10 هجَر في v1.12 refactor | grep غير موجود |
| 17.6 | مسح آليّ | `ruff --select F401,F841 webapp seo_crawler` | 0 hits |

## المرحلة 18 — الأداء والصمود والتشغيل والرصد ⚙️
| # | الفحص | كيف | المتوقّع |
|---|---|---|---|
| 18.1 | Crawl 33k pages | تشغيل حقيقي على internal-zid-test.example | ✅ نجح في v1.13.22 (5س 17د) |
| 18.2 | Memory caps (v1.13.17 F05/F06) | `all_js_diff` cap 100k + `all_accessibility` cap 50k | dropped counter + one-time warning |
| 18.3 | Playwright cleanup | JS render على 100 صفحة → قتل webapp | Chromium يُغلق بلا zombie |
| 18.4 | AI provider timeout | DeepSeek/OpenAI مع latency عالٍ | fallback بلا crash (v1.13.17 F28 hardened Gemini) |
| 18.5 | Concurrent HTTP fetches | 15 workers + adaptive_throttle | 429 يبطئ + recover |
| 18.6 | SQLite lock contention | crawl + generate بالتوازي | busy_timeout 5s كافٍ |
| 18.7 | Disk full mid-crawl | املأ D:\ 95% | صفحات جديدة تفشل، الموجودة تُصدَّر |
| 18.8 | subprocess restart | webapp restart أثناء crawl | subprocess مستقلّ يكمل |
| 18.9 | Windows signal handling (v1.13.17 A2-2) | Ctrl+Break أثناء render | handler يُعاد بعد الخروج |
| 18.10 | Progress live update | refresh page أثناء crawl (v1.13.16) | counters + phase live، لا صفر |
| 18.11 | Log rotation | `run.log` > 1GB | يبقى (لا rotation حالياً — موثّق) |
| 18.12 | Deployment: `START.bat` | double-click على Windows | فتح متصفّح تلقائياً + token يُطبع |
| 18.13 | Deployment: Docker | `docker compose up --build` | 200 على `/health` |
| 18.14 | Deployment: Windows installer | `installer\install.ps1` | يُنشئ venv + shortcuts |
| 18.15 | `/health` + `/readyz` | exempt من auth | 200 (readyz يفحص كتابة `webapp_jobs/`) |
| 18.16 | Correlation IDs | `X-Request-ID` في response | مطبوع في logs (v1.10-B1b) |
| 18.17 | metrics.json exists | كل crawl ينتج ملفّ | counters/gauges/events كاملة |
| 18.18 | Global exception handler (v1.10-A3) | trigger AssertionError في endpoint | `{"error":"internal_error"}` + traceback فقط في server log |

## المرحلة 19 — الواجهات (a11y / RTL / responsive / أخطاء) 🖥️
| # | الفحص | كيف | المتوقّع |
|---|---|---|---|
| 19.1 | a11y | `pa11y http://127.0.0.1:8000/` + job page | 0 مخالفة حرجة |
| 19.2 | RTL (Arabic) | لغة افتراضيّة `ar` + dir=rtl | مضبوط + toggle لـEN |
| 19.3 | Responsive | 800×600 لمس (Windows tablet) | لا تمرير أفقي |
| 19.4 | Error boundaries | JS error في browser console | لا شاشة بيضاء |
| 19.5 | i18n coverage | كل `data-i18n` له مدخل ar + en (v1.09) | audit script يكشف drift |
| 19.6 | XSS-safe rendering (v1.13.17 F49/F50) | `_esc()` على كل innerHTML | 0 unescaped |
| 19.7 | Force-directed graph (v1.13.22) | 500 nodes cap | يعمل بلا تجميد browser |
| 19.8 | Print report | `report.pdf` عبر Playwright | Arabic RTL صحيح |

---

# القسم الثالث — فحص ما-قبل-النشر (المنتج مفتوح المصدر)

## المرحلة 20 — جاهزيّة OSS للنشر 📦
> مرجع: `README.md`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, `ROADMAP.md`.

| # | الفحص | المتوقّع |
|---|---|---|
| 20.1 | LICENSE موجود | MIT (2026 Ahmad-Ajm) |
| 20.2 | README quick-start | يعمل من الصفر لـstranger |
| 20.3 | README badges | build + license (Python badge conditional) |
| 20.4 | SECURITY.md مع reporting channel | GitHub Private Security Advisory + email |
| 20.5 | CHANGELOG محدَّث | يغطّي كل v1.13.x |
| 20.6 | ROADMAP يعكس الحالة | Recently shipped حتى v1.13.22 |
| 20.7 | git history نظيف | 0 hits لـ`ahaj82@hotmail.com` + no client-name leaks (filter-repo passes v1.13.10-14) |
| 20.8 | Author email = `@users.noreply.github.com` | ✅ في كل الـ45+ commit |
| 20.9 | `.env.example` بلا secrets | placeholders فقط |
| 20.10 | `config.example.yaml` بلا secrets | credentials_file placeholders |
| 20.11 | GitHub repo visibility | خاص حالياً — flip to public عند الجاهزيّة |

## المرحلة 21 — قوالب المنصّات (Presets) 🛍️
> مرجع: `seo_crawler/seo_crawler/config_presets.py` + `tests/test_crawler.py`.

| # | الفحص | المتوقّع |
|---|---|---|
| 21.1 | Zid preset | `?sort_by`, `?orderby`, `/cart`, `/checkout`, `/my-account` مُستبعَدة |
| 21.2 | Salla preset | نفس الأنماط + `salla.sa`, `s-cdn.net` signatures |
| 21.3 | Shopify preset | `/cart`, `/checkout`, `?variant=`, filter combinations |
| 21.4 | WooCommerce preset | `/cart`, `/checkout`, `?add-to-cart` |
| 21.5 | WordPress preset (v1.13.5) | `?replytocom=`, `/feed/`, `/tag/`, `/author/`, `/wp-admin`, `/wp-json/`, `/xmlrpc.php` + 7 query param strips |
| 21.6 | Detection order | Woo قبل WordPress (Woo يفوز على overlap) |
| 21.7 | `apply_preset` idempotency | apply مرّتين على نفس config | dedup صحيح (`if pat not in existing`) |
| 21.8 | User patterns محفوظة | user `exclude_patterns` لا تُمحى |
| 21.9 | لا preset اختير | crawl يعمل بلا فلاتر إضافيّة |
| 21.10 | UI dropdown يعكس القائمة | إضافة preset جديد → dropdown محدَّث |

## المرحلة 22 — التقارير والتنزيلات (Reports/Downloads) 📊
| # | الفحص | المتوقّع |
|---|---|---|
| 22.1 | CSV export (21 file) | كل الأنواع مُنتَجة |
| 22.2 | JSON export | مع/بلا `output.json_full` |
| 22.3 | Excel export (optional) | openpyxl مثبَّت → ملفّ سليم؛ غير مثبَّت → skip + hint |
| 22.4 | XML export | valid XML (defusedxml للـparsing) |
| 22.5 | HTML report | Arabic RTL + مخصَّص بـclient_name/logo_url |
| 22.6 | PDF report | Playwright يُنتج PDF من HTML |
| 22.7 | sitemap.xml generator | من indexable pages فقط |
| 22.8 | ZIP-all download | كل مجلّد output + audit.json |
| 22.9 | Selective download | تحديد ملفّات معيّنة → ZIP جزئي |
| 22.10 | Filename anti-collision | timestamp في اسم الملفّ |
| 22.11 | Formula injection في CSV/Excel (v1.13.17 F21) | `' =SUM(1+1)'` مع مسافة يُبقى نصّاً |

## المرحلة 23 — التكاملات الخارجيّة 🔌
| # | التكامل | المتوقّع |
|---|---|---|
| 23.1 | GSC — top pages + queries + cannibalization | ✅ نجح في crawl 33k |
| 23.2 | GSC URL Inspection | quota-aware + retry 429 |
| 23.3 | GA4 — landing pages + channels | ✅ نجح |
| 23.4 | GA4 property_id validation | dropdown يجلب من Admin API |
| 23.5 | PSI (50 URL sample) | 25-50s لكل URL × 2 strategies |
| 23.6 | PSI `save_raw_json` | `pagespeed_raw/*.json` |
| 23.7 | CrUX History | يتطلّب تفعيل Chrome UX Report API في GCP (403 إن غير مفعّل) |
| 23.8 | Lighthouse import (offline) | مجلد `.json` مع تقارير سابقة |
| 23.9 | AWT import (offline) | مجلد CSV من Ahrefs Webmaster |
| 23.10 | Backlinks live (Ahrefs v3) | Bearer header + لا leak في `response.url` |
| 23.11 | Backlinks live (Majestic OpenApp) | key كـquery param — key scrubbed من logs (v1.09-B6) |
| 23.12 | AI Advisor (OpenAI/Anthropic/Gemini/local) | 6-10 recommendations |
| 23.13 | AI provider misconfig (v1.13.17 F28) | Gemini response مشوّه | fallback empty + warning بدل crash |

## المرحلة 24 — Priority Engine v2 + Action Board ⚡
| # | الفحص | المتوقّع |
|---|---|---|
| 24.1 | Multi-factor scoring | severity × impact × ease × confidence |
| 24.2 | Page-type classification | product/category/blog/policy/… صحيح |
| 24.3 | Ease/owner categorization | do-now / dev / platform / content |
| 24.4 | Deterministic output | نفس audit → نفس priority scores |
| 24.5 | Platform-aware weights | Zid vs generic behaves differently |
| 24.6 | `page_priority.csv` + `action_board.csv` | كامل مع severity/hint |
| 24.7 | Board UI | فلترة + بحث + تصنيف |
| 24.8 | URL detail drill-down | يجمع crawl + GSC + GA4 + PSI + priority + a11y |
| 24.9 | Priority `do-now` count | 0 على crawl حديث كامل (كل شيء ذو نمط مشابه) |
| 24.10 | Priority overflow | 33k pages | لا int-overflow في scoring |

## المرحلة 25 — الحزمة النهائية (Release Artifact) 🏷️
| # | الفحص | المتوقّع |
|---|---|---|
| 25.1 | Version bump في `json_exporter.py` | v1.13.22 → v1.13.23 |
| 25.2 | Version في audit JSON `_meta.version` | مطابق |
| 25.3 | CHANGELOG entry جديد | تفاصيل كل التغييرات |
| 25.4 | git tag `v1.13.22` | annotated tag + push |
| 25.5 | 94/94 tests خضراء | `python -m unittest discover -s tests` |
| 25.6 | `compileall` بلا SyntaxError | كل packages تُترجَم |
| 25.7 | Fresh clone → install → run | من الصفر على جهاز جديد |
| 25.8 | Docker image build | `docker compose up --build` |
| 25.9 | Windows installer | `installer\install.ps1` |
| 25.10 | START.bat | double-click يعمل |
| 25.11 | rollback | git reset --hard HEAD~1 يُرجع كل شيء بلا loose files |
| 25.12 | لا secrets في الحزمة | grep + gitleaks |

## المرحلة 26 — توافق الوثائق مع الكود 📚
| # | الفحص | المتوقّع |
|---|---|---|
| 26.1 | README ↔ الميزات | كل feature مذكورة موجودة في الكود |
| 26.2 | ARCHITECTURE.md ↔ module map | v1.12 refactor مطابق للـservices/routers الفعليّة |
| 26.3 | CLI.md ↔ argparse | كل `--flag` موثّق (`--phase2` v1.13.9) |
| 26.4 | USER_GUIDE.md ↔ UI | كل tab/panel/button ذُكر |
| 26.5 | RUNBOOK.md ↔ الحوادث المحتملة | 9 سيناريوهات (v1.13.21 §9 = Storage Sense) |
| 26.6 | EXTERNAL_TOOLS_GUIDE.md ↔ integrations | كل تكامل موثّق |
| 26.7 | AR ↔ EN parity | ملفّات `_AR.md` مساوية للـEN |
| 26.8 | CHANGELOG يغطّي التغييرات | حتى v1.13.22 |
| 26.9 | SECURITY.md ↔ hardenings | v1.10+ surfaces موثّقة |
| 26.10 | ROADMAP.md ↔ الحالة | Recently shipped محدَّث |

## المرحلة 27 — دورة حياة مفاتيح API الخارجيّة 🗝️
| # | الفحص | المتوقّع |
|---|---|---|
| 27.1 | Google OAuth tokens في `~/.sct/` أو `webapp_jobs/_google/` | mode 0600، atomic writes |
| 27.2 | PSI API key في `.env` | env var — لا يُكتب في job config.yaml (v1.13.17 F61) |
| 27.3 | AI API keys في `.env` | نفس النمط |
| 27.4 | Backlinks API key | نفس النمط + لا leak في response.url |
| 27.5 | Token rotation (`~/.sct/local_token`) | delete + restart يُنشئ جديد |
| 27.6 | OAuth state one-shot (v1.13.17 F31) | استخدام مرّتين → 400 |
| 27.7 | `_paste_flows` TTL 10 دقائق (F32) | flow قديم يُمحى |
| 27.8 | disconnect endpoint | يحذف tokens + يوقف كل الاستدعاءات |
| 27.9 | key rate-limit awareness | PSI 240 req/min free tier — SCT يحترمه |
| 27.10 | لا raw key في UI/logs | grep 0 hits |

## المرحلة 28 — حماية بيانات المهام (Backup / Restore / DR) 💾
| # | الفحص | المتوقّع |
|---|---|---|
| 28.1 | atomic writes (v1.13.16 F45) | crash mid-write لا يُتلف job.json/progress.json |
| 28.2 | Self-heal (v1.13.20) | job.json ناقص → backfill من folder+config+run.log |
| 28.3 | Windows Storage Sense exclusion | RUNBOOK §9 يوثّق (v1.13.21) |
| 28.4 | Antivirus exclusion | RUNBOOK §9 |
| 28.5 | OneDrive dehydration | RUNBOOK §9 |
| 28.6 | `webapp_jobs/` backup manual | `zip -r backup.zip webapp_jobs/` |
| 28.7 | Restore from backup | `unzip` في مسار جديد → webapp يعرضها |
| 28.8 | Job folder deletion via UI | زر "🗑️ حذف" يشتغل + confirmation |
| 28.9 | "🧹 حذف الكل" | يستبعد المهمّة الجارية |
| 28.10 | Delete confirmation dialog | (مقترح — غير موجود حالياً) |
| 28.11 | SQLite `.db` integrity | `PRAGMA integrity_check;` بعد crash | ok |

## المرحلة 29 — القبول النهائي والتوقيع (Sign-off) ✍️
| # | البند | المتوقّع |
|---|---|---|
| 29.1 | Blocking issues | صفر critical/high مفتوح (أو قبول موقّع) |
| 29.2 | Known limitations | موثّقة في CHANGELOG (F53 token-in-URL مؤجَّل، cascade F27/F21) |
| 29.3 | Test suite 94/94 | مطلوب |
| 29.4 | CI green | Linux + Windows على GitHub Actions |
| 29.5 | Deep audit 14-dim revisited | 4 critical → 0 مفتوحة (v1.13.17) |
| 29.6 | Live crawl 33k pages | ✅ نجح (v1.13.22 test) |
| 29.7 | جاهزيّة OSS | LICENSE + README + SECURITY + CHANGELOG + ROADMAP |
| 29.8 | git history نظيف | filter-repo scrub confirmed |
| 29.9 | Sign-off من المؤلّف | Ahmad-Ajm — تاريخ + نسخة (v1.13.22 + tag) |
| 29.10 | GitHub repo → Public | flip visibility من Settings |

---

## ترتيب التنفيذ الموصى به

1. **الآن (dev محلي):** المراحل 0→7 (وظيفيّ) + **10** (عزل) + **11** (SQLite) + **20** (OSS readiness).
2. **قبل النشر:** 8 (أمن) + 12/13/14 (contracts/state/dataflow) + **21** (presets) + **22** (reports) + **23** (integrations) + **27** (API keys).
3. **دمج في CI:** 15 (أدوات ساكنة) + 17 (ميت) + 19 (واجهات) + **26** (توافق الوثائق).
4. **قبل الإنتاج على مواقع حقيقيّة:** 18 (أداء/صمود/رصد) + **28** (backup) + 16 (ديون).
5. **بوّابة النشر:** **25** (release artifact) + **29** (قبول وتوقيع) — لا تُعبَر مع ثغرة حاجبة مفتوحة.

## ملحق — أدوات مقترحة للإضافة

`mypy` · `bandit` · `pip-audit` (موجود) · `gitleaks` · `vulture` · `pa11y` · `pytest-cov` · `bundle-analyzer` للـtemplates.

> عند أيّ فشل: راجع `webapp_jobs/<job_id>/run.log` (تفصيلي مع phases)، `metrics.json` (counters/events)، `~/.sct/local_token` (auth)، و`git log --oneline -20` (recent changes).
