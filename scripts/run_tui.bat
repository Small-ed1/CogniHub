@echo off
for %%I in ("%~dp0..") do set "APP_DIR=%%~fI"
cd /d "%APP_DIR%"

REM Check if API is running
curl -sf http://127.0.0.1:8000/health >nul 2>&1
if %errorlevel% neq 0 (
    echo Warning: API server may not be running.
    echo Start with: scripts\servers.bat start
    echo Or run manually: uvicorn cognihub.app:app
    echo.
)

REM Run TUI
if exist ".venv\Scripts\cognihub-tui.exe" (
    call ".venv\Scripts\cognihub-tui.exe"
) else (
    echo Virtual environment not found. Create it with:
    echo   python -m venv .venv
    echo   .venv\Scripts\activate.bat
    echo   python -m pip install -e "packages/ollama_cli[dev]" -e "packages/cognihub[dev]"
)
