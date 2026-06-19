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
import os
import re
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime
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
            cfg["site"]["start_url"] = url
            from urllib.parse import urlparse
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

        # قالب منصّة التجارة (IMP-11): يُطبَّق فقط لقيمة معروفة
        preset = str(overrides.get("platform_preset", "") or "").strip().lower()
        if preset in ("zid", "salla", "shopify", "woocommerce"):
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

        # === الاستخراج المخصّص ===
        ce = overrides.get("custom_extraction")
        if ce is not None:
            cfg["custom_extraction"]["enabled"] = bool(ce.get("enabled"))
            cfg["custom_extraction"]["rules"] = ce.get("rules", [])

        # === عتبات التحليل ===
        for key, val in (overrides.get("analysis") or {}).items():
            if val is not None:
                cfg["analysis"][key] = val

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

        args = [sys.executable, str(MAIN_PY), "--config", str(cfg_path), "--mode", mode]
        if overrides.get("url"):
            args += ["--url", overrides["url"]]
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
        with self._lock:
            self._sweep_finished()
            if self._procs:
                return {"ok": False, "error": "active_job",
                        "active_job": next(iter(self._procs), None)}
        job_dir = JOBS_DIR / job_id
        if not job_dir.exists():
            return {"ok": False, "error": "job_not_found"}
        cfg_path = job_dir / "config.yaml"
        if not cfg_path.exists():
            return {"ok": False, "error": "config_missing"}
        # تحقّق من deferred_urls.csv قبل الإطلاق (يوفّر فشلاً سريعاً وواضحاً)
        deferred_csv = job_dir / "output" / "csv" / "deferred_urls.csv"
        if not deferred_csv.exists():
            return {"ok": False, "error": "no_deferred_urls"}

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
        with self._lock:
            self._procs[job_id] = proc
        threading.Thread(target=self._watch, args=(job_id, job_dir, proc), daemon=True).start()
        return {"ok": True, "job_id": job_id, "phase": 2}

    # حالات الانتهاء التي يكتبها المحرّك في progress.json
    _FINAL_STATUSES = {"complete", "partial", "partial_max_pages", "stopped"}

    def _watch(self, job_id: str, job_dir: Path, proc: subprocess.Popen) -> None:
        rc = proc.wait()
        meta = self._read_meta(job_dir)
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
        self._write_meta(job_dir, meta)
        with self._lock:
            self._procs.pop(job_id, None)

    def stop(self, job_id: str, grace_seconds: float = 8.0) -> bool:
        """يطلب توقّفاً لطيفاً، ثم يُصعّد إلى terminate/kill إن لم تستجب
        العملية خلال grace_seconds (يحمي من حلقات تكامل لا تفحص الإشارة)."""
        if not _valid_job_id(job_id):
            return False
        with self._lock:
            proc = self._procs.get(job_id)
        if not proc:
            return False
        try:
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.send_signal(signal.SIGINT)
        except (ProcessLookupError, OSError):
            return False
        # ننتظر لطفاً، ثم نُصعّد إن استمرّت
        try:
            proc.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    proc.kill()
                except OSError:
                    pass
        meta = self._read_meta(JOBS_DIR / job_id)
        meta["status"] = "stopped"
        self._write_meta(JOBS_DIR / job_id, meta)
        return True

    def force_kill(self, job_id: str) -> bool:
        """قتل فوري بلا مهلة (للحلقات الطويلة العالقة في طرف ثالث مثل PageSpeed)."""
        if not _valid_job_id(job_id):
            return False
        with self._lock:
            proc = self._procs.get(job_id)
        if not proc:
            return False
        try:
            proc.kill()
        except OSError:
            pass
        meta = self._read_meta(JOBS_DIR / job_id)
        meta["status"] = "stopped"
        self._write_meta(JOBS_DIR / job_id, meta)
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
        with open(job_dir / "job.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _read_meta(job_dir: Path) -> dict[str, Any]:
        mp = job_dir / "job.json"
        if mp.exists():
            try:
                with open(mp, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    @staticmethod
    def _write_progress(pf: Path, data: dict[str, Any]) -> None:
        with open(pf, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
