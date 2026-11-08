# Builds the Windows portable version: a folder with its own Python, every package (versions from uv.lock), the two
# launchers, and a zip of it. Runs on Windows with uv on PATH (GitHub Actions' windows runner, or the test host);
# PowerShell 5.1 or 7. From the repository root:
#   powershell -NoProfile -ExecutionPolicy Bypass -File packaging\windows\build.ps1 [-OutDir dist] [-Commit <hash>]
# Result: <OutDir>\FunscriptGen-<version>-win64\ and <OutDir>\FunscriptGen-<version>-win64.zip (+ .sha256).
param(
    [string]$OutDir = "dist",
    [string]$Python = "3.12",
    [string]$Commit = "",  # recorded in the scripts' metadata (the build has no git); GitHub Actions passes its SHA
    [switch]$NoZip
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Run {
    # Runs a native command and stops on a non-zero exit code (PowerShell 5.1 has no $PSNativeCommandUseErrorActionPreference).
    # A simple function (no param block), so arguments such as -f reach the command instead of binding to Run.
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

# 1. Python: uv's standalone build (python-build-standalone), which runs from any folder.
Write-Host "== Python $Python"
Run uv python install $Python --install-dir (Join-Path $work "python") --no-bin
$installed = Get-ChildItem (Join-Path $work "python") -Directory | Where-Object Name -like "cpython-*-windows-x86_64-*" |
    Select-Object -First 1
if (-not $installed) { throw "uv did not install Python $Python" }
$stage = Join-Path $work "app"
$runtime = Join-Path $stage "runtime"
New-Item -ItemType Directory -Force $stage | Out-Null
Copy-Item -Recurse $installed.FullName $runtime
# uv marks its Pythons as managed by uv; this copy is the app's own.
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $runtime "Lib\EXTERNALLY-MANAGED")
$py = Join-Path $runtime "python.exe"

# 2. Packages: exactly the versions in uv.lock (with their hashes), then the project itself as a wheel.
Write-Host "== packages"
$requirements = Join-Path $work "requirements.txt"
Run uv export --frozen --no-dev --extra gui --no-emit-project --format requirements.txt --output-file $requirements --quiet
# Packages that are in the lock only because another one lists them, and that nothing imports when the program runs:
# onnxruntime lists sympy (and so mpmath), which only onnxruntime.tools.symbolic_shape_infer uses.
$unused = @("sympy", "mpmath")
$kept = New-Object System.Collections.Generic.List[string]
$skipping = $false
foreach ($line in (Get-Content $requirements)) {
    if ($line -match '^[A-Za-z0-9]') { $skipping = $unused -contains (($line -split '[=; ]')[0].ToLower()) }
    if (-not $skipping) { $kept.Add($line) }
}
[IO.File]::WriteAllLines($requirements, $kept, (New-Object Text.UTF8Encoding $false))
# The export already lists every dependency, so nothing is resolved again (--no-deps) and the unused ones stay out.
Run uv pip install --python $py --require-hashes --no-deps --compile-bytecode --link-mode copy -r $requirements
$wheels = Join-Path $work "wheel"
Run uv build --wheel --out-dir $wheels --quiet
$wheel = Get-ChildItem $wheels -Filter "funscript_gen-*.whl" | Select-Object -First 1
Run uv pip install --python $py --no-deps --compile-bytecode --link-mode copy $wheel.FullName
$version = (& $py -I -c "import funscript_gen; print(funscript_gen.__version__)").Trim()
if ($Commit) {
    $package = Join-Path $runtime "Lib\site-packages\funscript_gen"
    $info = @{ commit = $Commit.Substring(0, [Math]::Min(12, $Commit.Length)); dirty = $false } | ConvertTo-Json -Compress
    [IO.File]::WriteAllText((Join-Path $package "build-info.json"), $info, (New-Object Text.UTF8Encoding $false))
}

# 2b. A user's copy, not a developer's: fewer files (a fresh copy was 28,000: extracting it and starting it for the
# first time is slow, above all with a virus scanner reading each one). Only what the program never loads is removed:
# the packages' test suites and type stubs, pip, the console-script exes in Scripts\ (they point at the build folder),
# Tcl/Tk (nothing here uses tkinter: matplotlib draws with Agg, the window is WebView2), what is for compiling or
# converting (C headers, import libraries, Cython files, onnxruntime's model tools; not numpy.f2py: scipy touches it), and Gradio's
# server-side-rendering node app (SSR is off). Gradio's own .pyi files stay: it writes them next to its components'
# sources on every import (component_meta.py), and a missing one is made again. The .py files stay too: Gradio reads them.
Write-Host "== pruning"
$site = Join-Path $runtime "Lib\site-packages"
function Prune([string[]]$Paths) {
    foreach ($p in $Paths) { if (Test-Path $p) { Remove-Item -Recurse -Force $p } }
}
$before = (Get-ChildItem -Recurse -File -Force $runtime | Measure-Object).Count
Prune @(
    (Join-Path $runtime "tcl"), (Join-Path $runtime "include"), (Join-Path $runtime "libs"),
    (Join-Path $runtime "DLLs\_tkinter.pyd"), (Join-Path $runtime "DLLs\tcl86t.dll"), (Join-Path $runtime "DLLs\tk86t.dll"),
    (Join-Path $runtime "Lib\tkinter"), (Join-Path $runtime "Lib\idlelib"), (Join-Path $runtime "Lib\turtledemo"),
    (Join-Path $runtime "Lib\lib2to3"), (Join-Path $runtime "Lib\ensurepip"), (Join-Path $runtime "Lib\pydoc_data"),
    (Join-Path $runtime "Lib\test"), (Join-Path $site "pip"), (Join-Path $site "matplotlib\mpl-data\sample_data"),
    (Join-Path $site "gradio\templates\node"), (Join-Path $runtime "Scripts"),
    (Join-Path $site "onnxruntime\tools"), (Join-Path $site "onnxruntime\quantization"),
    (Join-Path $site "onnxruntime\transformers"), (Join-Path $site "onnxruntime\datasets")
)
Get-ChildItem $site -Filter "pip-*.dist-info" -Directory | ForEach-Object { Remove-Item -Recurse -Force $_.FullName }
# The packages' own tests (never the testing helpers, such as numpy.testing, which other packages import).
Get-ChildItem $site -Recurse -Directory -Force | Where-Object { $_.Name -in @("tests", "test") } |
    Sort-Object { $_.FullName.Length } | ForEach-Object { if (Test-Path $_.FullName) { Remove-Item -Recurse -Force $_.FullName } }
$gradio = Join-Path $site "gradio"
$compile = @(".h", ".hpp", ".c", ".cc", ".cpp", ".pxd", ".pyx", ".f90", ".lib", ".a")
Get-ChildItem $site -Recurse -File -Force | Where-Object {
    $_.Extension -in $compile -or $_.Name -eq "py.typed" -or ($_.Extension -eq ".pyi" -and -not $_.FullName.StartsWith($gradio))
} | ForEach-Object { Remove-Item -Force $_.FullName }
$after = (Get-ChildItem -Recurse -File -Force $runtime | Measure-Object).Count
Write-Host ("   {0:N0} -> {1:N0} files in runtime\" -f $before, $after)

# 3. Launchers: compiled with the C# compiler that comes with Windows' .NET Framework 4.
Write-Host "== launchers"
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$source = Join-Path $PSScriptRoot "launcher.cs"
Run $csc /nologo /codepage:65001 /optimize+ /target:exe "/out:$(Join-Path $stage 'funscript-gen.exe')" $source
Run $csc /nologo /codepage:65001 /optimize+ /target:winexe /define:GUI /reference:System.Windows.Forms.dll `
    "/out:$(Join-Path $stage 'FunscriptGen.exe')" $source
Copy-Item (Join-Path $PSScriptRoot "README.txt") (Join-Path $stage "README.txt")
Copy-Item (Join-Path $PSScriptRoot "README.zh.txt") (Join-Path $stage "README.zh.txt")
Copy-Item (Join-Path $repo "LICENSE") (Join-Path $stage "LICENSE.txt")
Copy-Item (Join-Path $repo "THIRD_PARTY_NOTICES.md") (Join-Path $stage "THIRD_PARTY_NOTICES.md")

# The language packs (zh-TW, en and the template) beside the exe: the launchers point FUNSCRIPT_GEN_LANG_DIR here, so a
# translation is added by putting a .toml file in lang\ (the same files are also inside the package as built-in packs).
Write-Host "== language packs"
Copy-Item -Recurse (Join-Path $repo "src\funscript_gen\lang") (Join-Path $stage "lang")

# 4. The folder under its release name, and the zip.
$name = "FunscriptGen-$version-win64"
$final = Join-Path $OutDir $name
if (Test-Path $final) { Remove-Item -Recurse -Force $final }
Move-Item $stage $final
Remove-Item -Recurse -Force $work
$size = (Get-ChildItem -Recurse -File $final | Measure-Object Length -Sum).Sum
Write-Host ("== {0}: {1:N0} MB" -f $final, ($size / 1MB))
if (-not $NoZip) {
    $zip = "$final.zip"
    Remove-Item -Force -ErrorAction SilentlyContinue $zip, "$zip.sha256"
    Run tar -a -c -f $zip -C $OutDir $name
    $hash = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
    [IO.File]::WriteAllText("$zip.sha256", "$hash  $name.zip`n", (New-Object Text.UTF8Encoding $false))
    Write-Host ("== {0}: {1:N0} MB, sha256 {2}" -f $zip, ((Get-Item $zip).Length / 1MB), $hash)
}
