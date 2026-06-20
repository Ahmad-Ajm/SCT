@echo off
REM ============================================================
REM  tools/freeze_lock.bat — توليد requirements.lock.txt صحيح
REM
REM  لماذا script منفصل: `pip freeze` المباشر يلتقط كلّ packages النظام
REM  (أيّ مكتبات خارجيّة مثبّتة عالمياً) لا فقط ما يحتاجه SCT. هذا الـscript ينشئ venv
REM  مؤقّتة نظيفة، يثبّت requirements.txt فقط، ثمّ يجمّد للحصول على
REM  lockfile دقيق reproducible.
REM
REM  الاستخدام: من جذر SCT:
REM      tools\freeze_lock.bat
REM ============================================================
setlocal
cd /d "%~dp0\.."

echo [SCT] إنشاء venv مؤقّتة...
python -m venv .venv-lock
if errorlevel 1 (
    echo [SCT] ✗ تعذّر إنشاء venv. هل python في PATH؟
    exit /b 1
)

echo [SCT] تثبيت requirements.txt في الـvenv النظيفة...
.venv-lock\Scripts\python.exe -m pip install --quiet --upgrade pip
.venv-lock\Scripts\python.exe -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo [SCT] ✗ فشل التثبيت.
    rmdir /s /q .venv-lock
    exit /b 1
)

echo [SCT] توليد requirements.lock.txt...
.venv-lock\Scripts\python.exe -m pip freeze ^
    | findstr /v /b "pip==" ^
    | findstr /v /b "setuptools==" ^
    | findstr /v /b "wheel==" ^
    > requirements.lock.txt

echo [SCT] تنظيف venv المؤقّتة...
rmdir /s /q .venv-lock

echo.
echo [SCT] ✓ تمّ التوليد: requirements.lock.txt
findstr /n /c:"" requirements.lock.txt | findstr "^1: ^2: ^3:"
echo ...
for /f %%c in ('find /c /v "" ^< requirements.lock.txt') do echo [SCT] إجمالي السطور: %%c

endlocal
