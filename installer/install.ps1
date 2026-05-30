# SCT — مُثبِّت Windows (PowerShell)
# الاستخدام: انقر بزر الفأرة الأيمن > Run with PowerShell
#  (أو من Terminal:  powershell -ExecutionPolicy Bypass -File install.ps1)
#
# ماذا يفعل؟
#   1) يتحقّق من Python 3.10+.
#   2) يُنشئ venv داخل جذر المشروع (.venv) ويُحدّث pip.
#   3) يُثبّت كل المتطلبات من requirements.txt.
#   4) يُثبّت Chromium لـ Playwright (تصيير JS + تقارير PDF).
#   5) يُنشئ اختصارات سطح المكتب وقائمة ابدأ تُشغّل الواجهة المرئية محلياً.
#
# لا يحتاج صلاحيات admin، ولا يكتب سجلّ Windows، ولا يلمس Python النظامي.

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
Write-Host "==> جذر المشروع: $Root"

# 1) فحص Python
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $py) {
    Write-Error "Python غير موجود. ثبّته من https://www.python.org/downloads/ (3.10 أو أحدث) وأعد التشغيل."
}
$ver = (& $py -c "import sys; print('{}.{}'.format(*sys.version_info[:2]))").Trim()
$verNum = [version]$ver
if ($verNum -lt [version]"3.10") {
    Write-Error "Python $ver أقدم من المطلوب (3.10+). حدّث Python."
}
Write-Host "==> Python $ver متاح: $py"

# 2) venv + pip
$venv = Join-Path $Root ".venv"
if (-not (Test-Path $venv)) {
    Write-Host "==> إنشاء venv في .venv …"
    & $py -m venv $venv
}
$venvPy = Join-Path $venv "Scripts\python.exe"
Write-Host "==> ترقية pip …"
& $venvPy -m pip install --upgrade pip | Out-Null

# 3) المتطلبات
Write-Host "==> تثبيت المتطلبات من requirements.txt (قد يستغرق دقائق) …"
& $venvPy -m pip install -r (Join-Path $Root "requirements.txt")

# 4) Playwright Chromium
Write-Host "==> تثبيت Chromium لـ Playwright (لتصيير JS وتقارير PDF) …"
& $venvPy -m playwright install chromium

# 5) اختصارات
$runBat = Join-Path $PSScriptRoot "run.bat"
if (-not (Test-Path $runBat)) {
    Write-Warning "ملف run.bat غير موجود — تخطّي إنشاء الاختصارات."
} else {
    $ws = New-Object -ComObject WScript.Shell
    function New-Shortcut([string]$Path) {
        $sc = $ws.CreateShortcut($Path)
        $sc.TargetPath       = $runBat
        $sc.WorkingDirectory = $Root
        $sc.IconLocation     = "$env:SystemRoot\System32\SHELL32.dll,167"
        $sc.Description      = "SCT — أداة الزحف وتدقيق SEO (محلية)"
        $sc.Save()
    }
    $desktop = [Environment]::GetFolderPath("Desktop")
    $startMenu = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"
    New-Item -ItemType Directory -Force -Path $startMenu | Out-Null
    New-Shortcut (Join-Path $desktop "SCT.lnk")
    New-Shortcut (Join-Path $startMenu "SCT.lnk")
    Write-Host "==> أُنشئت الاختصارات على سطح المكتب وقائمة ابدأ."
}

Write-Host ""
Write-Host "✅ تم التثبيت بنجاح."
Write-Host "   شغّل الأداة بالنقر المزدوج على اختصار SCT، أو بتشغيل installer\run.bat،"
Write-Host "   ثم افتح http://127.0.0.1:8000"
