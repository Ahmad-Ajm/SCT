# =============================================================
#  SCT — One-click launcher (PowerShell)
#
#  Usage:
#    Right-click → "Run with PowerShell"
#    or:        powershell -ExecutionPolicy Bypass -File START.ps1
#
#  Advantages over START.bat:
#    - Colored, clearer messages
#    - Detects PowerShell 5 and 7
#    - Prints the token with better formatting
# =============================================================

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host " ===========================================================" -ForegroundColor Cyan
Write-Host "  SCT — Simple Crawler Tool" -ForegroundColor Cyan
Write-Host " ===========================================================" -ForegroundColor Cyan
Write-Host ""

# ── 1) Pick Python: venv (if present) then system ──────────
$pythonExe = $null
if (Test-Path ".venv\Scripts\python.exe") {
    $pythonExe = ".\.venv\Scripts\python.exe"
    Write-Host "[SCT] using venv: .venv\Scripts\python.exe" -ForegroundColor Gray
} else {
    $sysPython = Get-Command python -ErrorAction SilentlyContinue
    if (-not $sysPython) {
        Write-Host "[SCT] ✗ Python is not installed on this machine." -ForegroundColor Red
        Write-Host "       Download it from: https://www.python.org/downloads/" -ForegroundColor Yellow
        Write-Host "       Or run installer\install.ps1 to set up a fully isolated venv." -ForegroundColor Yellow
        Write-Host ""
        Read-Host "Press Enter to close"
        exit 1
    }
    $pythonExe = "python"
    Write-Host "[SCT] using system Python" -ForegroundColor Gray
}

# ── 2) Dependency check (once on first run) ──────
$depCheck = & $pythonExe -c "import fastapi, uvicorn, aiohttp, bs4, yaml" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[SCT] installing requirements for the first time (may take a minute)..." -ForegroundColor Yellow
    & $pythonExe -m pip install --quiet -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[SCT] ✗ Failed to install requirements. See the error above." -ForegroundColor Red
        Read-Host "Press Enter to close"
        exit 1
    }
    Write-Host "[SCT] ✓ Requirements installed." -ForegroundColor Green
}

# ── 3) Open the browser after a few seconds ──────────────────────────
Write-Host "[SCT] the browser will open in 3 seconds at http://127.0.0.1:8000" -ForegroundColor Gray
Start-Job -ScriptBlock {
    Start-Sleep -Seconds 3
    Start-Process "http://127.0.0.1:8000"
} | Out-Null

# ── 4) Show the local token if present ─────────────────────
$tokenPath = Join-Path $env:USERPROFILE ".sct\local_token"
if (Test-Path $tokenPath) {
    $token = (Get-Content $tokenPath -Raw).Trim()
    Write-Host ""
    Write-Host " ───────────────────────────────────────────────────────" -ForegroundColor DarkGray
    Write-Host "  Local token (for curl / scripts):" -ForegroundColor Cyan
    Write-Host "  $token" -ForegroundColor White
    Write-Host " ───────────────────────────────────────────────────────" -ForegroundColor DarkGray
}

# ── 5) Run the server in the foreground ─────────────────────────
Write-Host ""
Write-Host "[SCT] server running. Press Ctrl+C to stop." -ForegroundColor Green
Write-Host ""
& $pythonExe webapp\run.py --host 127.0.0.1 --port 8000

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[SCT] the server stopped with an error. See the message above." -ForegroundColor Red
    Read-Host "Press Enter to close"
}
