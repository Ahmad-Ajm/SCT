@echo off
REM ============================================================
REM  SCT — مُشغّل بنقرة واحدة (Windows)
REM
REM  استخدام:
REM    - انقر مزدوجاً على هذا الملف (في Explorer)
REM    - أو من PowerShell/cmd:  START.bat
REM
REM  ما يفعله:
REM    1. يبحث عن Python (venv ثم النظام)
REM    2. يثبّت المتطلبات تلقائياً عند الحاجة (مرّة واحدة)
REM    3. يفتح المتصفّح على http://127.0.0.1:8000
REM    4. يطبع الـtoken المحلّي للاستعمال من curl/scripts
REM    5. يشغّل الخادم في المقدّمة (Ctrl+C لإيقافه)
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo  ===========================================================
echo   SCT - Simple Crawler Tool
echo  ===========================================================
echo.

REM ── 1) اختيار Python: venv (إن وُجدت) ثم النظام ──────────
set "PYTHON="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
    echo [SCT] استعمال venv: .venv\Scripts\python.exe
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo [SCT] ✗ Python غير مثبَّت على هذا الجهاز.
        echo       نزّله من: https://www.python.org/downloads/
        echo       او شغّل installer\install.ps1 لإعداد venv معزولة كاملة.
        echo.
        pause
        exit /b 1
    )
    set "PYTHON=python"
    echo [SCT] استعمال Python النظام
)

REM ── 2) فحص dependencies (مرّة واحدة عند أوّل تشغيل) ──────
"!PYTHON!" -c "import fastapi, uvicorn, aiohttp, bs4, yaml" >nul 2>nul
if errorlevel 1 (
    echo [SCT] تثبيت المتطلّبات لأوّل مرّة (قد يأخذ دقيقة)...
    "!PYTHON!" -m pip install --quiet -r requirements.txt
    if errorlevel 1 (
        echo [SCT] ✗ فشل تثبيت المتطلّبات. راجع الخطأ أعلاه.
        pause
        exit /b 1
    )
    echo [SCT] ✓ تمّ تثبيت المتطلّبات.
)

REM ── 3) فتح المتصفّح بعد ثانيتين (يعطي الخادم وقتاً للإقلاع) ──
echo [SCT] سيُفتح المتصفّح خلال ثانيتين على http://127.0.0.1:8000
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000"

REM ── 4) اعرض الـtoken المحلّي إن وُجد (للاستعمال من curl/scripts) ──
if exist "%USERPROFILE%\.sct\local_token" (
    echo.
    echo  ───────────────────────────────────────────────────────
    echo   Local token (لـcurl / scripts):
    type "%USERPROFILE%\.sct\local_token"
    echo.
    echo  ───────────────────────────────────────────────────────
)

REM ── 5) شغّل الخادم في المقدّمة (Ctrl+C لإيقافه) ─────────
echo.
echo [SCT] الخادم يعمل. اضغط Ctrl+C للإيقاف.
echo.
"!PYTHON!" webapp\run.py --host 127.0.0.1 --port 8000

REM إن خرج الخادم بشكل غير متوقّع
if errorlevel 1 (
    echo.
    echo [SCT] الخادم توقّف بخطأ. راجع الرسالة أعلاه.
    pause
)

endlocal
