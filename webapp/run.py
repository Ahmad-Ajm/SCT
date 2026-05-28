"""
webapp/run.py
=============
مُشغّل خادم الواجهة المرئية.

    python webapp/run.py            # http://127.0.0.1:8000
    python webapp/run.py --port 9000 --host 0.0.0.0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="SCT visual interface")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    try:
        import uvicorn
    except ModuleNotFoundError:
        print(
            "Missing dependency: uvicorn/fastapi.\n"
            "Install UI dependencies:\n"
            "  python -m pip install fastapi 'uvicorn[standard]' jinja2 python-multipart",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # نضمن أن جذر المشروع في sys.path لاستيراد webapp.app
    sys.path.insert(0, str(ROOT))
    print(f"SCT UI running at http://{args.host}:{args.port}")
    uvicorn.run("webapp.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
