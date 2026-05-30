@echo off
REM ============================================================
REM  SCT — مُشغّل الواجهة المرئية (Windows)
REM  انقر مزدوجاً لتشغيل الأداة على http://127.0.0.1:8000
REM ============================================================
setlocal
set ROOT=%~dp0..
pushd "%ROOT%"

if not exist ".venv\Scripts\python.exe" (
    echo [SCT] venv غير موجود — شغّل installer\install.ps1 أولاً.
    pause
    exit /b 1
)

REM افتح المتصفّح على الواجهة (يُجدول الفتح بعد ثانيتين كي يكون الخادم جاهزاً)
start "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8000"

REM شغّل الخادم في المقدّمة (Ctrl+C لإيقافه)
".venv\Scripts\python.exe" webapp\run.py --host 127.0.0.1 --port 8000

popd
endlocal
