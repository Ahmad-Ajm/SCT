"""
webapp/job_runner.py
=====================
إدارة مهام الزحف عبر عمليات فرعية (subprocess) معزولة.

لماذا subprocess؟
- عزل تام: انهيار/تعليق الزحف لا يُسقط خادم الويب.
- "إيقاف" موثوق عبر إنهاء العملية.
- يعيد استخدام نقطة التشغيل الرسمية (main.py) دون تكرار منطق.

التقدّم اللحظي: الزاحف يكتب progress.json (عبر متغيّر البيئة SCT_PROGRESS_FILE).
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime

log = logging.getLogger("sct.job_runner")
from pathlib import Path
from typing import Any, Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = ROOT / "webapp_jobs"
BASE_CONFIG = ROOT / "config.yaml"
MAIN_PY = ROOT / "main.py"

# صيغة معرّف المهمة: YYYYMMDD_HHMMSS_<6 hex> — للتحقّق ومنع traversal
_JOB_ID_RE = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{6}$")

# مستوى السجل يظهر دائماً محاطاً بـ "| LEVEL |" في كلا المنسّقين (console/file)،
# فنعدّه حسب المستوى الفعلي بدل البحث عن الكلمة في نص الرسالة (يتجنّب التضخيم).
_LOG_LEVEL_RE = re.compile(r"\|\s*(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s*\|")


def _valid_job_id(job_id: str) -> bool:
    return bool(_JOB_ID_RE.match(str(job_id or "")))


# v1.13.16 (F61): قائمة المفاتيح الحسّاسة التي يجب ألا تظهر في أيّ ملفّ على القرص.
# تُمرَّر للعمليّة الفرعيّة عبر متغيّرات بيئة فقط (انظر _secret_env في JobRunner).
_SENSITIVE_KEYS = frozenset({
    "credentials_file", "api_key", "token", "secret",
    "client_secret", "service_account_key",
})


def _strip_sensitive_in_place(node: Any) -> None:
    """يمشي على شجرة dict/list ويحذف أيّ مفتاح يطابق _SENSITIVE_KEYS.

    استخدام: تعقيم config قبل الكتابة على القرص لمنع تسريب مسارات اعتمادات/مفاتيح
    عبر تنزيل config.yaml من الواجهة.
    """
    if isinstance(node, dict):
        for k in list(node.keys()):
            if k in _SENSITIVE_KEYS:
                del node[k]
            else:
                _strip_sensitive_in_place(node[k])
    elif isinstance(node, list):
        for item in node:
            _strip_sensitive_in_place(item)


# v1.13.16 (F45): كتابة JSON ذرّيّة — write-then-rename بدل json.dump مباشر،
# كي لا يبقى ملفّ نصف-مكتوب إن انهارت العمليّة في المنتصف. os.replace ذرّيّ على
# نفس نظام الملفّات (Windows و POSIX) ويستبدل الملفّ الموجود بأمان.
def _atomic_write_json(path: Path, data: Any, *, ensure_ascii: bool = False,
                       indent: int | None = None) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)
    os.replace(tmp, path)


class JobRunner:
    """مدير مهام زحف محلي (مهمة واحدة نشطة في كل وقت يُنصَح بها للاستخدام المحلي)."""

    def __init__(self) -> None:
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        self._procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()
        self._secret_env: dict[str, str] = {}  # أسرار تُمرَّر للعملية الفرعية فقط

    # ------------------------------------------------------------------
    def _load_base_config(self) -> dict[str, Any]:
        if BASE_CONFIG.exists():
            with open(BASE_CONFIG, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    # حدود السرعة لحماية المواقع من الضغط
    MIN_DELAY_SECONDS = 0.1   # حدّ أدنى للتأخير بين الطلبات (لا يمكن النزول تحته)
    MAX_CONCURRENT = 20       # حدّ أقصى للطلبات المتزامنة

    # مفاتيح الاستخراج المتاحة (تُعرض كمجموعات في الواجهة)
    EXTRACTION_KEYS = [
        "meta", "headings", "content", "canonical",
        "links", "images",
        "og", "hreflang", "schema", "pagination",
        "headers", "mixed_content", "resources",
    ]

    def _build_job_config(self, job_dir: Path, overrides: dict[str, Any]) -> Path:
        self._secret_env = {}   # تُعاد تعبئتها أدناه ثم تُقرأ في start()
        cfg = self._load_base_config()
        cfg.setdefault("site", {})
        cfg.setdefault("crawl", {})
        cfg.setdefault("output", {})
        cfg.setdefault("state", {})
        cfg.setdefault("report", {})
        cfg.setdefault("extraction", {})
        cfg.setdefault("logging", {})
        cfg.setdefault("integrations", {})
        cfg.setdefault("analysis", {})
        cfg.setdefault("custom_extraction", {})

        url = overrides.get("url")
        if url:
            # v1.13.7: defensive normalization — أحياناً المستخدم يلصق "example.com"
            # بلا scheme أو يبدأ بـ"www." فقط. browser form يرفض ذلك مع type="url"،
            # لكنّ API calls خارجيّة أو لصق سريع قد يمرّر القيمة بلا تعديل.
            from urllib.parse import urlparse
            url = url.strip()
            if not url.startswith(("http://", "https://")):
                url = "https://" + url.lstrip("/")
            cfg["site"]["start_url"] = url
            cfg["site"]["domain"] = urlparse(url).netloc

        if overrides.get("max_pages") is not None:
            cfg["crawl"]["max_pages"] = int(overrides["max_pages"])
        if overrides.get("max_depth") is not None:
            cfg["crawl"]["max_depth"] = int(overrides["max_depth"])
        # حدود السرعة: نفرض حدّاً أدنى للتأخير وحدّاً أقصى للتزامن حماية للموقع
        if overrides.get("delay_seconds") is not None:
            cfg["crawl"]["delay_seconds"] = max(self.MIN_DELAY_SECONDS, float(overrides["delay_seconds"]))
        if overrides.get("concurrent_requests") is not None:
            cfg["crawl"]["concurrent_requests"] = max(
                1, min(self.MAX_CONCURRENT, int(overrides["concurrent_requests"]))
            )
        if overrides.get("respect_robots") is not None:
            cfg["crawl"]["respect_robots"] = bool(overrides["respect_robots"])
        if overrides.get("seed_strategy"):
            strat = str(overrides["seed_strategy"]).lower()
            if strat in ("homepage", "sitemap", "hybrid"):
                cfg["crawl"]["seed_strategy"] = strat

        # v1.05: انتحال User-Agent (preset أو مخصّص) — يكشف مشاكل Cloudflare/WAF
        # الخاصّة بـbots مثل Googlebot 403 challenges. الافتراضي يبقى كما هو في
        # http_client (SEOCrawlerBot/1.0) عند عدم اختيار شيء.
        ua_preset = str(overrides.get("ua_preset", "") or "").lower()
        ua_custom = str(overrides.get("ua_custom", "") or "").strip()
        ua_map = {
            "googlebot": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
            "googlebot-mobile": (
                "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.6099.118 Mobile Safari/537.36 "
                "(compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
            ),
            "bingbot": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
        }
        if ua_preset == "custom" and ua_custom:
            cfg["crawl"]["user_agent"] = ua_custom
        elif ua_preset in ua_map:
            cfg["crawl"]["user_agent"] = ua_map[ua_preset]

        # قالب منصّة جاهز (IMP-11 + v1.13.5 WordPress): يُطبَّق فقط لقيمة معروفة
        preset = str(overrides.get("platform_preset", "") or "").strip().lower()
        if preset in ("zid", "salla", "shopify", "woocommerce", "wordpress"):
            cfg["site"]["platform_preset"] = preset
        # توليد sitemap.xml (IMP-5)
        if overrides.get("generate_sitemap") is not None:
            cfg["output"]["generate_sitemap"] = bool(overrides["generate_sitemap"])
        # تحكّم تكيّفي بالسرعة (IMP-10)
        if overrides.get("adaptive_throttle") is not None:
            cfg["crawl"].setdefault("adaptive_throttle", {})
            cfg["crawl"]["adaptive_throttle"]["enabled"] = bool(overrides["adaptive_throttle"])

        # === اختيار ما يُجمَع (extraction) ===
        # إن مُرّرت قائمة extraction نُفعّل المختار فقط ونعطّل الباقي.
        selected = overrides.get("extraction")
        if selected is not None:
            selected_set = set(selected)
            for key in self.EXTRACTION_KEYS:
                cfg["extraction"][f"extract_{key}"] = key in selected_set

        # فحص حالة موارد الصفحة (مكلف) — مطفأ افتراضياً
        if overrides.get("check_resource_status") is not None:
            cfg["extraction"]["check_resource_status"] = bool(overrides["check_resource_status"])

        # v1.13.18: تصيير JS (Playwright/Chromium) — يرى الموقع بعد تنفيذ JS.
        # بطيء 5-10× لكنّه لازم للـSPA/AJAX. مطفأ افتراضياً.
        if overrides.get("js_render") is not None:
            cfg.setdefault("javascript", {})
            cfg["javascript"]["enabled"] = bool(overrides["js_render"])
        if overrides.get("js_max_pages") is not None:
            cfg.setdefault("javascript", {})
            cfg["javascript"]["max_pages"] = max(0, int(overrides["js_max_pages"] or 0))

        # v1.13.18: فحص الوصولية (axe-core) — يعمل داخل المتصفّح المُصيَّر.
        # يتطلّب تفعيل javascript. مطفأ افتراضياً.
        if overrides.get("accessibility_check") is not None:
            cfg.setdefault("accessibility", {})
            cfg["accessibility"]["enabled"] = bool(overrides["accessibility_check"])
            # لتشغيل axe بدون ملفّ محلي: نسمح بجلبه من CDN (jsdelivr).
            if cfg["accessibility"]["enabled"]:
                cfg["accessibility"].setdefault("allow_cdn", True)
                # تفعيل الوصولية يستلزم تفعيل JS render — نضبطه صراحةً.
                cfg.setdefault("javascript", {})["enabled"] = True
        if overrides.get("accessibility_max_pages") is not None:
            cfg.setdefault("accessibility", {})
            cfg["accessibility"]["max_pages"] = max(
                0, int(overrides["accessibility_max_pages"] or 0))

        # تسريع فحص الروابط الخارجية على المواقع الضخمة
        cfg.setdefault("external_check", {})
        if overrides.get("ext_sample_per_host") is not None:
            cfg["external_check"]["sample_per_host"] = bool(overrides["ext_sample_per_host"])
        if overrides.get("ext_max_urls"):
            cfg["external_check"]["max_urls"] = int(overrides["ext_max_urls"])

        # مخرجات/حالة محددة للمهمة
        cfg["output"]["output_dir"] = str(job_dir / "output")
        cfg["output"]["timestamped_folder"] = False
        formats = overrides.get("formats") or ["csv", "json", "html", "pdf"]
        cfg["output"]["formats"] = formats
        cfg["state"]["state_dir"] = str(job_dir / "state")

        # === لوغ مستقل وواضح لكل مهمة ===
        cfg["logging"]["log_dir"] = str(job_dir / "logs")
        cfg["logging"]["level"] = overrides.get("log_level", "INFO")
        cfg["logging"]["console_output"] = True
        cfg["logging"]["file_output"] = True

        # خيارات التقرير (PDF/HTML)
        audience = str(overrides.get("audience", "expert") or "expert").lower()
        if audience not in ("client", "expert", "both"):
            audience = "expert"
        cfg["report"].update({
            "language": overrides.get("language", "ar"),
            "audience": audience,
            "client_name": overrides.get("client_name", ""),
            "logo_url": overrides.get("logo_url", ""),
            "sections": overrides.get("sections")
                or ["cover", "summary", "issues", "problem_pages", "redirects", "schema"],
            "severity_filter": overrides.get("severity_filter")
                or ["🔴 Critical", "🟠 High", "🟡 Medium", "🟢 Low"],
            "max_rows": int(overrides.get("max_rows", 100)),
        })

        # === التكاملات (تُدمج فوق الأساسي؛ تُكتب محلياً في إعداد المهمة فقط) ===
        for name, sub in (overrides.get("integrations") or {}).items():
            cfg["integrations"].setdefault(name, {})
            cfg["integrations"][name].update(sub)
        # لا نكتب الأسرار (PageSpeed API key) في ملف إعداد المهمة على القرص؛
        # نمرّرها للعملية الفرعية عبر متغيّر بيئة (يقرأها main.py كـ fallback).
        ps = cfg.get("integrations", {}).get("pagespeed", {})
        if ps.get("api_key"):
            self._secret_env["PAGESPEED_API_KEY"] = str(ps["api_key"])
            ps["api_key"] = ""
        # مفتاح الذكاء الاصطناعي: لا يُكتب على القرص؛ يُمرَّر للعملية عبر AI_API_KEY
        ai = cfg.get("integrations", {}).get("ai", {})
        if ai.get("api_key"):
            self._secret_env["AI_API_KEY"] = str(ai["api_key"])
            ai["api_key"] = ""
        # v1.04: مفتاح Ahrefs/Majestic يُمرَّر عبر BACKLINKS_API_KEY (نفس فلسفة PageSpeed)
        bl = cfg.get("integrations", {}).get("backlinks", {})
        if bl.get("api_key"):
            self._secret_env["BACKLINKS_API_KEY"] = str(bl["api_key"])
            bl["api_key"] = ""
        # v1.13.16 (F61): مسارات اعتماد Google (GSC/GA4) — تُلتقَط من الـconfig
        # قبل التعقيم وتُمرَّر للعمليّة الفرعيّة عبر env vars. ملفّ config.yaml على
        # القرص قابل للتنزيل من الواجهة، فلا نسمح ببقاء مسار credentials فيه.
        # ملاحظة: GA4 يدعم GA4_CREDENTIALS_FILE كfallback في integrations_service؛
        # GSC حالياً يقرأ من config فقط — يحتاج تعديل مستهلك منفصل لقراءة env.
        gsc = cfg.get("integrations", {}).get("gsc", {})
        if gsc.get("credentials_file"):
            self._secret_env["GSC_CREDENTIALS_FILE"] = str(gsc["credentials_file"])
        ga4 = cfg.get("integrations", {}).get("ga4", {})
        if ga4.get("credentials_file"):
            self._secret_env["GA4_CREDENTIALS_FILE"] = str(ga4["credentials_file"])

        # === الاستخراج المخصّص ===
        ce = overrides.get("custom_extraction")
        if ce is not None:
            cfg["custom_extraction"]["enabled"] = bool(ce.get("enabled"))
            cfg["custom_extraction"]["rules"] = ce.get("rules", [])

        # === عتبات التحليل ===
        for key, val in (overrides.get("analysis") or {}).items():
            if val is not None:
                cfg["analysis"][key] = val

        # v1.13.16 (F61): تعقيم نهائي للأسرار قبل الكتابة على القرص. ملفّ
        # config.yaml هذا قابل للتنزيل من الواجهة، لذا أيّ مفتاح حسّاس متبقّي
        # (api_key/credentials_file/...) قد يُسرَّب. الأسرار تُمرَّر للعمليّة
        # الفرعيّة عبر _secret_env فقط، وهنا نطبّق walk عميق على dict-tree كاملاً
        # لإزالة أيّ مفتاح من SENSITIVE حتى لو أُضيف لاحقاً بفرع لم نتوقّعه.
        _strip_sensitive_in_place(cfg)
        cfg_path = job_dir / "config.yaml"
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True)
        return cfg_path

    # ------------------------------------------------------------------
    def start(self, overrides: dict[str, Any]) -> str:
        job_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
        job_dir = JOBS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        mode = overrides.get("mode", "audit")
        cfg_path = self._build_job_config(job_dir, overrides)
        progress_file = job_dir / "progress.json"

        meta = {
            "job_id": job_id,
            "mode": mode,
            "url": overrides.get("url", ""),
            "started_at": datetime.now().isoformat(),
            "status": "running",
            "config": str(cfg_path),
        }
        self._write_meta(job_dir, meta)
        self._write_progress(progress_file, {"status": "starting", "pages_crawled": 0})

        env = dict(os.environ)
        env["SCT_PROGRESS_FILE"] = str(progress_file)
        env["PYTHONIOENCODING"] = "utf-8"
        # عملية الزحف خلفية وغير تفاعلية: امنع أي محاولة لفتح متصفح موافقة OAuth
        # (كانت قد تعلّق العملية للأبد). التفويض يتم مسبقاً عبر الواجهة.
        env["SCT_NONINTERACTIVE"] = "1"
        # أسرار التكاملات تُمرَّر عبر البيئة فقط (ليست في ملف الإعداد على القرص)
        env.update(self._secret_env)

        # v1.09-B4: حماية من argv injection — `mode` و`url` يأتيان من الـform.
        # URL يبدأ بـ`--` يصبح CLI flag على main.py؛ mode غير قياسي يفسد الإخراج.
        if mode not in ("audit", "competitor", "compare"):
            mode = "audit"
        args = [sys.executable, str(MAIN_PY), "--config", str(cfg_path), "--mode", mode]
        raw_url = overrides.get("url") or ""
        if raw_url:
            from urllib.parse import urlparse
            try:
                _scheme = (urlparse(raw_url).scheme or "").lower()
            except (ValueError, TypeError):
                _scheme = ""
            if _scheme in ("http", "https") and not raw_url.startswith("-"):
                # نستعمل صيغة `--url=value` (argv عنصر واحد) — تمنع injection حتّى
                # لو وصلت قيمة غير متوقّعة كـ`--malicious` بحيلة أخرى لاحقاً.
                args.append(f"--url={raw_url}")
            else:
                log.warning(f"تجاهل url غير صالح أو يبدأ بشرطة: {raw_url!r}")
        if overrides.get("no_resume"):
            args.append("--no-resume")
        if overrides.get("skip_external"):
            args.append("--skip-external")
        if overrides.get("integrations_only"):
            args.append("--integrations-only")
        if overrides.get("phase2"):
            args.append("--phase2")

        # v1.08: في Phase 2 نُلحق بالـrun.log بدل الكتابة من جديد، كي يحتفظ المستخدم
        # بسجلّ Phase 1 الذي تابعه. أيضاً نستخدم اسم تقدّم مختلف لتجنّب الالتباس.
        log_file = open(job_dir / "run.log", "a" if overrides.get("phase2") else "w",
                        encoding="utf-8")
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        proc = subprocess.Popen(
            args, cwd=str(ROOT), env=env,
            stdout=log_file, stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        # v1.13.16 (F46): أغلق الـhandle في الـparent بعد Popen — الـsubprocess
        # ورث fd مضاعفاً ويكتب عبره. ترك الـhandle مفتوحاً هنا يسبّب على Windows
        # «file in use» عند محاولة قراءة/حذف run.log لاحقاً من الواجهة.
        log_file.close()
        with self._lock:
            self._procs[job_id] = proc

        threading.Thread(target=self._watch, args=(job_id, job_dir, proc), daemon=True).start()
        return job_id

    def start_phase2(self, job_id: str) -> dict[str, Any]:
        """v1.08: يبدأ Phase 2 لمهمّة موجودة (يستعمل deferred_urls.csv كبذور).

        المسبّقات: المهمّة منتهية + deferred_urls.csv موجود + لا توجد مهمّة أخرى نشطة.
        النتيجة: subprocess جديد ينضمّ إلى نفس job_dir (لا job_id جديد).
        """
        if not _valid_job_id(job_id):
            return {"ok": False, "error": "invalid job_id"}
        # v1.09-B9: نمسك الـlock طوال عمليّة الفحص-والإطلاق. سابقاً كان يُحرَّر
        # بعد الفحص قبل subprocess.Popen ⇒ طلبان متوازيان يمرّان كلاهما.
        with self._lock:
            self._sweep_finished()
            if self._procs:
                return {"ok": False, "error": "active_job",
                        "active_job": next(iter(self._procs), None)}
            # نضع placeholder سريع لمنع طلب موازٍ ثانٍ من المرور (سيُستبدل ببروسس
            # حقيقي بعد قليل أسفل).
            self._procs[job_id] = None  # type: ignore[assignment]
        # v1.09-B9: إن فشلنا في أيّ pre-check، نُحرّر الـplaceholder من _procs
        # كي لا يبقى job_id «نشطاً» وهميّاً يمنع المهام المستقبليّة.
        def _cleanup_and_return(err: str) -> dict[str, Any]:
            with self._lock:
                self._procs.pop(job_id, None)
            return {"ok": False, "error": err}

        job_dir = JOBS_DIR / job_id
        if not job_dir.exists():
            return _cleanup_and_return("job_not_found")
        cfg_path = job_dir / "config.yaml"
        if not cfg_path.exists():
            return _cleanup_and_return("config_missing")
        # تحقّق من deferred_urls.csv قبل الإطلاق (يوفّر فشلاً سريعاً وواضحاً)
        deferred_csv = job_dir / "output" / "csv" / "deferred_urls.csv"
        if not deferred_csv.exists():
            return _cleanup_and_return("no_deferred_urls")

        meta = self._read_meta(job_dir)
        meta["status"] = "running"
        meta["phase2_started_at"] = datetime.now().isoformat()
        self._write_meta(job_dir, meta)
        progress_file = job_dir / "progress.json"
        self._write_progress(progress_file, {"status": "starting_phase2", "pages_crawled": 0})

        env = dict(os.environ)
        env["SCT_PROGRESS_FILE"] = str(progress_file)
        env["PYTHONIOENCODING"] = "utf-8"
        env["SCT_NONINTERACTIVE"] = "1"
        env.update(self._secret_env)

        args = [
            sys.executable, str(MAIN_PY),
            "--config", str(cfg_path),
            "--mode", meta.get("mode", "audit"),
            "--phase2",
        ]
        if meta.get("url"):
            args += ["--url", meta["url"]]

        log_file = open(job_dir / "run.log", "a", encoding="utf-8")
        log_file.write("\n\n========= PHASE 2 STARTED =========\n")
        log_file.flush()
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        proc = subprocess.Popen(
            args, cwd=str(ROOT), env=env,
            stdout=log_file, stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        # v1.13.16 (F46): إغلاق الـhandle في الـparent — انظر الشرح في start().
        log_file.close()
        with self._lock:
            self._procs[job_id] = proc
        threading.Thread(target=self._watch, args=(job_id, job_dir, proc), daemon=True).start()
        return {"ok": True, "job_id": job_id, "phase": 2}

    # حالات الانتهاء التي يكتبها المحرّك في progress.json
    _FINAL_STATUSES = {"complete", "partial", "partial_max_pages", "stopped"}

    def _watch(self, job_id: str, job_dir: Path, proc: subprocess.Popen) -> None:
        rc = proc.wait()
        meta = self._read_meta(job_dir)
        # v1.13.20: تحصين إضافي — لو أيّ read أعاد dict بلا job_id (لن يحصل
        # الآن بعد self-heal في _read_meta لكن دفاع في العمق)، نضبطه هنا كي
        # لا يُكتب job.json نهائيّاً بدون هذا الحقل حتّى لو خرب شيء لاحقاً.
        meta.setdefault("job_id", job_id)
        final = self.progress(job_id).get("status")
        if meta.get("status") == "stopped":
            pass  # أوقفها المستخدم عبر الواجهة — نُبقيها
        elif rc != 0 and final not in self._FINAL_STATUSES:
            meta["status"] = "failed"
        elif final in self._FINAL_STATUSES:
            meta["status"] = final  # complete / partial / partial_max_pages / stopped
        else:
            meta["status"] = "complete" if rc == 0 else "failed"
        meta["return_code"] = rc
        meta["ended_at"] = datetime.now().isoformat()
        meta["result"] = self._discover_result(job_dir, meta.get("mode", "audit"))
        meta["diagnostics"] = self._summarize_run_log(job_dir / "run.log")
        # v1.13.11 (F5): مزامنة progress.json مع الحالة النهائية كي لا تظهر
        # شارة "فشل" مع شريط "جار التحليل..." في الواجهة (race condition سابق:
        # meta.status="failed" وprogress.status="analyzing" تتعايشان دون مزامنة).
        # نقرأ الموجود ونحدّث حقل status فقط — العدّادات والمراحل تُحفَظ كما هي.
        progress_file = job_dir / "progress.json"
        try:
            cur = self.progress(job_id) or {}
            cur["status"] = meta["status"]
            self._write_progress(progress_file, cur)
        except OSError:
            log.exception("Failed to sync final status to progress.json for %s", job_id)
        self._write_meta(job_dir, meta)
        with self._lock:
            self._procs.pop(job_id, None)

    def stop(self, job_id: str, grace_seconds: float = 60.0) -> bool:
        """يطلب توقّفاً لطيفاً ويعود فوراً. _watch يلتقط الخروج الفعليّ.
        thread جانبيّ يُصعّد إلى terminate/kill إن لم تستجب العملية
        خلال grace_seconds.

        v1.13.15: تحوّل من blocking إلى async + grace رُفع من 8 إلى 60 ثانية
        ليُتاح للـsubprocess إكمال crawl + analysis + export الجزئيّ.
        الـHTTP request يعود في <100ms — الواجهة تستطلع حتى الحالة النهائية.

        v1.13.21 (Fix 1 — race condition): send_signal() الآن داخل الـlock نفسه
        الذي يحمي lookup الـproc. سابقاً كان الـlock يُحرَّر بعد lookup ثمّ يُرسَل
        الإشارة خارجه — _watch كان يستطيع سحب الـproc من _procs بين الخطوتين،
        فتُرسَل الإشارة إلى proc منتهٍ (أو تفشل بصمت). النتيجة: UI يرى "stopped"
        بينما العمليّة ما زالت حيّة. الآن lookup + write meta + send_signal
        كلّها ذرّيّة."""
        if not _valid_job_id(job_id):
            return False
        with self._lock:
            proc = self._procs.get(job_id)
            if not proc:
                # v1.13.21 (Defensive 1): لا توجد عمليّة في السجلّ. هذا طبيعيّ إن
                # كانت العمليّة انتهت للتوّ، لكنّه قد يكشف عن orphan (subprocess
                # ما زال يعمل والـwatch أزاله بلا إنهاء). لا يمكننا إرسال إشارة
                # بلا مقبض، لكن نسجّل بوضوح كي يظهر في اللوغ إن حصلت الحالة.
                log.warning("stop(%s): proc not in registry — either already "
                            "finished or orphaned", job_id)
                return False
            # B1: اكتب stopped قبل الإشارة — يلغي race مع _watch تماماً.
            try:
                meta = self._read_meta(JOBS_DIR / job_id)
                meta["status"] = "stopped"
                self._write_meta(JOBS_DIR / job_id, meta)
            except OSError:
                log.exception("stop(%s): pre-signal meta write failed", job_id)
            # v1.13.21 (Fix 1): send_signal داخل الـlock — يضمن أنّ الـproc ما زال
            # في _procs ولم يُزَل من _watch بين lookup والإرسال.
            try:
                if os.name == "nt":
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    proc.send_signal(signal.SIGINT)
            except (ProcessLookupError, OSError) as e:
                # meta.status="stopped" مكتوبة بالفعل، فنُبقي النتيجة True كي
                # لا يعتبر الـUI أنّ الإيقاف فشل. الـescalation ستُنهي العمليّة
                # عبر terminate/kill إن كانت ما زالت حيّة.
                log.warning("stop(%s): send_signal failed: %s — proceeding to "
                            "escalation", job_id, e)
        # spawn background watcher للتصعيد إن لزم — لا نحجز الـrequest.
        threading.Thread(
            target=self._escalate_after_grace,
            args=(proc, grace_seconds, job_id),
            daemon=True,
        ).start()
        return True

    @staticmethod
    def _escalate_after_grace(proc: subprocess.Popen, grace_seconds: float,
                              job_id: str) -> None:
        """ينتظر الـsubprocess grace_seconds، ثم terminate إن لم يستجب."""
        try:
            proc.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            log.warning("stop(%s): grace expired — escalating to terminate", job_id)
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    proc.kill()
                except OSError:
                    pass

    def force_kill(self, job_id: str) -> bool:
        """قتل فوري بلا مهلة (للحلقات الطويلة العالقة في طرف ثالث مثل PageSpeed).

        v1.13.21 (Fix 2): lookup + write meta + kill داخل نفس الـlock — نفس
        نمط stop() لإلغاء race مع _watch الذي قد يسحب الـproc بين lookup و kill.
        """
        if not _valid_job_id(job_id):
            return False
        with self._lock:
            proc = self._procs.get(job_id)
            if not proc:
                log.warning("force_kill(%s): proc not in registry — either "
                            "already finished or orphaned", job_id)
                return False
            # اكتب stopped قبل القتل لتجنّب race مع _watch.
            try:
                meta = self._read_meta(JOBS_DIR / job_id)
                meta["status"] = "stopped"
                self._write_meta(JOBS_DIR / job_id, meta)
            except OSError:
                log.exception("force_kill(%s): pre-kill meta write failed", job_id)
            try:
                proc.kill()
            except OSError as e:
                log.warning("force_kill(%s): proc.kill failed: %s", job_id, e)
        return True

    # ------------------------------------------------------------------
    def progress(self, job_id: str) -> dict[str, Any]:
        if not _valid_job_id(job_id):
            return {}
        pf = JOBS_DIR / job_id / "progress.json"
        if pf.exists():
            try:
                with open(pf, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def meta(self, job_id: str) -> dict[str, Any]:
        if not _valid_job_id(job_id):
            return {}
        return self._read_meta(JOBS_DIR / job_id)

    def _sweep_finished(self) -> None:
        """ينظّف العمليات المنتهية من السجلّ (يحمي من «مهمة نشطة وهمية» لو فشل
        _watch بصمت ولم يُزل القيد)."""
        for jid in list(self._procs):
            proc = self._procs.get(jid)
            if proc is None or proc.poll() is not None:
                self._procs.pop(jid, None)

    def is_running(self, job_id: str) -> bool:
        with self._lock:
            self._sweep_finished()
            return job_id in self._procs

    def active_job(self) -> Optional[str]:
        """مُعرّف المهمة النشطة حالياً إن وُجدت (نسمح بمهمة واحدة فقط)."""
        with self._lock:
            self._sweep_finished()
            return next(iter(self._procs), None)

    def list_jobs(self) -> list[dict[str, Any]]:
        jobs = []
        for d in sorted(JOBS_DIR.glob("*"), reverse=True):
            if d.is_dir():
                m = self._read_meta(d)
                if m:
                    jobs.append(m)
        return jobs

    def delete_job(self, job_id: str) -> dict[str, Any]:
        """يحذف مجلد المهمة كاملاً (اللوغ + المخرجات + الحالة).

        يرفض حذف مهمة قيد التشغيل (يجب إيقافها أوّلاً). يرفض أيضاً معرّفاً غير صالح
        أو مساراً يحاول الخروج من JOBS_DIR (حماية مسار).
        """
        if not _valid_job_id(job_id):
            return {"ok": False, "error": "invalid job_id"}
        with self._lock:
            self._sweep_finished()
            if job_id in self._procs:
                return {"ok": False, "error": "job is running — stop it first"}
        job_dir = JOBS_DIR / job_id
        # حماية مسار: نتأكّد أنّه فعلاً تحت JOBS_DIR وليس symlink خارجها.
        try:
            resolved = job_dir.resolve(strict=False)
            jobs_root = JOBS_DIR.resolve(strict=False)
            if jobs_root not in resolved.parents and resolved != jobs_root:
                return {"ok": False, "error": "path escapes jobs root"}
        except OSError:
            return {"ok": False, "error": "path resolution failed"}
        if not job_dir.exists():
            return {"ok": False, "error": "job not found"}
        try:
            import shutil
            shutil.rmtree(str(job_dir))
        except OSError as e:
            return {"ok": False, "error": f"delete failed: {e}"}
        return {"ok": True, "job_id": job_id}

    def delete_all_jobs(self) -> dict[str, Any]:
        """يحذف كل المهام من القرص باستثناء المهمة النشطة حالياً."""
        active = self.active_job()
        deleted, failed = [], []
        for m in self.list_jobs():
            jid = m.get("job_id") or ""
            if not jid or jid == active:
                continue
            res = self.delete_job(jid)
            if res.get("ok"):
                deleted.append(jid)
            else:
                failed.append({"job_id": jid, "error": res.get("error")})
        return {"ok": True, "deleted": deleted, "failed": failed,
                "skipped_active": active}

    def _discover_result(self, job_dir: Path, mode: str) -> dict[str, str]:
        out = job_dir / "output"
        result: dict[str, str] = {}
        if not out.exists():
            return result
        # v1.06: نُميّز بين «audit JSON» (زحف كامل، يصلح لتوليد HTML/PDF/Excel) و
        # «integrations JSON» (تكاملات-فقط، يحوي GSC/GA4/PageSpeed بلا pages). الواجهة
        # تستعمل result.kind لإخفاء أزرار التوليد على المهام التي لا تحوي بيانات زحف.
        patterns = {
            "json": ["audit_*.json", "complete_audit.json"],
            "integrations_json": ["integrations_*.json"],
            "html": ["report_*.html", "report.html"],
            "pdf": ["report_*.pdf", "report.pdf"],
            "excel": ["audit_*.xlsx", "master_audit.xlsx"],
            # متغيّرات تقرير الجمهور (وضع both) — أزرار تنزيل منفصلة
            "html_client": ["report_*_client.html"],
            "pdf_client": ["report_*_client.pdf"],
            "html_expert": ["report_*_expert.html"],
            "pdf_expert": ["report_*_expert.pdf"],
        }
        for name, pats in patterns.items():
            hits: list[Path] = []
            for pat in pats:
                hits.extend(out.rglob(pat))
            # المفاتيح العامة html/pdf يجب ألا تلتقط متغيّرات الجمهور (_client/_expert)
            # كي لا تُختار عشوائياً في وضع both؛ تلك لها مفاتيح صريحة.
            if name in ("html", "pdf"):
                hits = [h for h in hits
                        if not (h.stem.endswith("_client") or h.stem.endswith("_expert"))]
            if hits:
                # الأحدث تعديلاً
                result[name] = str(max(hits, key=lambda p: p.stat().st_mtime))
        # للعرض/التوافق في وضع both (لا يوجد تقرير عام): استخدم نسخة الخبير
        if "html" not in result and result.get("html_expert"):
            result["html"] = result["html_expert"]
        if "pdf" not in result and result.get("pdf_expert"):
            result["pdf"] = result["pdf_expert"]
        xml_dir = out / "xml"
        if xml_dir.exists():
            for xml_file in sorted(xml_dir.glob("*.xml")):
                result[f"xml_{xml_file.stem}"] = str(xml_file)
        # v1.06: علامة kind تساعد الواجهة على اتّخاذ قرار «هل أُظهر أزرار توليد التقارير؟»
        # — لا audit JSON ⇒ مهمّة تكاملات-فقط ⇒ يظهر شريط نتائج التكاملات بدل أزرار التوليد.
        if result.get("json"):
            result["kind"] = "audit"
        elif result.get("integrations_json"):
            result["kind"] = "integrations_only"
        return result

    def _summarize_run_log(self, log_path: Path) -> dict[str, Any]:
        """ملخص سريع يساعد الواجهة على كشف الأخطاء دون فتح اللوغ كاملاً."""
        if not log_path.exists():
            return {"log_exists": False}
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return {"log_exists": True, "read_error": str(e)}

        counts = {"ERROR": 0, "CRITICAL": 0, "WARNING": 0}
        important: list[str] = []
        for line in text.splitlines():
            m = _LOG_LEVEL_RE.search(line)
            if m:
                level = m.group(1)
                if level in counts:
                    counts[level] += 1
                if level in ("ERROR", "CRITICAL"):
                    important.append(line)
            elif "Traceback (most recent call last)" in line:
                important.append(line)
        return {
            "log_exists": True,
            "log_size_bytes": log_path.stat().st_size,
            "error_count": counts["ERROR"],
            "critical_count": counts["CRITICAL"],
            "traceback_count": text.count("Traceback (most recent call last)"),
            "warning_count": counts["WARNING"],
            "last_important_lines": important[-20:],
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _write_meta(job_dir: Path, meta: dict[str, Any]) -> None:
        # v1.13.16 (F45): كتابة ذرّيّة — انهيار في المنتصف لا يُتلف job.json.
        _atomic_write_json(job_dir / "job.json", meta, ensure_ascii=False, indent=2)

    @staticmethod
    def _read_meta(job_dir: Path) -> dict[str, Any]:
        mp = job_dir / "job.json"
        meta: dict[str, Any] = {}
        if mp.exists():
            try:
                with open(mp, "r", encoding="utf-8") as f:
                    meta = json.load(f) or {}
            except (json.JSONDecodeError, OSError):
                meta = {}
        # v1.13.20: self-heal — corrupt/legacy job.json كانت تفقد الحقول الأوّليّة
        # (job_id, url, mode, started_at) عبر race قديمة في _write_meta قبل v1.13.16
        # F45 (atomic write). النتيجة: قائمة "المهام الأخيرة" تعرض صفوفاً فارغة
        # ورابط "عرض" يُعيد إلى / (لأنّ href="/jobs/{{ j.job_id }}" يصير "/jobs/").
        # نُعيد بناء ما يمكن من: اسم المجلّد + config.yaml + progress.json.
        JobRunner._backfill_meta(meta, job_dir)
        return meta

    @staticmethod
    def _backfill_meta(meta: dict[str, Any], job_dir: Path) -> None:
        """يملأ الحقول المفقودة من مصادر مساعدة (اسم المجلّد + config.yaml + run.log)."""
        # job_id دائماً مستخرَج من اسم المجلّد (المصدر الحقيقي).
        if not meta.get("job_id"):
            meta["job_id"] = job_dir.name
        # url + mode + config من config.yaml إن لزم.
        cfg_path = job_dir / "config.yaml"
        if cfg_path.exists():
            if not meta.get("url") or not meta.get("mode") or not meta.get("config"):
                try:
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        cfg = yaml.safe_load(f) or {}
                except (yaml.YAMLError, OSError):
                    cfg = {}
                if not meta.get("url"):
                    meta["url"] = (cfg.get("site") or {}).get("start_url", "")
                if not meta.get("mode"):
                    meta["mode"] = "audit"
                if not meta.get("config"):
                    meta["config"] = str(cfg_path)
        # fallback أخير: URL من run.log لو لم يتوفّر config.yaml (مهام قديمة قد
        # يفقد ملفّ إعدادها كلياً).
        if not meta.get("url"):
            log_path = job_dir / "run.log"
            if log_path.exists():
                try:
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                        # نقرأ أوّل 5000 بايت فقط — Target URL يكون في الأسطر الأولى.
                        head = f.read(5000)
                    m = re.search(r"Target URL:\s*(\S+)", head)
                    if m:
                        meta["url"] = m.group(1)
                except OSError:
                    pass
        # قيم افتراضيّة آمنة للـUI لو لم يُوجَد شيء.
        meta.setdefault("mode", "audit")
        meta.setdefault("url", "")
        # started_at من طابع الوقت في اسم المجلّد (YYYYMMDD_HHMMSS_hex).
        if not meta.get("started_at"):
            m = re.match(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_",
                         job_dir.name)
            if m:
                y, mo, d, hh, mm, ss = m.groups()
                meta["started_at"] = f"{y}-{mo}-{d}T{hh}:{mm}:{ss}"

    @staticmethod
    def _write_progress(pf: Path, data: dict[str, Any]) -> None:
        # v1.13.16 (F45): كتابة ذرّيّة — يمنع progress.json نصف-مكتوب يُربك القارئ.
        _atomic_write_json(pf, data, ensure_ascii=False)
