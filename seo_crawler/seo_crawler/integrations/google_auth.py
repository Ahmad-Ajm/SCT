"""
integrations/google_auth.py
===========================
مُحمّل اعتماد Google موحّد يدعم نوعين تلقائياً (يُستخدم من GSC و GA4):

1) حساب خدمة (Service Account JSON): يعمل مباشرةً، لكنه يتطلّب إضافة بريد حساب الخدمة
   كمستخدم في GA4 و Search Console (قد ترفضه بعض الإعدادات).
2) OAuth (client secret لتطبيق «سطح المكتب»): يفتح موافقة المستخدم مرّة واحدة في المتصفح،
   ويحفظ token محلياً، فيستعمل حساب المالك الذي يملك الصلاحية أصلاً — دون أي حاجة لإضافة
   حساب الخدمة. هذا هو الحل البديل عندما يُرفض حساب الخدمة.

لا أسرار في الكود. الـ token يُحفظ بصلاحيات مقيّدة (0600) محلياً فقط.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from utils.logger import get_logger

log = get_logger(__name__)


def detect_credentials_type(credentials_file: str) -> str:
    """يكشف نوع ملف الاعتماد: service_account | oauth | unknown."""
    try:
        data = json.loads(Path(credentials_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unknown"
    if isinstance(data, dict):
        if data.get("type") == "service_account":
            return "service_account"
        if "installed" in data or "web" in data:
            return "oauth"
    return "unknown"


def load_google_credentials(
    credentials_file: str,
    scopes: list[str],
    token_path: Optional[str] = None,
) -> Optional[Any]:
    """يعيد اعتماداً صالحاً (Service Account أو OAuth) أو None عند الفشل.

    للـ OAuth: يستعمل token محفوظاً إن وُجد، وإلا يفتح موافقة المتصفح مرّة واحدة
    (يُفضّل تنفيذها مسبقاً عبر authorize_google.py كي لا تتعطّل عمليات الواجهة).
    """
    p = Path(credentials_file)
    if not p.exists():
        log.error(f"ملف الاعتماد غير موجود: {credentials_file}")
        return None

    ctype = detect_credentials_type(credentials_file)

    if ctype == "service_account":
        try:
            from google.oauth2 import service_account
        except ImportError:
            log.error("مكتبة google-auth غير مثبتة. ثبّت: pip install google-auth")
            return None
        return service_account.Credentials.from_service_account_file(
            str(p), scopes=scopes
        )

    if ctype == "oauth":
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError:
            log.error(
                "مكتبات OAuth غير مثبتة. ثبّت: "
                "pip install google-auth-oauthlib google-api-python-client"
            )
            return None

        tp = Path(token_path) if token_path else p.parent / f"{p.stem}_token.json"
        creds: Optional[Any] = None
        if tp.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(tp), scopes)
            except (OSError, ValueError):
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(p), scopes)
                creds = flow.run_local_server(port=0)
            try:
                tp.write_text(creds.to_json(), encoding="utf-8")
                try:
                    os.chmod(tp, 0o600)
                except (OSError, NotImplementedError):
                    pass
            except OSError as e:
                log.warning(f"تعذّر حفظ token الاعتماد: {e}")
        return creds

    log.error(
        f"نوع ملف الاعتماد غير معروف ({credentials_file}). يجب أن يكون إمّا حساب خدمة "
        f"(type=service_account) أو client secret لتطبيق OAuth (يحوي 'installed'/'web')."
    )
    return None
