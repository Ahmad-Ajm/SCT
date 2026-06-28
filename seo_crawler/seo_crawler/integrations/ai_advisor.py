"""
integrations/ai_advisor.py
==========================
مستشار ذكاء اصطناعي اختياري ومحايد للمزوّد.

يأخذ ملخّص التدقيق + أهم الفرص ويطلب من نموذج لغوي:
1. ملخّصاً تنفيذياً واضحاً لحالة الموقع.
2. توصيات محدّدة ومرتّبة بالأولوية لتحسين الـ SEO.

المزوّدات المدعومة (كلها عبر `requests` فقط — لا تبعيات إضافية):
- openai / deepseek / openrouter / huggingface / أي نقطة متوافقة مع OpenAI
  (chat/completions): تُضبط عبر `base_url` + `model` + مفتاح Bearer.
- gemini (Google Generative Language): شكل طلب مختلف (`:generateContent`).

مبادئ:
- مطفأ افتراضياً. لا يُكتب المفتاح في المستودع؛ يُقرأ من الإعداد المحلي أو
  من متغيّر البيئة `AI_API_KEY`.
- لا يُرسل بيانات شخصية (PII): فقط روابط الصفحات وأنواع المشاكل وأرقام مجمّعة.
- يتعامل بلطف عند غياب المفتاح أو فشل الشبكة (يُرجع حالة واضحة بدل أن ينهار).
"""

from __future__ import annotations

import json
import os
from typing import Any

from utils.logger import get_logger

log = get_logger(__name__)

# سجلّ المزوّدات: القيم الافتراضية لـ base_url والنموذج وشكل الطلب.
# يستطيع المستخدم تجاوز base_url/model من الإعدادات (يدعم النماذج المحلية أيضاً).
_PROVIDERS: dict[str, dict[str, str]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini", "shape": "openai",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat", "shape": "openai",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini", "shape": "openai",
    },
    "huggingface": {
        "base_url": "https://router.huggingface.co/v1",
        "model": "meta-llama/Llama-3.1-8B-Instruct", "shape": "openai",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "model": "gemini-1.5-flash", "shape": "gemini",
    },
    # نقطة متوافقة مع OpenAI مخصّصة (Ollama/LM Studio/بوابة داخلية): base_url+model مطلوبان
    "openai_compatible": {"base_url": "", "model": "", "shape": "openai"},
}

_SYSTEM_PROMPT = {
    "ar": (
        "أنت خبير SEO تقني. ستحصل على ملخّص نتائج تدقيق زاحف لموقع، وعليك أن تُرجع "
        "JSON فقط بالشكل: {\"summary\": str, \"recommendations\": [{\"title\": str, "
        "\"why\": str, \"action\": str, \"priority\": \"high|medium|low\"}]}. "
        "اكتب بالعربية، بإيجاز وعملية، وركّز على ما يرفع الظهور والنقرات أولاً."
    ),
    "en": (
        "You are a technical SEO expert. You will receive a crawler audit summary for a "
        "site and must return ONLY JSON shaped as: {\"summary\": str, "
        "\"recommendations\": [{\"title\": str, \"why\": str, \"action\": str, "
        "\"priority\": \"high|medium|low\"}]}. Be concise and practical; prioritize what "
        "improves visibility and clicks first."
    ),
}


