@echo off
REM ============================================================
REM  SCT — One-click launcher (Windows)
REM
REM  Usage:
REM    - Double-click this file (in Explorer)
REM    - or from PowerShell/cmd:  START.bat
REM
REM  What it does:
REM    1. Finds Python (venv then system)
REM    2. Installs requirements automatically when needed (once)
REM    3. Opens the browser at http://127.0.0.1:8000
REM    4. Prints the local token for use from curl/scripts
REM    5. Runs the server in the foreground (Ctrl+C to stop)
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo  ===========================================================
echo   SCT - Simple Crawler Tool
echo  ===========================================================
echo.

REM ── 1) Pick Python: venv (if present) then system ──────────
set "PYTHON="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
    echo [SCT] using venv: .venv\Scripts\python.exe
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo [SCT] ✗ Python is not installed on this machine.
        echo       Download it from: https://www.python.org/downloads/
        echo       Or run installer\install.ps1 to set up a fully isolated venv.
        echo.
        pause
        exit /b 1
    )
    set "PYTHON=python"
    echo [SCT] using system Python
)

REM ── 2) Dependency check (once on first run) ──────
"!PYTHON!" -c "import fastapi, uvicorn, aiohttp, bs4, yaml" >nul 2>nul
if errorlevel 1 (
    echo [SCT] installing requirements for the first time (may take a minute)...
    "!PYTHON!" -m pip install --quiet -r requirements.txt
    if errorlevel 1 (
        echo [SCT] ✗ Failed to install requirements. See the error above.
        pause
        exit /b 1
    )
    echo [SCT] ✓ Requirements installed.
)

REM ── 3) Open the browser after a few seconds (gives the server time to boot) ──
echo [SCT] the browser will open shortly at http://127.0.0.1:8000
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000"

REM ── 4) Show the local token if present (for use from curl/scripts) ──
if exist "%USERPROFILE%\.sct\local_token" (
    echo.
    echo  ───────────────────────────────────────────────────────
    echo   Local token (for curl / scripts):
    type "%USERPROFILE%\.sct\local_token"
    echo.
    echo  ───────────────────────────────────────────────────────
)

REM ── 5) Run the server in the foreground (Ctrl+C to stop) ─────────
echo.
echo [SCT] server running. Press Ctrl+C to stop.
echo.
"!PYTHON!" webapp\run.py --host 127.0.0.1 --port 8000

REM If the server exits unexpectedly
if errorlevel 1 (
    echo.
    echo [SCT] the server stopped with an error. See the message above.
    pause
)

endlocal
