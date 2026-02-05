# Windows CI Build Script for TD Launcher Plus
# This script is designed for GitHub Actions and standard Python environments

$ErrorActionPreference = "Stop"

Write-Host "Building TD Launcher Plus for Windows (CI)..."

# 1. Clean previous builds
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }

# 2. Run PyInstaller
Write-Host "Running PyInstaller..."
& pyinstaller --noconfirm --log-level=WARN `
    --onefile --nowindow `
    --windowed `
    --name="td_launcher_plus" `
    --icon="td_launcher_plus.ico" `
    --add-binary="toeexpand/toeexpand.exe;toeexpand" `
    --add-binary="test.toe;." `
    --add-binary="toeexpand/iconv.dll;toeexpand" `
    --add-binary="toeexpand/icudt59.dll;toeexpand" `
    --add-binary="toeexpand/icuuc59.dll;toeexpand" `
    --add-binary="toeexpand/libcurl.dll;toeexpand" `
    --add-binary="toeexpand/libcurl-x64.dll;toeexpand" `
    --add-binary="toeexpand/zlib1.dll;toeexpand" `
    .\td_launcher.py

# 3. Compile Inno Setup
$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
    Write-Host "Compiling Inno Setup Installer..."
    & $iscc inno\TD_Launcher_Inno_Compiler.iss
} else {
    Write-Warning "Inno Setup (ISCC.exe) not found. Skipping installer creation."
}

Write-Host "`nBuild Summary:"
Write-Host "=============="
Write-Host "Executable: dist\td_launcher_plus.exe"
if (Test-Path "inno\Output") {
    $installer = Get-ChildItem "inno\Output\*.exe" | Select-Object -First 1
    if ($installer) {
        Write-Host "Installer: $($installer.FullName)"
    }
}
