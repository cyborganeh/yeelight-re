# Build the Windows deliverables:
#
#   dist\yeelight-re.exe       CLI  (console, onefile)
#   dist\yeelight-re-gui.exe   GUI  (windowed, onefile)
#   dist\yeelight-re-0.3.0-win64.zip
#
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1
#
# PyInstaller is installed in a temporary venv, so the main Python is untouched.
# Requires Python 3.10 through the `py` launcher (PyInstaller on 3.14 may fail).

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$version = "0.3.0"
$venv = Join-Path $env:TEMP "yeelight-re-pyi"
$python = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Creating build venv at $venv"
    py -3.10 -m venv $venv
}

& $python -m pip install -q --upgrade pip
& $python -m pip install -q pyinstaller
& $python tools\make_icon.py

$common = @(
    "--noconfirm", "--clean", "--onefile",
    "--icon", "$root\packaging\yeelight.ico",
    "--version-file", "$root\packaging\version_info.txt",
    "--distpath", "$root\dist",
    "--workpath", "$root\build\pyinstaller",
    "--specpath", "$root\build",
    "--collect-submodules", "yeelight_re"
)

# A previous onefile build may still be running (the bootloader spawns a child,
# so killing only the parent is not enough). Release the files first.
Get-Process yeelight-re, yeelight-re-gui -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500
foreach ($name in "yeelight-re.exe", "yeelight-re-gui.exe") {
    $path = Join-Path $root "dist\$name"
    if (Test-Path $path) { Remove-Item -Force $path }
}

Write-Host "Building CLI executable..."
& $python -m PyInstaller @common --console --name yeelight-re `
    --exclude-module tkinter --exclude-module _tkinter `
    "$root\packaging\launcher.py"
if ($LASTEXITCODE -ne 0) { throw "CLI build failed with exit code $LASTEXITCODE" }

Write-Host "Building GUI executable..."
& $python -m PyInstaller @common --windowed --name yeelight-re-gui `
    --add-data "$root\packaging\yeelight.ico;." `
    "$root\packaging\gui_launcher.py"
if ($LASTEXITCODE -ne 0) { throw "GUI build failed with exit code $LASTEXITCODE" }

$cli = Join-Path $root "dist\yeelight-re.exe"
$gui = Join-Path $root "dist\yeelight-re-gui.exe"
foreach ($path in $cli, $gui) {
    if (-not (Test-Path $path)) { throw "Build failed: $path not found" }
}

$stage = Join-Path $env:TEMP "yeelight-re-dist"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Path $stage | Out-Null
Copy-Item $cli $stage
Copy-Item $gui $stage
Copy-Item (Join-Path $root "packaging\README-EXE.txt") (Join-Path $stage "CARA-PAKAI.txt")

$zip = Join-Path $root "dist\yeelight-re-$version-win64.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip

Get-Item $cli, $gui, $zip | Select-Object Name, Length, LastWriteTime
Write-Host ""
Write-Host "OK. Coba:"
Write-Host "  .\dist\yeelight-re.exe --version"
Write-Host "  .\dist\yeelight-re-gui.exe --ip 192.168.1.20"
