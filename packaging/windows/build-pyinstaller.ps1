# Builds the Windows portable version with PyInstaller (the alternative to build.ps1, which ships a whole Python): a
# folder with FunscriptGen.exe, funscript-gen.exe and _internal\ (about 3,000 files instead of 16,000), and a zip of
# it. Runs on Windows with uv on PATH; PowerShell 5.1 or 7. From the repository root:
#   powershell -NoProfile -ExecutionPolicy Bypass -File packaging\windows\build-pyinstaller.ps1 [-OutDir dist] [-Commit <hash>]
# Result: <OutDir>\FunscriptGen-<version>-win64\ and <OutDir>\FunscriptGen-<version>-win64.zip (+ .sha256), laid out
# for smoke-test.ps1 and the READMEs like the build.ps1 one. -KeepVenv leaves <OutDir>\build\venv for smoke-test.ps1 -Python.
param(
    [string]$OutDir = "dist",
    [string]$Python = "3.12",
    [string]$Commit = "",  # recorded in the scripts' metadata (the build has no git); GitHub Actions passes its SHA
    [string]$PyInstaller = "6.22.3",
    [string]$Hooks = "2026.9",  # pyinstaller-hooks-contrib
    [switch]$NoZip,
    [switch]$KeepVenv
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Run {
    # Runs a native command and stops on a non-zero exit code (PowerShell 5.1 has no $PSNativeCommandUseErrorActionPreference).
    $exe, $rest = $args
    & $exe @rest
    if ($LASTEXITCODE -ne 0) { throw "$exe $($rest -join ' ') failed with exit code $LASTEXITCODE" }
}

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repo
New-Item -ItemType Directory -Force $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path
$work = Join-Path $OutDir "build"
if (Test-Path $work) { Remove-Item -Recurse -Force $work }
New-Item -ItemType Directory -Force $work | Out-Null

# 1. A virtual environment with exactly the versions in uv.lock (with their hashes), then the project as a wheel.
Write-Host "== packages"
$venv = Join-Path $work "venv"
$py = Join-Path $venv "Scripts\python.exe"
Run uv venv $venv --python $Python --quiet
$requirements = Join-Path $work "requirements.txt"
Run uv export --frozen --no-dev --extra gui --no-emit-project --format requirements.txt --output-file $requirements --quiet
# Listed in the lock only because onnxruntime does (see build.ps1); nothing imports them when the program runs.
$unused = @("sympy", "mpmath")
$kept = New-Object System.Collections.Generic.List[string]
$skipping = $false
foreach ($line in (Get-Content $requirements)) {
    if ($line -match '^[A-Za-z0-9]') { $skipping = $unused -contains (($line -split '[=; ]')[0].ToLower()) }
    if (-not $skipping) { $kept.Add($line) }
}
[IO.File]::WriteAllLines($requirements, $kept, (New-Object Text.UTF8Encoding $false))
Run uv pip install --python $py --require-hashes --no-deps --link-mode copy -r $requirements
Run uv pip install --python $py --link-mode copy "pyinstaller==$PyInstaller" "pyinstaller-hooks-contrib==$Hooks"
$wheels = Join-Path $work "wheel"
Run uv build --wheel --out-dir $wheels --quiet
$wheel = Get-ChildItem $wheels -Filter "funscript_gen-*.whl" | Select-Object -First 1
Run uv pip install --python $py --no-deps --link-mode copy $wheel.FullName
$version = (& $py -I -c "import funscript_gen; print(funscript_gen.__version__)").Trim()
if ($Commit) {
    $package = Join-Path $venv "Lib\site-packages\funscript_gen"
    $info = @{ commit = $Commit.Substring(0, [Math]::Min(12, $Commit.Length)); dirty = $false } | ConvertTo-Json -Compress
    [IO.File]::WriteAllText((Join-Path $package "build-info.json"), $info, (New-Object Text.UTF8Encoding $false))
}

# 2. PyInstaller: packaging\windows\pyinstaller\funscript-gen.spec (two exes sharing _internal\).
Write-Host "== PyInstaller"
$spec = Join-Path $PSScriptRoot "pyinstaller\funscript-gen.spec"
$dist = Join-Path $work "dist"
# PyInstaller logs to stderr, which PowerShell 5.1 would turn into errors.
$ErrorActionPreference = "Continue"
& (Join-Path $venv "Scripts\pyinstaller.exe") $spec --noconfirm --clean --log-level WARN --distpath $dist --workpath (Join-Path $work "pyi")
$code = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($code -ne 0) { throw "pyinstaller failed with exit code $code" }
$stage = Join-Path $dist "FunscriptGen"
if (-not (Test-Path (Join-Path $stage "FunscriptGen.exe"))) { throw "PyInstaller did not make FunscriptGen.exe" }

# 3. What sits beside the exes: the readmes, the licences, the language packs (a translation is added by putting a
# .toml file in lang\; entry.py points FUNSCRIPT_GEN_LANG_DIR there).
Copy-Item (Join-Path $PSScriptRoot "README.txt") (Join-Path $stage "README.txt")
Copy-Item (Join-Path $PSScriptRoot "README.zh.txt") (Join-Path $stage "README.zh.txt")
Copy-Item (Join-Path $repo "LICENSE") (Join-Path $stage "LICENSE.txt")
Copy-Item (Join-Path $repo "THIRD_PARTY_NOTICES.md") (Join-Path $stage "THIRD_PARTY_NOTICES.md")
Copy-Item -Recurse (Join-Path $repo "src\funscript_gen\lang") (Join-Path $stage "lang")

# 4. The folder under its release name, and the zip.
$name = "FunscriptGen-$version-win64"
$final = Join-Path $OutDir $name
if (Test-Path $final) { Remove-Item -Recurse -Force $final }
Move-Item $stage $final
if ($KeepVenv) {
    Move-Item $venv (Join-Path $OutDir "build-venv")
}
Remove-Item -Recurse -Force $work
$size = (Get-ChildItem -Recurse -File $final | Measure-Object Length -Sum).Sum
$count = (Get-ChildItem -Recurse -File $final | Measure-Object).Count
Write-Host ("== {0}: {1:N0} MB, {2:N0} files" -f $final, ($size / 1MB), $count)
if (-not $NoZip) {
    $zip = "$final.zip"
    Remove-Item -Force -ErrorAction SilentlyContinue $zip, "$zip.sha256"
    Run tar -a -c -f $zip -C $OutDir $name
    $hash = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
    [IO.File]::WriteAllText("$zip.sha256", "$hash  $name.zip`n", (New-Object Text.UTF8Encoding $false))
    Write-Host ("== {0}: {1:N0} MB, sha256 {2}" -f $zip, ((Get-Item $zip).Length / 1MB), $hash)
}