class AIAdvisor:
    """عميل ذكاء اصطناعي محايد للمزوّد."""

    def __init__(
        self,
        provider: str = "openai",
        api_key: str = "",
        model: str = "",
        base_url: str = "",
        timeout: int = 60,
        language: str = "ar",
        allow_private: bool = False,
    ):
        self.provider = (provider or "openai").lower()
        spec = _PROVIDERS.get(self.provider, _PROVIDERS["openai_compatible"])
        self.shape = spec["shape"]
        self.base_url = (base_url or spec["base_url"]).rstrip("/")
        self.model = model or spec["model"]
        self.api_key = api_key or os.getenv("AI_API_KEY", "")
        self.timeout = timeout
        self.language = "en" if str(language).lower().startswith("en") else "ar"
        # السماح بنقطة خاصة/محلية (نماذج محلية مثل Ollama/LM Studio على 127.0.0.1).
        # افتراضياً مرفوض كي لا يُوجَّه الطلب (ومعه مفتاح Bearer) لعنوان داخلي/ميتاداتا.
        self.allow_private = bool(allow_private)

    # ------------------------------------------------------------------
    def is_ready(self) -> tuple[bool, str]:
        """هل الإعداد كافٍ للاستدعاء؟ يُرجع (جاهز، سبب)."""
        if not self.api_key:
            return False, "missing_api_key"
        if not self.base_url:
            return False, "missing_base_url"
        if not self.model:
            return False, "missing_model"
        # حماية SSRF: نرفض توجيه الطلب (ومعه المفتاح) لعنوان داخلي/loopback/ميتاداتا
        # إلا إذا فعّل المستخدم allow_private صراحةً (للنماذج المحلية).
        from utils.helpers import is_safe_remote_url
        safe, _reason = is_safe_remote_url(self.base_url, self.allow_private)
        if not safe:
            return False, "unsafe_base_url"
        try:
            import requests  # noqa: F401
        except ImportError:
            return False, "requests_not_installed"
        return True, ""

    def analyze(self, audit_summary: dict[str, Any]) -> dict[str, Any]:
        """يطلب تحليلاً وتوصيات من النموذج بناءً على ملخّص التدقيق.

        Returns:
            dict: {"enabled": bool, "provider": str, "model": str,
                   "summary": str, "recommendations": list, "error": str|None}
        """
        ready, reason = self.is_ready()
        base = {
            "enabled": True, "provider": self.provider, "model": self.model,
            "summary": "", "recommendations": [], "error": None,
        }
        if not ready:
            base["error"] = reason
            log.info(f"AI advisor غير جاهز: {reason}")
            return base

        prompt = self._build_user_prompt(audit_summary)
        try:
            if self.shape == "gemini":
                text = self._call_gemini(prompt)
            else:
                text = self._call_openai_compatible(prompt)
        except Exception as e:  # شبكة/مفتاح/استجابة غير متوقّعة
            base["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            log.warning(f"AI advisor فشل: {base['error']}")
            return base

        parsed = self._parse_json_object(text)
        if parsed is None:
            # النموذج لم يُرجع JSON صالحاً: نُعيد النص الخام كملخّص
            base["summary"] = (text or "").strip()[:4000]
            return base
        base["summary"] = str(parsed.get("summary", ""))[:6000]
        recs = parsed.get("recommendations", [])
        base["recommendations"] = recs if isinstance(recs, list) else []
        return base

    # ------------------------------------------------------------------
    def _build_user_prompt(self, audit_summary: dict[str, Any]) -> str:
        """نص الطلب: ملخّص مدمج وخالٍ من PII."""
        payload = json.dumps(audit_summary, ensure_ascii=False, default=str)
        if self.language == "ar":
            return ("هذه بيانات تدقيق موقع (JSON). حلّلها وأعطني JSON بالملخّص "
                    f"والتوصيات حسب التعليمات:\n{payload}")
        return ("Here is a site's audit data (JSON). Analyze it and return the "
                f"summary+recommendations JSON per the instructions:\n{payload}")

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {self.api_key}"}
        if self.provider == "openrouter":
            # ترويسات اختيارية يُفضّلها OpenRouter (لا تكشف شيئاً حسّاساً)
            headers["HTTP-Referer"] = "https://localhost/sct"
            headers["X-Title"] = "SCT SEO Crawler"
        return headers

    def _call_openai_compatible(self, user_prompt: str) -> str:
        import requests

        url = f"{self.base_url}/chat/completions"
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT[self.language]},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        resp = requests.post(url, headers=self._headers(),
                             json=body, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        return (choices[0].get("message") or {}).get("content") or ""

    def _call_gemini(self, user_prompt: str) -> str:
        import requests

        url = f"{self.base_url}/models/{self.model}:generateContent"
        body = {
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT[self.language]}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": 0.2},
        }
        # المفتاح في ترويسة لا في الـ URL (الـ query strings تُسجَّل في الوسطاء/اللوغ)
        resp = requests.post(
            url,
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            json=body, timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        # تصفّح آمن: أيّ حقل مفقود/فارغ في الاستجابة لا يجب أن يُسقط التدقيق كلّه.
        # نُسلسل عبر .get() مع defaults كي نتجنّب IndexError/KeyError على المنتصف.
        candidates = data.get("candidates") or [{}]
        content = candidates[0].get("content") or {}
        parts = content.get("parts") or [{}]
        text = parts[0].get("text", "") or ""
        if not text:
            log.warning("Gemini response missing text field — returning empty string")
        return text

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any] | None:
        """استخراج أول كائن JSON من نص قد يحوي أسوار ```json أو شرحاً."""
        if not text:
            return None
        s = text.strip()
        if s.startswith("```"):
            # إزالة أسوار ```json ... ```
            s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
            if s.lstrip().lower().startswith("json"):
                s = s.lstrip()[4:]
        start = s.find("{")
        end = s.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            obj = json.loads(s[start:end + 1])
            return obj if isinstance(obj, dict) else None
        except ValueError:
            return None


