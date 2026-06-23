# دليل الحوادث لـSCT (للمشغّلين)

> دليل ميداني للمشغّلين على SCT (Simple Crawler Tool) v1.13. كل سيناريو
> يتّبع بنية **الأعراض → التشخيص → الحلّ** مع أوامر shell جاهزة.
> النسخة الإنجليزيّة الكاملة في [RUNBOOK.md](RUNBOOK.md).
>
> مراجع: [README](../README_ar.md) · [SECURITY](../SECURITY.md) ·
> [CHANGELOG](../CHANGELOG.md) · [USER_GUIDE_AR](USER_GUIDE_AR.md).

---

## المحتويات

1. [Google OAuth `invalid_grant` (انتهاء token كلّ 7 أيام في Testing mode)](#1-google-oauth-invalid_grant)
2. [Local token مفقود أو صلاحيّاته خاطئة → 401 على كلّ /api/](#2-local-token)
3. [`/readyz` يردّ 503 (فحص الكتابة في webapp_jobs/ فشل)](#3-readyz-503)
4. [المنفذ 8000 مشغول](#4-port-busy)
5. [زرّ Phase 2 لا يعمل](#5-phase2)
6. [`database is locked` بعد إصلاح `busy_timeout` في v1.10](#6-db-locked)
7. [القرص ممتلئ — تنظيف `webapp_jobs/` بأمان](#7-disk-full)
8. [اعتراض CSP / security-headers من scanner خارجي](#8-csp)

---

<a id="1-google-oauth-invalid_grant"></a>

## 1. Google OAuth `invalid_grant` (انتهاء token كلّ 7 أيام)

### الأعراض

- تكامل GSC/GA4 يتوقّف فجأة بعد أن كان يعمل.
- اللوغ يحوي:

  ```text
  google.auth.exceptions.RefreshError: ('invalid_grant: Token has been
  expired or revoked.', {'error': 'invalid_grant', ...})
  ```

- شارة **Google** في الصفحة الرئيسيّة بلون كهرماني/أحمر:
  «Google (منتهٍ — أعد التفويض)».
- `GET /api/google/status` يردّ `{"expired": true, ...}` (هذا الفحص أُضيف في v1.06
  لاكتشاف الانتهاء قبل بدء أيّ زحف، لا أثناءه).

### التشخيص

شاشة موافقة OAuth في Google تحتوي وضعاً «Testing» يُلغي refresh_tokens **كلّ 7 أيام**.
هذه سياسة Google، ليست خطأ في SCT — للتخلّص منها يجب وضع OAuth client في
verification process لـsensitive scopes. SCT يستدعي `creds.refresh(Request())` بشكل
نشط على كلّ token محفوظ في فحص الحالة، فيظهر الانتهاء صراحةً كـ`expired: true`.

افحص يدويّاً:

```bash
# Linux / macOS / Git Bash
curl -s -H "Authorization: Bearer $(cat ~/.sct/local_token)" \
  http://127.0.0.1:8000/api/google/status | python -m json.tool
```

```powershell
# PowerShell
$token = Get-Content "$env:USERPROFILE\.sct\local_token"
Invoke-RestMethod -Headers @{ Authorization = "Bearer $token" } `
  http://127.0.0.1:8000/api/google/status
```

ناتج متوقَّع على token منتهٍ:

```json
{
  "configured": true,
  "has_token_gsc": true,
  "has_token_ga4": true,
  "expired": true,
  "client_secret_present": true
}
```

### الحلّ

1. افتح الصفحة الرئيسيّة في المتصفّح. تبويب **التكاملات** سيُظهر «وافق بحسابي» بجانب
   الشارة المنتهية.
2. اضغط عليه. لأنّ v1.06 يحفظ `client_secret` عبر إعادة التفويض، تحتاج فقط الموافقة
   من المتصفّح — **لا** ترفع `client_secret.json` من جديد.
3. بعد انتهاء التفويض، أعد فحص `/api/google/status`. يجب أن ترى `"expired": false`.
4. أعد تشغيل الزحف.

لو `client_secret_present: false` اتبع [docs/OAUTH_SETUP.md](OAUTH_SETUP.md)
لرفع client secret أولاً.

---

<a id="2-local-token"></a>

## 2. Local token مفقود أو صلاحيّاته خاطئة → 401 على كلّ `/api/`

### الأعراض

- كل `curl` أو script يردّ:

  ```text
  HTTP/1.1 401 Unauthorized
  {"error": "unauthorized"}
  ```

- الواجهة المرئيّة في المتصفّح لا تزال تعمل (تحمّل `/` المُعفاة + تحقن fetch
  المُرمَّمة الـtoken تلقائياً).
- scripts كانت تعمل تتعطّل بعد install جديد أو `chmod` شامل.

### التشخيص

v1.10 أضاف token لكلّ install في `~/.sct/local_token` بصلاحيّات `0600` عند أوّل تشغيل.
كلّ `/api/*` (عدا `/health` و `/readyz`) يحتاجه عبر `Authorization: Bearer <token>` أو
`?token=<token>` (v1.13.2 وما بعدها). مقارنة constant-time عبر `hmac.compare_digest`.

تحقّق:

```bash
ls -la ~/.sct/local_token
cat ~/.sct/local_token
```

```powershell
Get-Item "$env:USERPROFILE\.sct\local_token" | Format-List
Get-Content "$env:USERPROFILE\.sct\local_token"
```

حالات سيّئة شائعة:
- ملف غير موجود (حُذف، أو لم يُنشَأ لأنّ الخادم انهار في الإقلاع).
- ملف world-readable (`-rw-r--r--`) بعد `chmod -R 644`.
- ملف مملوك لـ`root` بعد تشغيل واحد بـ`sudo` → المستخدم الحالي لا يقرأه.
- اثنان من SCT على نفس الجهاز يكتبان في نفس `~/.sct/local_token` بقيم مختلفة (الأخير يفوز).

### الحلّ

أعد توليده ببساطة: احذف وأعد تشغيل الخادم:

```bash
rm -f ~/.sct/local_token
chmod 700 ~/.sct
./start.sh           # أو START.bat على Windows
chmod 600 ~/.sct/local_token
cat ~/.sct/local_token   # انسخه إلى Authorization headers في scripts
```

```powershell
Remove-Item "$env:USERPROFILE\.sct\local_token" -Force
.\START.bat
icacls "$env:USERPROFILE\.sct\local_token" /inheritance:r /grant:r "${env:USERNAME}:F"
```

⚠️ **كلّ script سابقة تحتاج القيمة الجديدة** — القديمة لن تعمل من localhost أيضاً.

لو تريد الحفاظ على نفس الـtoken عبر restart (مثلاً في deployment automation):

```bash
cp ~/.sct/local_token ~/.sct/local_token.bak
# أعد التوليد، ثم إن لزم:
cp ~/.sct/local_token.bak ~/.sct/local_token
chmod 600 ~/.sct/local_token
```

---

<a id="3-readyz-503"></a>

## 3. `/readyz` يردّ 503 (فحص الكتابة فشل)

### الأعراض

- `GET /readyz` يردّ:

  ```text
  HTTP/1.1 503 Service Unavailable
  {"status": "not_ready", "error": "cannot write to webapp_jobs/"}
  ```

- `/health` لا يزال يردّ `{"status": "ok"}` (liveness سليم).
- Orchestrators (Kubernetes/Swarm/compose-with-healthcheck) تُعلِّم الـcontainer
  `unhealthy` وقد تعيد تشغيله.
- زحفات جديدة تفشل في البدء.

### التشخيص

`/readyz` (مُضاف في v1.10) يفحص كتابة صغيرة إلى `webapp_jobs/` في كلّ استدعاء.
أيّ من الأعطال التالية يُسقطه إلى 503:

- `webapp_jobs/` غير موجود (cron حذفه، أو لم يُنشَأ في checkout جديد).
- Permission denied (الـcontainer يعمل بمستخدم `sct` لكن host-mounted volume مملوك لـ`root`).
- نظام ملفّات للقراءة فقط (FS فشل، btrfs في `ro` بعد خطأ، bind-mount بـ`:ro`).
- القرص ممتلئ (`ENOSPC`) — انظر [السيناريو 7](#7-disk-full).
- Quota متجاوزة.

تشخيص من الجهاز:

```bash
ls -la ./webapp_jobs/ | head
stat ./webapp_jobs/
touch ./webapp_jobs/.readyz_manual_test && rm ./webapp_jobs/.readyz_manual_test \
  && echo "كتابة OK" || echo "كتابة فاشلة"
df -h ./webapp_jobs/
df -i ./webapp_jobs/
```

```powershell
Get-Item .\webapp_jobs\ | Format-List
Get-Acl .\webapp_jobs\ | Format-List
New-Item -Path .\webapp_jobs\.readyz_manual_test -ItemType File -Force | Out-Null
Remove-Item .\webapp_jobs\.readyz_manual_test
```

### الحلّ

أعد إنشاء المجلّد وأصلح الملكيّة:

```bash
# Bare metal / VM
mkdir -p ./webapp_jobs
chown -R "$(id -u):$(id -g)" ./webapp_jobs
chmod 755 ./webapp_jobs

# Docker — الـimage يعمل بمستخدم sct (غير-root) منذ v1.09
docker compose down
sudo chown -R 1000:1000 ./webapp_jobs   # uid:gid للمستخدم sct
docker compose up -d
```

```powershell
New-Item -ItemType Directory -Path .\webapp_jobs -Force | Out-Null
icacls .\webapp_jobs /grant "${env:USERNAME}:(OI)(CI)F"
```

أعد فحص `/readyz`:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/readyz
# متوقّع: 200
```

---

<a id="4-port-busy"></a>

## 4. المنفذ 8000 مشغول

### الأعراض

- `START.bat` / `START.ps1` / `./start.sh` يخرج فوراً بـ:

  ```text
  [ERROR] Address already in use: 127.0.0.1:8000
  ```
  
- المتصفّح يفتح `http://127.0.0.1:8000` فيرى نسخة قديمة عالقة، أو تطبيقاً آخر، أو
  `Connection refused`.

### التشخيص

اعرف من يحجز المنفذ. `STOP.bat` على Windows يفعل هذا تلقائياً عبر
`netstat -ano | findstr :8000` ثمّ `taskkill /PID <pid> /F`. الأوامر اليدويّة:

```bash
# Linux / macOS
lsof -iTCP:8000 -sTCP:LISTEN -P -n
# أو
ss -lptn 'sport = :8000'
```

```powershell
netstat -ano | Select-String ":8000\s.*LISTENING"
Get-NetTCPConnection -LocalPort 8000 -State Listen |
  Select-Object LocalAddress, LocalPort, OwningProcess
```

### الحلّ

```bash
kill $(lsof -t -iTCP:8000 -sTCP:LISTEN)
# إن لم تستجب:
kill -9 $(lsof -t -iTCP:8000 -sTCP:LISTEN)
```

```powershell
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess -Force
```

أو شغّل SCT على منفذ آخر:

```bash
python webapp/run.py --port 8765
```

```powershell
python webapp\run.py --port 8765
```

---

<a id="5-phase2"></a>

## 5. زرّ Phase 2 لا يعمل

### الأعراض

- بعد انتهاء Phase 1، الـpanel الكهرماني **«🔍 روابط مكتشفة لم تُفحَص»** ظاهر لكنّ
  زرّ **«🔁 شغّل Phase 2»** يفشل بصمت أو يردّ non-2xx من `POST /api/jobs/<id>/phase2`.
- ردود API المحتملة (كلّها 400):

  ```json
  {"error": "deferred_csv_missing"}
  {"error": "active_job_running"}
  {"error": "config_missing"}
  {"error": "job_not_found"}
  ```

### التشخيص

`start_phase2(job_id)` في `webapp/job_runner.py` يتحقّق من 4 شروط مسبقة:

| السبب | المعنى | المكان |
|---|---|---|
| `job_not_found` | `webapp_jobs/<id>/` غير موجود | حُذفت المهمّة، أو المعرّف خاطئ |
| `config_missing` | `webapp_jobs/<id>/config.yaml` غير مكتوب | Phase 1 لم تصل إلى export بعد |
| `deferred_csv_missing` | `output/.../csv/deferred_urls.csv` غير موجود | إمّا لا روابط مؤجَّلة (Phase 2 لا فائدة منها)، أو بحث v1.09 فشل |
| `active_job_running` | مهمّة أخرى قيد التشغيل | guard في v1.09 (B12) — placeholder يُدخَل لحظة دخول `start_phase2` |

تحقّق:

```bash
ls -la webapp_jobs/<job_id>/output/*/csv/deferred_urls.csv 2>/dev/null
ls -la webapp_jobs/<job_id>/config.yaml
curl -s -H "Authorization: Bearer $(cat ~/.sct/local_token)" \
  http://127.0.0.1:8000/api/jobs | python -m json.tool | grep -E '"status"|"id"'
```

### الحلّ بحسب السبب

- **`deferred_csv_missing` ولم يُؤجَّل شيء** — لا يوجد Phase 2 لتشغيلها. هذا طبيعيّ
  لمواقع صغيرة. الـUI يُظهر فقط الأنواع غير الصفريّة؛ لو الكلّ صفر، لا تضغط الزرّ.
- **`deferred_csv_missing` لكن CSV موجود فعلاً** — افحص `crawl.timestamped_folder`
  في config المهمّة. حرّك CSV لأعلى مستوى إن لزم:
  `mv webapp_jobs/<id>/output/<ts>/csv/deferred_urls.csv webapp_jobs/<id>/output/csv/`
- **`active_job_running`** — انظر الـPIDs الجارية:
  ```bash
  ps -ef | grep -E 'main\.py.*--phase2|main\.py.*--mode' | grep -v grep
  ```
  أوقف العمليّة العالقة من الواجهة أو اقتل الـPID.
- **`config_missing`** — Phase 1 لم تنتهِ نظيفاً. افحص لوغ المهمّة. أعد التشغيل
  كـPhase 1 جديدة.

---

<a id="6-db-locked"></a>

## 6. `database is locked` بعد إصلاح `busy_timeout` في v1.10

### الأعراض

- لوغ الزحف يحوي:

  ```text
  sqlite3.OperationalError: database is locked
  ```

- v1.10 (C1.M-4) أضاف `PRAGMA busy_timeout = 5000` على كلّ connection. هذا يحلّ
  أغلب التنازع. لو الخطأ يظهر بعد الترقية، فهو في حالة من الحالات النادرة أدناه.

### التشخيص

`busy_timeout` بـ5 ثوانٍ يعمل داخل كلّ نسخة مكتوبة — لكن SQLite يُظهر «database is
locked» حين:

- **transaction كتابة واحدة تتجاوز 5 ثوانٍ** — الأكثر شيوعاً: `VACUUM`، أو
  `INSERT … SELECT …` كبير، أو `UPDATE` مع index على جدول multi-GB.
- **عمليّة خارجيّة تحتجز DB حصرياً** — sqlite3 shell بـ`BEGIN EXCLUSIVE`، أو DB
  Browser for SQLite مع تعديل غير محفوظ.
- **`sct.db` على network filesystem** (NFS, SMB, cloud-mount) — SQLite locking
  غير موثوق هناك، لا حلّ من جانب البرنامج.
- **عمليّتا SCT على نفس DB** — foot-gun عند نسخ `webapp_jobs/<id>/` أثناء عمل مهمّة.

تشخيص:

```bash
lsof webapp_jobs/<job_id>/output/state/sct.db
df -T webapp_jobs/<job_id>/output/state/sct.db
sqlite3 webapp_jobs/<job_id>/output/state/sct.db "PRAGMA journal_mode;"
# expected: wal
```

```powershell
# يحتاج Sysinternals handle.exe
handle.exe webapp_jobs\<job_id>\output\state\sct.db
```

### الحلّ

- **VACUUM طويل** — لا تشغّله أثناء الزحف. أوقف، شغّل VACUUM، استأنف.
- **DB tool خارجي يحجز** — أغلق DB Browser/sqlite3 shell.
- **Network FS** — انقل `webapp_jobs/` إلى قرص محلّي. لا حلّ برمجيّ.
- **عمليّتان** — حدّدهما عبر `lsof`/`handle.exe` وأوقف الإضافيّة.
- **كاتب عالق** — كحلّ أخير:
  ```bash
  cd webapp_jobs/<job_id>/output/state
  ls -la sct.db*
  # إن وُجدت sct.db-wal و sct.db-shm:
  sqlite3 sct.db "PRAGMA wal_checkpoint(TRUNCATE);"
  ```

- **DB تالف فعلاً**:
  ```bash
  sqlite3 sct.db "PRAGMA integrity_check;"
  # إن لم يكن "ok":
  sqlite3 sct.db ".dump" > dump.sql
  mv sct.db sct.db.broken
  sqlite3 sct.db < dump.sql
  ```

---

<a id="7-disk-full"></a>

## 7. القرص ممتلئ — تنظيف `webapp_jobs/` بأمان

### الأعراض

- زحفات جديدة تفشل بـ`[Errno 28] No space left on device`.
- `/readyz` يردّ 503 — انظر [السيناريو 3](#3-readyz-503).
- جزء كبير من القرص يحتجزه `webapp_jobs/<job_id>/output/*.csv` و SQLite per-job.

### التشخيص

كلّ مهمّة تحت `webapp_jobs/<job_id>/` تحوي اللوغ + DB + كل CSV/JSON exports + report
(لو وُلِّد) + XML sitemap. installs طويلة الأمد تتراكم لعشرات GB.

```bash
du -sh webapp_jobs/* 2>/dev/null | sort -rh | head -20
du -sh webapp_jobs/
df -h .
df -i .   # inodes — مواقع كثيرة تنفد inodes قبل المساحة
```

```powershell
Get-ChildItem .\webapp_jobs -Directory |
  Select-Object Name, @{Name='SizeMB';Expression={
    [math]::Round((Get-ChildItem $_.FullName -Recurse -ErrorAction SilentlyContinue |
                   Measure-Object -Property Length -Sum).Sum / 1MB, 1)
  }} | Sort-Object SizeMB -Descending | Select-Object -First 20
```

### الحلّ

**الأفضل — استعمل endpoint الـAPI** (v1.01+). يحترم الحماية: المهمّة النشطة لا
تُحذف، المعرّفات غير الصالحة تُرفض، المسارات تُحلّ ضمن `webapp_jobs/`.

```bash
# احذف كلّ المهام ما عدا النشطة
curl -X POST -H "Authorization: Bearer $(cat ~/.sct/local_token)" \
  http://127.0.0.1:8000/api/jobs/delete-all

# أو احذف مهمّة بعينها
curl -X POST -H "Authorization: Bearer $(cat ~/.sct/local_token)" \
  http://127.0.0.1:8000/api/jobs/20260620_141500_abc123/delete
```

```powershell
$token = Get-Content "$env:USERPROFILE\.sct\local_token"
Invoke-RestMethod -Method Post -Headers @{ Authorization = "Bearer $token" } `
  http://127.0.0.1:8000/api/jobs/delete-all
```

الـUI لها أزرار **🧹 احذف الكل (ما عدا النشطة)** و **🗑️ احذف** لكلّ صف.

**fallback — حذف من shell.** فقط حين الخادم لا يُستجاب (مثلاً ممتلئ لدرجة لا يُقلع).
**لا تحذف** مجلّد مهمّة subprocess لا يزال يكتب فيها — ستُتلِف SQLite WAL.

```bash
./STOP.bat 2>/dev/null || pkill -f "webapp/run.py"
lsof +D ./webapp_jobs 2>/dev/null   # تأكّد لا شيء يكتب
find ./webapp_jobs -mindepth 1 -maxdepth 1 -type d -mtime +30 -print -exec rm -rf {} +
# أو
rm -rf ./webapp_jobs/*
```

---

<a id="8-csp"></a>

## 8. اعتراض CSP / security-headers من scanner خارجي

### الأعراض

scanner أمني (Nessus, Qualys, ZAP, Burp, Mozilla Observatory) يُعلِم SCT بفقدان
أو ضعف في أحد:

- `Content-Security-Policy`
- `Strict-Transport-Security` (HSTS)
- `X-Frame-Options` / `frame-ancestors`
- `Referrer-Policy`
- `Permissions-Policy`

### التشخيص — ما هو SCT وما ليس هو

**SCT ليس تطبيق ويب public-hardened.** إنّه أداة تدقيق محلّيّة لمستخدم واحد، تُشغَّل
على `http://127.0.0.1:8000` للمشغّل نفسه. الكود يقايض hardening للويب العام بـ
ergonomics للمطوّر المحلّي:

- **يستمع على localhost افتراضياً**. token wall (السيناريو 2) يعني أنّه حتّى على
  `0.0.0.0` لا يستطيع مهاجم غير مصادَق تشغيل الـAPI. CSRF Origin guard (v1.09)
  يرفض cross-origin POSTs من المتصفّح. Rate limiting (v1.10) يحمي `/api/start`
  (10/ساعة) و باقي `/api/*` (120/دقيقة).
- **لا يُقدّم HTTPS بنفسه** → لا HSTS. لو ضع SCT خلف reverse proxy للوصول البعيد،
  **الـproxy** هو المكان الصحيح لـHSTS و CSP و TLS pinning.
- **HTML inlines CSS/JS** → CSP بـ`default-src 'self'` يكسر `<script>` blocks في
  `index.html`, `job.html`, `graph.html`, `board.html`. الـgraph view يرسم على
  `<canvas>` مع force-directed simulation inlined.
- **يضع token wall على كلّ state-changing endpoint وكل `/api/*` read**. يُشغّل
  CSRF Origin guard. يُنفّذ rate limits. يُرجع `X-Request-ID` في كلّ response.
  يضع SQL table whitelist. يفحص SSRF عبر `is_safe_remote_url` على كلّ outbound URL
  بما فيها JS-rendering navigations و HEAD redirects.

شكوى scanner عن CSP/HSTS على `http://127.0.0.1:8000` هي **عدم تطابق scanner-مع-تصميم**،
ليست ثغرة — لكن الردّ يعتمد على ما إذا كنت تنشر SCT خلف proxy.

### الحلّ

**لو SCT محلّي فقط على `127.0.0.1`** (الافتراضي):

- اعتبر اعتراض الـscanner خارج النطاق. اقتبس SECURITY.md و هذا القسم. نموذج التهديد
  هو «مشغّل على جهازه الخاص»؛ CSP لا يُقدِّم شيئاً لأنّه لا توجد سطح محتوى من جهة
  ثالثة، والـtoken wall يحمي مسبقاً.
- تأكّد من عمل الحماية الفعليّة:

  ```bash
  curl -i http://127.0.0.1:8000/health
  # expected: X-Request-ID: <12 chars>
  
  curl -i -X POST http://127.0.0.1:8000/api/start
  # expected: HTTP/1.1 401 Unauthorized
  
  curl -i -H "Origin: https://evil.example/" \
    -H "Authorization: Bearer $(cat ~/.sct/local_token)" \
    -X POST http://127.0.0.1:8000/api/jobs/delete-all
  # expected: HTTP/1.1 403 Forbidden  (CSRF origin guard)
  ```

**لو عرّضت SCT خلف reverse proxy** (ليس deployment مدعوم لكن يحدث):

- ضع proxy حقيقي (nginx, Caddy). الـproxy ينهي TLS ويضبط HSTS و CSP المناسب
  للـinlined scripts (عادةً: `default-src 'self'; script-src 'self' 'unsafe-inline';
  style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self';
  frame-ancestors 'none'`).
- أضف `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Permissions-Policy: ()` على الـproxy.
- **لا تُعطّل token wall في SCT** لأنّ proxy يحمي. defense-in-depth هو الفكرة.
- قيِّد proxy على IPs/VPN معيّن — لا تضع SCT على الإنترنت المفتوح.

---

## ملحق: one-liners مفيدة

```bash
# نسخة الخادم الجاري؟
curl -s http://127.0.0.1:8000/health
# (النسخة كذلك في footer الصفحة الرئيسيّة وفي audit.json _meta.version)

# تتبّع لوغ مهمّة بعينها live
tail -F webapp_jobs/<job_id>/job.log

# عدد المهام والمساحة؟
ls webapp_jobs/ | wc -l && du -sh webapp_jobs/

# شغّل suite الاختبارات للتأكّد من install نظيف
python -B -m unittest discover -s tests
# متوقّع: 91/91 pass على v1.13
```

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Get-Content .\webapp_jobs\<job_id>\job.log -Wait -Tail 50
(Get-ChildItem .\webapp_jobs -Directory).Count
python -B -m unittest discover -s tests
```

لأيّ شيء لا يُغطّى هنا، راجع `CHANGELOG.md` لإصدار محدَّد — أغلب السلوكيّات
المرئيّة للمشغّل موثَّقة في release notes الذي أصلحها.
