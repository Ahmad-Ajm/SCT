@echo off
REM ============================================================
REM  SCT — إيقاف الخادم وكل المهام النشطة (Windows)
REM
REM  الاستخدام: انقر مزدوجاً
REM
REM  ما يفعله:
REM    - يجد عمليّة Python التي تُشغّل webapp/run.py على المنفذ 8000
REM    - يُنهيها بأمان (Ctrl+Break) ثمّ بـkill إن لزم
REM ============================================================
setlocal

echo.
echo [SCT] البحث عن عمليّة الخادم على المنفذ 8000...

REM ابحث عن PID للخدمة المستمعة على 8000
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    set "PID=%%a"
    goto :found
)

echo [SCT] لا يوجد خادم نشط على المنفذ 8000.
pause
exit /b 0

:found
echo [SCT] وُجدت عمليّة بـPID=%PID%، جارٍ الإيقاف...
taskkill /PID %PID% /T /F >nul 2>nul
if errorlevel 1 (
    echo [SCT] ✗ تعذّر الإيقاف. شغّل cmd كـAdministrator وأعد المحاولة.
) else (
    echo [SCT] ✓ تمّ الإيقاف.
)

REM امهلها ثانية وتأكّد
timeout /t 1 >nul
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul
if not errorlevel 1 (
    echo [SCT] ⚠ لا تزال هناك عمليّة على المنفذ. أعد المحاولة كـAdministrator.
)

pause
endlocal