def build_audit_summary_for_ai(
    analysis: dict[str, Any],
    site_url: str = "",
    max_opportunities: int = 15,
) -> dict[str, Any]:
    """يبني ملخّصاً مُدمجاً وخالياً من PII لإرساله للنموذج.

    يشمل: عدّادات المشاكل بالخطورة، أهم أنواع المشاكل، وأهم الفرص (روابط +
    مشاكل + إشارات حركة المرور) — دون أي بيانات مستخدمين.
    """
    seo = (analysis.get("seo_issues", {}) or {})
    summary = seo.get("summary", {}) or {}
    by_sev = seo.get("by_severity", {}) or {}

    top_issue_types: list[dict[str, Any]] = []
    for sev, items in by_sev.items():
        for it in (items or [])[:50]:
            top_issue_types.append({
                "severity": sev,
                "issue_type": it.get("issue_type", ""),
                "affected_count": it.get("affected_count", 0),
            })
    top_issue_types.sort(key=lambda x: -int(x.get("affected_count", 0) or 0))

    # v1.09-B6: strip query string من URLs قبل إرسالها للـLLM طرف ثالث.
    # `?utm_source=…&email=…&session=…` لا يجب أن يخرج للـAPI الخارجي.
    from urllib.parse import urlparse, urlunparse
    def _strip_qs(u: str) -> str:
        if not u:
            return ""
        try:
            p = urlparse(u)
            return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
        except (ValueError, TypeError):
            return u

    opps = (analysis.get("opportunities", {}) or {}).get("opportunities", []) or []
    top_opps = [{
        "url": _strip_qs(o.get("url", "")),
        "priority_score": o.get("priority_score", 0),
        "technical_issues": o.get("technical_issues", ""),
        "clicks": o.get("clicks", 0),
        "impressions": o.get("impressions", 0),
        "sessions": o.get("sessions", 0),
        "top_fix": o.get("top_fix", ""),
    } for o in opps[:max_opportunities]]

    return {
        "site": site_url,
        "issue_counts": {
            "total": summary.get("total_issues", 0),
            "critical": summary.get("critical_count", 0),
            "high": summary.get("high_count", 0),
            "medium": summary.get("medium_count", 0),
            "low": summary.get("low_count", 0),
        },
        "top_issue_types": top_issue_types[:20],
        "top_opportunities": top_opps,
    }
