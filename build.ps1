# Build script to update frontend from SasyndevCONTROL and recompile EXE
$ErrorActionPreference = "Stop"

Write-Host "1. Building SasyndevCONTROL Vite frontend..." -ForegroundColor Cyan
Push-Location "D:\projects\bgmi\SasyndevCONTROL"
npm run build
Pop-Location

Write-Host "2. Cleaning and updating dist in Rust project..." -ForegroundColor Cyan
if (Test-Path ".\dist") {
    Remove-Item -Recurse -Force ".\dist"
}
New-Item -ItemType Directory -Path ".\dist" | Out-Null
Copy-Item -Recurse -Force "D:\projects\bgmi\SasyndevCONTROL\dist\*" ".\dist\"

Write-Host "3. Cleaning Rust package cache to force re-embedding of dist..." -ForegroundColor Cyan
cargo clean -p sasyndev_control

Write-Host "4. Compiling standalone EXE with embedded website..." -ForegroundColor Cyan
cargo build --release

Copy-Item .\target\release\SasyndevCONTROL.exe .\SasyndevCONTROL.exe -Force
Write-Host "Done! SasyndevCONTROL.exe updated successfully." -ForegroundColor Green
