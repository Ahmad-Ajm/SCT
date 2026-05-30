# SCT — مُلغي تثبيت Windows
# يحذف اختصارات SCT و venv (لا يلمس البيانات في webapp_jobs).
$ErrorActionPreference = "Continue"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Write-Host "==> إزالة اختصارات SCT …"
$desktop = Join-Path ([Environment]::GetFolderPath("Desktop")) "SCT.lnk"
$startMenu = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\SCT.lnk"
foreach ($p in @($desktop, $startMenu)) {
    if (Test-Path $p) { Remove-Item -Force $p; Write-Host "  حُذف: $p" }
}
$venv = Join-Path $Root ".venv"
if (Test-Path $venv) {
    Write-Host "==> إزالة .venv …"
    Remove-Item -Recurse -Force $venv
}
Write-Host "✅ تمّت الإزالة. ملفّات المهام في webapp_jobs لم تُمَس."
