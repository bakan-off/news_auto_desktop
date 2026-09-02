# Сборка дистрибутива КМЦБС Новости
#
#   pwsh -File build.ps1   (или ПКМ -> «Выполнить с помощью PowerShell»)
#   pwsh -File build.ps1 -OutDir <пустая папка>
#       — сборка и чистый zip уйдут в указанную папку, dist\ НЕ трогается.
#         Так собирают релиз, когда локальную установку в dist\ трогать
#         нельзя: на ней проверяют обновление из репозитория.
#
# Что делает:
#   1. Сохраняет ваш config.json/app.log из папки сборки (пересборка стирает её)
#   2. Собирает onedir-exe через PyInstaller (иконка, customtkinter,
#      ресурс версии: издатель/название/версия в свойствах exe — из APP_VERSION)
#   3. Возвращает config.json/app.log в локальную папку сборки — чтобы после
#      обновления не проходить вход заново
#   4. Пакует чистый zip — без config.json и app.log: в рассылке личных
#      данных быть не должно; на новой машине программа создаст пустой
#      конфиг при первом запуске
#
# Требования: активированный venv (venv\Scripts\activate) с зависимостями
# из requirements.txt и requirements-dev.txt.

param(
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$appName = "КМЦБС-Новости"
if ($OutDir) {
    # сборка мимо репозитория: dist\ (локальная установка) не трогаем
    if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }
    $distDir = $OutDir
} else {
    $distDir = Join-Path $repo "dist"
}
$appdir = Join-Path $distDir $appName
$zipPath = Join-Path $distDir "$appName.zip"

# Версия из core.py -> ресурс VERSIONINFO в exe (Свойства файла: издатель,
# название, версия). Без него exe «безымянный» в свойствах и диалогах Windows
$verLine = Select-String -Path (Join-Path $repo "core.py") -Pattern 'APP_VERSION\s*=\s*"([\d\.]+)"'
if (-not $verLine) { throw "APP_VERSION не найдена в core.py" }
$appVer = $verLine.Matches[0].Groups[1].Value
$v = @($appVer.Split(".")) + @("0", "0")
$verQuad = ($v[0..3] | ForEach-Object { [int]$_ }) -join ", "
$verTxt = @"
# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($verQuad),
    prodvers=($verQuad),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'041904B0',
        [StringStruct(u'CompanyName', u'МКУК «КМЦБС»'),
        StringStruct(u'FileDescription', u'КМЦБС Новости — отправка новостей филиалами библиотек'),
        StringStruct(u'FileVersion', u'$appVer.0'),
        StringStruct(u'InternalName', u'КМЦБС-Новости'),
        StringStruct(u'LegalCopyright', u'© МКУК «КМЦБС»'),
        StringStruct(u'OriginalFilename', u'КМЦБС-Новости.exe'),
        StringStruct(u'ProductName', u'КМЦБС Новости'),
        StringStruct(u'ProductVersion', u'$appVer')]
      )
    ]),
    VarFileInfo([VarStruct(u'Translation', [1049, 1200])])
  ]
)
"@
$verInfoPath = Join-Path $env:TEMP "nad_version_info.txt"
# UTF-8 БЕЗ BOM: файл читает PyInstaller, BOM ломает разбор
[System.IO.File]::WriteAllText($verInfoPath, $verTxt, [System.Text.UTF8Encoding]::new($false))
Write-Host "== Версия приложения: $appVer (ресурс версии: $verInfoPath)" -ForegroundColor Cyan

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
    # --distpath ОБЯЗАТЕЛЕН: без него PyInstaller собирает в .\dist\ от
    # текущей папки, и -OutDir не работает — сборка уезжает в dist\ и
    # затирает локальную установку (так уже случилось один раз)
    python -m PyInstaller --onedir --noconsole --clean -y `
        --collect-data customtkinter `
        --version-file $verInfoPath `
        --distpath $distDir `
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
if ($OutDir) {
    Write-Host "  сборка (dist\ не тронут):          $appdir"
} else {
    Write-Host "  локальная сборка (с вашим config): $appdir"
}
Write-Host "  архив для рассылки (чистый):       $zipPath"
Write-Host ("  размер архива: {0:N1} МБ" -f ((Get-Item $zipPath).Length / 1MB))
