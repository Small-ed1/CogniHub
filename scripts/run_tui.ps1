$AppDir = Split-Path -Parent $PSCommandPath
$AppDir = Split-Path -Parent $AppDir  # Go up to project root
$VenvTui = Join-Path $AppDir ".venv\Scripts\cognihub-tui.exe"

# Check if API is running
try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 5 -ErrorAction Stop
} catch {
    Write-Host "Warning: API server may not be running."
    Write-Host "Start with: .\scripts\servers.ps1 start"
    Write-Host "Or run manually: uvicorn cognihub.app:app"
    Write-Host ""
}

# Run TUI
if (Test-Path $VenvTui) {
    & $VenvTui
} else {
    Write-Host "Virtual environment not found. Create it with:"
    Write-Host "  python -m venv .venv"
    Write-Host "  .venv\Scripts\Activate.ps1"
    Write-Host "  python -m pip install -e \"packages/ollama_cli[dev]\" -e \"packages/cognihub[dev]\""
}
