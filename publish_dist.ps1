# Публикация релиза в основной репозиторий news_auto_desktop (он публичный)
# Использование: pwsh -File publish_dist.ps1 [-Version 1.4.0] [-Notes "текст"]
#   [-ZipPath <архив>] [-AssetName <имя.zip>]
# AssetName — имя файла в релизе; по умолчанию KMCBS-News-<версия>.zip.
# Вторая сборка того же релиза (например, 32-битная для Windows 7)
# публикуется со своим AssetName и чужие ассеты не трогает.
param(
    [string]$Version = "1.4.0",
    [string]$Notes = "",
    [string]$ZipPath = "",
    [string]$AssetName = ""
)

$ErrorActionPreference = "Stop"
$srcRepo = "D:\Harness\news_auto_desktop"
$owner = "bakan-off"
$repoName = "news_auto_desktop"
$tag = "v$Version"

if (-not $ZipPath) { $ZipPath = Join-Path $srcRepo "dist\КМЦБС-Новости.zip" }
if (-not (Test-Path $ZipPath)) { throw "Архив не найден: $ZipPath" }

# 1) Токен GitHub из диспетчера учётных данных (на печать не выводится)
$credInput = "protocol=https`nhost=github.com`n`n"
$credLines = $credInput | git credential fill
$token = $null
foreach ($line in $credLines) {
    if ($line -match "^password=(.+)$") { $token = $Matches[1] }
}
if (-not $token) { throw "Не удалось получить токен GitHub из диспетчера учётных данных" }
$headers = @{
    "Authorization" = "Bearer $token"
    "Accept"        = "application/vnd.github+json"
    "User-Agent"    = "KMCBS-News-Publish"
}

# 2) Репозиторий должен существовать и быть публичным (создаём при отсутствии)
try {
    $repoInfo = Invoke-RestMethod -Method Get -Uri "https://api.github.com/repos/$owner/$repoName" -Headers $headers
    if ($repoInfo.private) {
        Invoke-RestMethod -Method Patch -Uri "https://api.github.com/repos/$owner/$repoName" -Headers $headers `
            -ContentType "application/json; charset=utf-8" `
            -Body ([System.Text.Encoding]::UTF8.GetBytes((ConvertTo-Json @{ private = $false }))) | Out-Null
        Write-Host "Репозиторий $owner/$repoName сделан публичным"
    } else {
        Write-Host "Репозиторий $owner/$repoName уже публичный"
    }
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404) {
        Invoke-RestMethod -Method Post -Uri "https://api.github.com/user/repos" -Headers $headers `
            -ContentType "application/json; charset=utf-8" `
            -Body ([System.Text.Encoding]::UTF8.GetBytes((ConvertTo-Json @{
                name = $repoName
                description = "КМЦБС Новости — отправка новостей филиалами (desktop-клиент)"
                private = $false
                has_issues = $true
                has_wiki = $false
            }))) | Out-Null
        Write-Host "Репозиторий $owner/$repoName создан (публичный)"
    } else { throw }
}

# 3) Release с архивом
if (-not $Notes) {
    $Notes = "Программа «КМЦБС Новости», версия $Version. Список изменений — в описании."
}
$relBody = "Программа «КМЦБС Новости», версия $Version.`n`n$Notes"
$release = $null
try {
    $release = Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$owner/$repoName/releases" -Headers $headers `
        -ContentType "application/json; charset=utf-8" `
        -Body ([System.Text.Encoding]::UTF8.GetBytes((ConvertTo-Json @{
            tag_name = $tag
            target_commitish = "main"
            name = $tag
            body = $relBody
        })))
    Write-Host "Release $tag создан"
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 422) {
        Write-Host "Release $tag уже существует — используем существующий"
        $release = Invoke-RestMethod -Method Get -Uri "https://api.github.com/repos/$owner/$repoName/releases/tags/$tag" -Headers $headers
    } else { throw }
}

# имя ассета: ASCII — кириллица в имени файла искажается при загрузке
# через API. Удаляем только ассет С ТЕМ ЖЕ именем (устаревшую версию
# этой же сборки); другие ассеты релиза не трогаем.
if (-not $AssetName) { $AssetName = "KMCBS-News-$Version.zip" }
$assetName = $AssetName
foreach ($a in @($release.assets)) {
    if ($a.name -eq $AssetName) {
        Invoke-RestMethod -Method Delete -Uri $a.url -Headers $headers | Out-Null
    }
}
$uploaded = Invoke-RestMethod -Method Post `
    -Uri "https://uploads.github.com/repos/$owner/$repoName/releases/$($release.id)/assets?name=$assetName" `
    -Headers $headers -InFile $ZipPath -ContentType "application/zip"
Write-Host "Архив загружен: $($uploaded.name) ($([math]::Round($uploaded.size / 1MB, 1)) МБ)"

# 4) Проверка: лента тегов видна анонимно (её же читает программа)
try {
    $atom = Invoke-RestMethod -Method Get -Uri "https://github.com/$owner/$repoName/tags.atom"
    $titles = @($atom.feed.entry | ForEach-Object { $_.title })
    Write-Host "Лента тегов $repoName : $($titles -join ', ')"
} catch {
    Write-Host "Анонимная проверка ленты тегов не удалась: $($_.Exception.Message)"
}
