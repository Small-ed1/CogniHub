@echo off
echo Router Phase 1 - Windows Setup
echo.

echo Installing Python dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo Failed to install dependencies. Please check Python and pip installation.
    pause
    exit /b 1
)

echo.
echo Setup complete!
echo.
echo Next steps:
echo 1. Install Ollama from https://ollama.ai/
echo 2. Pull models: ollama pull llama3.1
echo 3. Pull embedding model: ollama pull embeddinggemma
echo 4. Start servers: scripts\servers.bat start
echo 5. Run TUI: scripts\run_tui.bat
echo.
echo See README_Windows.md for more details.
echo.
pause