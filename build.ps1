# Сборка дистрибутива КМЦБС Новости
#
#   pwsh -File build.ps1   (или ПКМ -> «Выполнить с помощью PowerShell»)
#
# Что делает:
#   1. Сохраняет ваш config.json/app.log из папки сборки (пересборка стирает её)
#   2. Собирает onedir-exe через PyInstaller (иконка, customtkinter)
#   3. Возвращает config.json/app.log в локальную папку сборки — чтобы после
#      обновления не проходить вход заново
#   4. Пакует dist\КМЦБС-Новости.zip — ЧИСТУЮ сборку без config.json и
#      app.log: в рассылке личных данных быть не должно; на новой машине
#      программа создаст пустой конфиг при первом запуске
#
# Требования: активированный venv (venv\Scripts\activate) с зависимостями
# из requirements.txt и requirements-dev.txt.

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$appName = "КМЦБС-Новости"
$distDir = Join-Path $repo "dist"
$appdir = Join-Path $distDir $appName
$zipPath = Join-Path $distDir "$appName.zip"

# 1) Личные файлы пользователя сохраняем (PyInstaller -y стирает папку)
$keepDir = Join-Path $env:TEMP "nad_keep_personal"
if (Test-Path $keepDir) { Remove-Item $keepDir -Recurse -Force }
New-Item -ItemType Directory -Path $keepDir | Out-Null
foreach ($f in "config.json", "app.log") {
    $p = Join-Path $appdir $f
    if (Test-Path $p) { Copy-Item $p (Join-Path $keepDir $f) -Force }
}

Write-Host "== Сборка exe..." -ForegroundColor Cyan
# Вывод PyInstaller пишем в лог. На время вызова ослабляем Stop-политику:
# каждая строка stderr сборщика оборачивается в ErrorRecord, и при
# ErrorActionPreference=Stop она становится терминальной ошибкой скрипта
$buildLog = Join-Path $repo "build_pyinstaller.log"
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    python -m PyInstaller --onedir --noconsole --clean -y `
        --collect-data customtkinter `
        --icon app.ico --add-data "app.ico;." `
        --name $appName main.py *> $buildLog
    $pyCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $prevEap
}
if ($pyCode -ne 0) {
    Get-Content $buildLog -Tail 15
    throw "PyInstaller упал с кодом $pyCode"
}

# 2) Возвращаем личные файлы в ЛОКАЛЬНУЮ папку сборки (для тестирования)
foreach ($f in "config.json", "app.log") {
    $p = Join-Path $keepDir $f
    if (Test-Path $p) { Copy-Item $p (Join-Path $appdir $f) -Force }
}
Remove-Item $keepDir -Recurse -Force

# 3) Чистый zip: копия сборки в staging-папку с исходным именем,
#    без config.json/app.log и кэша проверки обновлений
Write-Host "== Упаковка чистого архива..." -ForegroundColor Cyan
$stage = Join-Path $env:TEMP "nad_stage"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null
Copy-Item $appdir (Join-Path $stage $appName) -Recurse
$cleanApp = Join-Path $stage $appName
foreach ($f in "config.json", "app.log", ".update_cache.json", "config.json.tmp", "app.log.tmp") {
    Remove-Item (Join-Path $cleanApp $f) -Force -ErrorAction SilentlyContinue
}
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path $cleanApp -DestinationPath $zipPath -Force
Remove-Item $stage -Recurse -Force

Write-Host ""
Write-Host "Готово:" -ForegroundColor Green
Write-Host "  локальная сборка (с вашим config): $appdir"
Write-Host "  архив для рассылки (чистый):       $zipPath"
Write-Host ("  размер архива: {0:N1} МБ" -f ((Get-Item $zipPath).Length / 1MB))
