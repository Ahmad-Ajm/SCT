#!/usr/bin/env bash
# =============================================================
#  SCT — Single-command launcher (macOS/Linux)
#
#  Usage:
#    ./start.sh
#    or:  bash start.sh
#
#  What it does:
#    1. Picks Python (venv > system)
#    2. Auto-installs deps on first run
#    3. Opens the browser (via `open`/`xdg-open`)
#    4. Prints the local token
#    5. Runs the server in the foreground (Ctrl+C to stop)
# =============================================================
set -e
cd "$(dirname "$0")"

echo ""
echo " ==========================================================="
echo "  SCT - Simple Crawler Tool"
echo " ==========================================================="
echo ""

# ── 1) pick Python ────────────────────────────────────────
if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
    echo "[SCT] using venv: .venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
    echo "[SCT] using system python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON="python"
    echo "[SCT] using system python"
else
    echo "[SCT] ✗ Python not installed."
    echo "      install via: brew install python  (macOS)"
    echo "                   sudo apt install python3 python3-pip  (Debian/Ubuntu)"
    exit 1
fi

# ── 2) dependency check (first run only) ──────────────────
if ! "$PYTHON" -c "import fastapi, uvicorn, aiohttp, bs4, yaml" >/dev/null 2>&1; then
    echo "[SCT] installing requirements (first run, ~1 minute)..."
    "$PYTHON" -m pip install --quiet -r requirements.txt
    echo "[SCT] ✓ requirements installed."
fi

# ── 3) open browser after 3s ──────────────────────────────
echo "[SCT] opening browser in 3s on http://127.0.0.1:8000"
(
    sleep 3
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "http://127.0.0.1:8000" >/dev/null 2>&1 || true
    elif command -v open >/dev/null 2>&1; then
        open "http://127.0.0.1:8000" >/dev/null 2>&1 || true
    fi
) &

# ── 4) print local token (for curl/scripts) ───────────────
TOKEN_FILE="$HOME/.sct/local_token"
if [ -f "$TOKEN_FILE" ]; then
    echo ""
    echo " ───────────────────────────────────────────────────────"
    echo "  Local token (for curl / scripts):"
    cat "$TOKEN_FILE"
    echo ""
    echo " ───────────────────────────────────────────────────────"
fi

# ── 5) run server in foreground ───────────────────────────
echo ""
echo "[SCT] server running. Ctrl+C to stop."
echo ""
exec "$PYTHON" webapp/run.py --host 127.0.0.1 --port 8000
