"""
authorize_google.py
====================
موافقة OAuth لمرّة واحدة لـ Google Search Console + Google Analytics 4.

استخدمه عندما يُرفض إضافة «حساب الخدمة» إلى GA4/GSC: فبدلاً من حساب الخدمة، نأذن
بحسابك أنت (المالك الذي يملك الصلاحية أصلاً) عبر متصفّحك مرّة واحدة، ثم تحفظ الأداة
الـ token وتستعمله تلقائياً (دون فتح متصفّح في كل تشغيل).

الخطوات:
  1) في Google Cloud Console: APIs & Services ← Credentials ← Create credentials ←
     OAuth client ID ← Application type: «Desktop app» ← نزّل ملف client secret (JSON).
  2) شغّل (مرة واحدة):
        python authorize_google.py "C:\\path\\client_secret.json"
     سيفتح المتصفح؛ اختر حساب Google الذي يملك صلاحية GA4 و Search Console ووافق.
  3) ستُحفظ token بجوار ملف client secret:  gsc_token.json و ga4_token.json
  4) في الواجهة: فعّل GSC و GA4 واجعل «ملف الاعتماد» يشير إلى ملف client secret نفسه.

ملاحظة: هذا الملف لا يحوي أي أسرار، ولا تُرفع ملفات client secret / token إلى Git.
"""

from __future__ import annotations

import sys
from pathlib import Path

# نطاقات القراءة فقط لكلا الخدمتين
SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",   # Search Console
    "https://www.googleapis.com/auth/analytics.readonly",    # Analytics 4
]


def main() -> int:
    if len(sys.argv) < 2:
        print("الاستخدام: python authorize_google.py <مسار client_secret.json>")
        return 2
    client = Path(sys.argv[1])
    if not client.exists():
        print(f"الملف غير موجود: {client}")
        return 2

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("ثبّت أولاً: pip install google-auth-oauthlib google-api-python-client "
              "google-analytics-data")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(client), SCOPES)
    print("سيُفتح المتصفّح — اختر الحساب المالك ووافق على القراءة فقط...")
    creds = flow.run_local_server(port=0)

    # نحفظ نفس الـ token (يغطّي كلا النطاقين) بالاسمين اللذين تتوقّعهما الأداة
    import os
    for name in ("gsc_token.json", "ga4_token.json"):
        out = client.parent / name
        out.write_text(creds.to_json(), encoding="utf-8")
        try:
            os.chmod(out, 0o600)
        except (OSError, NotImplementedError):
            pass
        print(f"تم الحفظ: {out}")

    print("\nتم الإذن بنجاح. الآن فعّل GSC و GA4 في الواجهة واجعل «ملف الاعتماد» "
          "يشير إلى ملف client secret نفسه، ثم شغّل الزحف.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
