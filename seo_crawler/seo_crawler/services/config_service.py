"""
services/config_service.py — تهيئة config + output dir + validate + slugify.

نُقل من main.py في v1.12 (Tier 1 — يستورد utils.helpers فقط، لا أيّ service آخر).
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from utils.logger import get_logger

log = get_logger(__name__)


def load_config(config_path: str = "config.yaml") -> dict[str, Any]:
    config_file = Path(config_path)
    if not config_file.exists():
        # v1.13.10: fall back to config.example.yaml so a fresh clone runs
        # without the user having to `cp config.example.yaml config.yaml` first.
        # Only the default path triggers the fallback — an explicit --config
        # pointing at a missing file is still a hard error (likely a typo).
        if config_path == "config.yaml":
            fallback = Path("config.example.yaml")
            if fallback.exists():
                log.info("config.yaml not found; using config.example.yaml")
                config_file = fallback
            else:
                log.error(f"Neither {config_path} nor config.example.yaml found")
                sys.exit(1)
        else:
            log.error(f"Config file not found: {config_path}")
            sys.exit(1)
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        log.error(f"YAML parse error: {e}")
        sys.exit(1)


def setup_output_dir(config: dict[str, Any], mode_name: str) -> Path:
    # v1.13.15 (A2-1): config مُحتمل أن يفتقد قسم output في تشغيل CLI أدنى —
    # نستخدم .get بدلاً من bracket المباشر لتجنّب KeyError غير ودّي.
    output_cfg = config.get("output") or {}
    base_dir = Path(output_cfg.get("output_dir", "./output"))
    if output_cfg.get("timestamped_folder", True):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_dir = base_dir / f"{mode_name}_{timestamp}"
    else:
        output_dir = base_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Output directory: {output_dir}")
    return output_dir


def validate_config(config: dict[str, Any]) -> list[str]:
    """v1.10-C1 (M-8): فحص بنيوي للإعدادات عند startup — يكتشف أخطاء واضحة قبل
    بدء زحفة 3 ساعات تفشل في النصف. يُرجع قائمة تحذيرات (فارغة = OK)."""
    warnings: list[str] = []
    site = config.get("site") or {}
    crawl = config.get("crawl") or {}
    # site.start_url
    su = site.get("start_url", "")
    if not isinstance(su, str) or not su.startswith(("http://", "https://")):
        warnings.append(f"site.start_url ينقصه أو يبدأ بـscheme غير صحيح: {su!r}")
    # crawl.max_pages
    mp = crawl.get("max_pages")
    if mp is not None and (not isinstance(mp, int) or mp < 0):
        warnings.append(f"crawl.max_pages يجب أن يكون int غير سالب: {mp!r}")
    # crawl.concurrent_requests
    cr = crawl.get("concurrent_requests")
    if cr is not None and (not isinstance(cr, int) or cr < 1 or cr > 100):
        warnings.append(f"crawl.concurrent_requests يجب أن يكون 1..100: {cr!r}")
    # crawl.delay_seconds
    ds = crawl.get("delay_seconds")
    if ds is not None and (not isinstance(ds, (int, float)) or ds < 0):
        warnings.append(f"crawl.delay_seconds يجب أن يكون رقم غير سالب: {ds!r}")
    # crawl.seed_strategy
    ss = crawl.get("seed_strategy")
    if ss is not None and ss not in ("homepage", "sitemap", "hybrid"):
        warnings.append(f"crawl.seed_strategy غير معروف: {ss!r}")
    # crawl.deferred_crawl.pagination_max
    dc = crawl.get("deferred_crawl") or {}
    pm = dc.get("pagination_max")
    if pm is not None and (not isinstance(pm, int) or pm < 0):
        warnings.append(f"crawl.deferred_crawl.pagination_max يجب أن يكون int>=0: {pm!r}")
    return warnings


def slugify_label(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    slug = "_".join(part for part in slug.split("_") if part)
    return slug or "site"


def configure_target_site(config: dict[str, Any], url: str) -> None:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid site URL: {url}")
    # حماية SSRF على رابط البداية قبل أي طلب (يشمل جلب robots.txt الذي يسبق
    # فحص SSRF لكل رابط). يُسمح بالمضيفين الخاصين فقط عند crawl.allow_private_hosts.
    from utils.helpers import is_safe_remote_url
    allow_private = bool(config.get("crawl", {}).get("allow_private_hosts", False))
    safe, reason = is_safe_remote_url(url, allow_private)
    if not safe:
        raise ValueError(f"Unsafe site URL ({reason}): {url}")
    config["site"]["start_url"] = url
    config["site"]["domain"] = parsed.netloc
