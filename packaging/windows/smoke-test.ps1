# Checks a built portable folder (build.ps1) the way a user runs it: the CLI makes a script from a test video, the
# app serves its page, and nothing was written outside the folder. The folder has no Python of its own, so -Python
# names one with av and numpy to make the test video (the build's: build.ps1 -KeepVenv leaves it as build-venv).
#   powershell -NoProfile -ExecutionPolicy Bypass -File packaging\windows\smoke-test.ps1 dist\FunscriptGen-<version>-win64 -Python dist\build-venv\Scripts\python.exe
param(
    [Parameter(Mandatory = $true)][string]$App,
    [Parameter(Mandatory = $true)][string]$Python,
    [int]$Port = 17860
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$App = (Resolve-Path $App).Path
$cli = Join-Path $App "funscript-gen.exe"
$py = (Resolve-Path $Python).Path
$work = Join-Path $App "data\tmp\smoke"
New-Item -ItemType Directory -Force $work | Out-Null

# The user's own folders: the build must not add anything to them.
$watched = @($env:USERPROFILE, (Join-Path $env:USERPROFILE ".cache"), $env:APPDATA, $env:LOCALAPPDATA) |
    Where-Object { $_ -and (Test-Path $_) }
function Entries { @(foreach ($d in $watched) { Get-ChildItem -Force -Name $d | ForEach-Object { Join-Path $d $_ } }) }
$before = Entries

Write-Host "== CLI"
& $cli --help | Out-Null
if ($LASTEXITCODE -ne 0) { throw "funscript-gen.exe --help failed ($LASTEXITCODE)" }
$clip = Join-Path $work "clip.mp4"
& $py -I (Join-Path $PSScriptRoot "smoke_clip.py") $clip
if ($LASTEXITCODE -ne 0) { throw "smoke_clip.py failed" }
$script = Join-Path $work "clip.funscript"
& $cli generate $clip --no-ai -o $script
if ($LASTEXITCODE -ne 0) { throw "funscript-gen.exe generate failed ($LASTEXITCODE)" }
$result = [IO.File]::ReadAllText($script) | ConvertFrom-Json
if ($result.actions.Count -lt 4) { throw "the test video gave only $($result.actions.Count) actions" }
Write-Host "   $($result.actions.Count) actions, $($result.metadata.creator)"

Write-Host "== language packs"
$packs = (& $cli lang list) -join "`n"
if ($LASTEXITCODE -ne 0 -or $packs -notmatch "English" -or $packs -notmatch "external") {
    throw "funscript-gen.exe lang list did not find the packs in lang\: $packs"
}
if (-not (Test-Path (Join-Path $App "lang\_template.toml"))) { throw "lang\_template.toml is missing" }
if (-not (Test-Path (Join-Path $App "LICENSE.txt"))) { throw "LICENSE.txt is missing" }
if (-not (Test-Path (Join-Path $App "THIRD_PARTY_NOTICES.md"))) { throw "THIRD_PARTY_NOTICES.md is missing" }
Write-Host "   $((($packs -split "`n") | Where-Object { $_ -match 'external' }).Count) packs in lang\"

Write-Host "== app (server only)"
Start-Process (Join-Path $App "FunscriptGen.exe") -ArgumentList "--ui", "none", "--port", "$Port"
$page = $null
$deadline = (Get-Date).AddSeconds(120)
while (-not $page -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
    try { $page = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 "http://127.0.0.1:$Port/").Content } catch { }
}
Get-CimInstance Win32_Process | Where-Object { $_.Name -eq "FunscriptGen.exe" -and $_.CommandLine -like "*--port $Port*" } |
    ForEach-Object { Stop-Process -Force -Id $_.ProcessId }
if (-not $page) { throw "the app did not answer on port $Port (see data\app.log)" }
if ($page -notmatch "local-video") { throw "the app's page has no local video box" }
if ($page -notmatch "fg-inbox") { throw "the app's page has no drop inbox" }
Write-Host "   page served"

Write-Host "== nothing outside the folder"
$added = @(Entries | Where-Object { $before -notcontains $_ })
if ($added.Count) { throw "written outside the folder: $($added -join ', ')" }
Remove-Item -Recurse -Force $work
Write-Host "== smoke test passed"
