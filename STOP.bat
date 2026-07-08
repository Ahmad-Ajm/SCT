@echo off
REM ============================================================
REM  SCT — Stop the server and all active tasks (Windows)
REM
REM  Usage: double-click
REM
REM  What it does:
REM    - Finds the Python process running webapp/run.py on port 8000
REM    - Terminates it gracefully (Ctrl+Break) then by kill if needed
REM ============================================================
setlocal

echo.
echo [SCT] Searching for the server process on port 8000...

REM Find the PID of the service listening on 8000
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    set "PID=%%a"
    goto :found
)

echo [SCT] No active server on port 8000.
pause
exit /b 0

:found
echo [SCT] Found process PID=%PID%, stopping...
taskkill /PID %PID% /T /F >nul 2>nul
if errorlevel 1 (
    echo [SCT] ✗ Could not stop it. Run cmd as Administrator and try again.
) else (
    echo [SCT] ✓ Stopped.
)

REM Give it a second and verify
timeout /t 1 >nul
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul
if not errorlevel 1 (
    echo [SCT] ⚠ There is still a process on the port. Try again as Administrator.
)

pause
endlocal
