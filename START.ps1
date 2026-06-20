# =============================================================
#  SCT — مُشغّل بنقرة واحدة (PowerShell)
#
#  استخدام:
#    Right-click → "Run with PowerShell"
#    أو:        powershell -ExecutionPolicy Bypass -File START.ps1
#
#  مزايا على START.bat:
#    - رسائل ملوّنة وأوضح
#    - يكتشف PowerShell 5 و 7
#    - يطبع الـtoken مع تنسيق أفضل
# =============================================================

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host " ===========================================================" -ForegroundColor Cyan
Write-Host "  SCT — Simple Crawler Tool" -ForegroundColor Cyan
Write-Host " ===========================================================" -ForegroundColor Cyan
Write-Host ""

# ── 1) اختيار Python: venv (إن وُجدت) ثم النظام ──────────
$pythonExe = $null
if (Test-Path ".venv\Scripts\python.exe") {
    $pythonExe = ".\.venv\Scripts\python.exe"
    Write-Host "[SCT] استعمال venv: .venv\Scripts\python.exe" -ForegroundColor Gray
} else {
    $sysPython = Get-Command python -ErrorAction SilentlyContinue
    if (-not $sysPython) {
        Write-Host "[SCT] ✗ Python غير مثبَّت على هذا الجهاز." -ForegroundColor Red
        Write-Host "       نزّله من: https://www.python.org/downloads/" -ForegroundColor Yellow
        Write-Host "       أو شغّل installer\install.ps1 لإعداد venv معزولة كاملة." -ForegroundColor Yellow
        Write-Host ""
        Read-Host "اضغط Enter للإغلاق"
        exit 1
    }
    $pythonExe = "python"
    Write-Host "[SCT] استعمال Python النظام" -ForegroundColor Gray
}

# ── 2) فحص dependencies (مرّة واحدة عند أوّل تشغيل) ──────
$depCheck = & $pythonExe -c "import fastapi, uvicorn, aiohttp, bs4, yaml" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[SCT] تثبيت المتطلّبات لأوّل مرّة (قد يأخذ دقيقة)..." -ForegroundColor Yellow
    & $pythonExe -m pip install --quiet -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[SCT] ✗ فشل تثبيت المتطلّبات. راجع الخطأ أعلاه." -ForegroundColor Red
        Read-Host "اضغط Enter للإغلاق"
        exit 1
    }
    Write-Host "[SCT] ✓ تمّ تثبيت المتطلّبات." -ForegroundColor Green
}

# ── 3) فتح المتصفّح بعد ثانيتين ──────────────────────────
Write-Host "[SCT] سيُفتح المتصفّح خلال 3 ثوانٍ على http://127.0.0.1:8000" -ForegroundColor Gray
Start-Job -ScriptBlock {
    Start-Sleep -Seconds 3
    Start-Process "http://127.0.0.1:8000"
} | Out-Null

# ── 4) اعرض الـtoken المحلّي إن وُجد ─────────────────────
$tokenPath = Join-Path $env:USERPROFILE ".sct\local_token"
if (Test-Path $tokenPath) {
    $token = (Get-Content $tokenPath -Raw).Trim()
    Write-Host ""
    Write-Host " ───────────────────────────────────────────────────────" -ForegroundColor DarkGray
    Write-Host "  Local token (لـcurl / scripts):" -ForegroundColor Cyan
    Write-Host "  $token" -ForegroundColor White
    Write-Host " ───────────────────────────────────────────────────────" -ForegroundColor DarkGray
}

# ── 5) شغّل الخادم في المقدّمة ─────────────────────────
Write-Host ""
Write-Host "[SCT] الخادم يعمل. اضغط Ctrl+C للإيقاف." -ForegroundColor Green
Write-Host ""
& $pythonExe webapp\run.py --host 127.0.0.1 --port 8000

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[SCT] الخادم توقّف بخطأ. راجع الرسالة أعلاه." -ForegroundColor Red
    Read-Host "اضغط Enter للإغلاق"
}
