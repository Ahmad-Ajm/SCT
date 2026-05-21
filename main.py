"""
Root launcher for SCT.

The maintained crawler implementation lives in ``seo_crawler/seo_crawler``.
Keeping this thin entry point lets users run the tool from the project root
without duplicating the application code.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent / "seo_crawler" / "seo_crawler"


def _bootstrap() -> None:
    if not APP_DIR.exists():
        raise RuntimeError(f"SCT application directory was not found: {APP_DIR}")

    app_dir = str(APP_DIR)
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)


def main() -> None:
    _bootstrap()

    try:
        from main import main as app_main
    except ModuleNotFoundError as exc:
        missing = exc.name or "unknown"
        print(
            f"Missing dependency: {missing}\n"
            "Install SCT dependencies first:\n"
            "  python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    app_main()


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent)
    main()
