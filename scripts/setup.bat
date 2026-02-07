@echo off
echo ContextHarbor - Windows Setup
echo.

echo Creating virtual environment...
python -m venv .venv
if %errorlevel% neq 0 (
    echo Failed to create venv. Ensure Python 3.14+ is installed.
    pause
    exit /b 1
)

echo Installing workspace packages...
call .venv\Scripts\python -m pip install -U pip
call .venv\Scripts\python -m pip install -e "packages/ollama_cli[dev]" -e "packages/contextharbor[dev]"
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
echo 3. Pull embedding model: ollama pull nomic-embed-text
echo 4. Start servers: scripts\servers.bat start
echo 5. Run TUI: scripts\run_tui.bat
echo.
echo See docs\README_Windows.md for more details.
echo.
pause
