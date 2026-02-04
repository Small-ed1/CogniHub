@echo off
setlocal enabledelayedexpansion

for %%I in ("%~dp0..") do set "APP_DIR=%%~fI"
set "FASTAPI_PID_FILE=%APP_DIR%\fastapi.pid"
set "OLLAMA_PID_FILE=%APP_DIR%\ollama.pid"
set "FASTAPI_LOG=%APP_DIR%\logs\fastapi.log"
set "OLLAMA_LOG=%APP_DIR%\logs\ollama.log"

if not exist "%APP_DIR%\logs" mkdir "%APP_DIR%\logs"

cd /d "%APP_DIR%"

if "%1"=="start" goto start_servers
if "%1"=="stop" goto stop_servers
if "%1"=="restart" goto restart_servers
if "%1"=="status" goto status_servers
if "%1"=="logs" goto logs_servers
goto usage

:start_servers
echo Starting all servers...
call :kill_existing
call :start_ollama
call :wait_for_ollama
if errorlevel 1 goto end
call :start_fastapi
call :wait_for_fastapi
if errorlevel 1 goto end
echo.
echo All servers started successfully!
echo FastAPI: http://localhost:8000
echo Ollama: http://localhost:11434
echo.
echo View logs:
echo   FastAPI: type logs\fastapi.log or powershell Get-Content logs\fastapi.log -Wait
echo   Ollama:  type logs\ollama.log or powershell Get-Content logs\ollama.log -Wait
goto end

:stop_servers
echo Stopping all servers...
call :kill_existing
echo All servers stopped.
goto end

:restart_servers
call :stop_servers
timeout /t 2 >nul
goto start_servers

:status_servers
echo Server status:
call :check_process "%FASTAPI_PID_FILE%" "FastAPI"
call :check_process "%OLLAMA_PID_FILE%" "Ollama"
goto end

:logs_servers
if "%2"=="fastapi" (
    if exist "%FASTAPI_LOG%" (
        powershell Get-Content "%FASTAPI_LOG%" -Wait
    ) else (
        echo No FastAPI log file found
    )
) else if "%2"=="ollama" (
    if exist "%OLLAMA_LOG%" (
        powershell Get-Content "%OLLAMA_LOG%" -Wait
    ) else (
        echo No Ollama log file found
    )
) else (
    echo Usage: %0 logs {fastapi|ollama}
)
goto end

:usage
echo Usage: %0 {start^|stop^|restart^|status^|logs}
echo.
echo Commands:
echo   start    - Start all servers in background
echo   stop     - Stop all servers
echo   restart  - Restart all servers
echo   status   - Show server status
echo   logs     - View logs (fastapi^|ollama)
goto end

:kill_existing
call :kill_pidfile "%FASTAPI_PID_FILE%" "FastAPI"
call :kill_pidfile "%OLLAMA_PID_FILE%" "Ollama"
goto :eof

:kill_pidfile
set "pidfile=%~1"
set "name=%~2"
if exist "%pidfile%" (
    set /p pid=<"%pidfile%"
    if defined pid (
        tasklist /FI "PID eq !pid!" 2>nul | find /i "!pid!" >nul
        if !errorlevel! equ 0 (
            echo Stopping %name% (PID: !pid!)
            taskkill /PID !pid! /T >nul 2>&1
            timeout /t 1 >nul
            tasklist /FI "PID eq !pid!" 2>nul | find /i "!pid!" >nul
            if !errorlevel! equ 0 (
                taskkill /PID !pid! /T /F >nul 2>&1
            )
        )
    )
    del /q "%pidfile%" 2>nul
)
goto :eof

:start_ollama
echo Starting Ollama...
start /b cmd /c "ollama serve > ""%OLLAMA_LOG%"" 2>&1"
timeout /t 2 >nul
for /f "tokens=2" %%i in ('tasklist /FI "IMAGENAME eq ollama.exe" /NH') do set OLLAMA_PID=%%i
if defined OLLAMA_PID (
    echo !OLLAMA_PID! > "%OLLAMA_PID_FILE%"
    echo Ollama started (PID: !OLLAMA_PID!), logging to %OLLAMA_LOG%
) else (
    echo Failed to start Ollama
)
goto :eof

:start_fastapi
echo Starting FastAPI...
start /b cmd /c "uvicorn cognihub.app:app --host 0.0.0.0 --port 8000 > ""%FASTAPI_LOG%"" 2>&1"
timeout /t 2 >nul
for /f "tokens=2" %%i in ('tasklist /FI "IMAGENAME eq uvicorn.exe" /NH') do set FASTAPI_PID=%%i
if defined FASTAPI_PID (
    echo !FASTAPI_PID! > "%FASTAPI_PID_FILE%"
    echo FastAPI started (PID: !FASTAPI_PID!), logging to %FASTAPI_LOG%
) else (
    echo Failed to start FastAPI
)
goto :eof

:wait_for_ollama
echo Waiting for Ollama to be ready...
for /l %%i in (1,1,30) do (
    curl -s http://localhost:11434/api/version >nul 2>&1
    if !errorlevel! equ 0 (
        echo Ollama is ready!
        goto :eof
    )
    timeout /t 1 >nul
)
echo Ollama failed to start in time. Check %OLLAMA_LOG%
exit /b 1
goto :eof

:wait_for_fastapi
echo Waiting for FastAPI to be ready...
for /l %%i in (1,1,30) do (
    curl -s http://localhost:8000/health >nul 2>&1
    if !errorlevel! equ 0 (
        echo FastAPI is ready!
        goto :eof
    )
    timeout /t 1 >nul
)
echo FastAPI failed to start in time. Check %FASTAPI_LOG%
exit /b 1
goto :eof

:check_process
set "pidfile=%~1"
set "name=%~2"
if exist "%pidfile%" (
    set /p pid=<"%pidfile%"
    if defined pid (
        tasklist /FI "PID eq !pid!" 2>nul | find /i "!pid!" >nul
        if !errorlevel! equ 0 (
            echo %name%: RUNNING (PID: !pid!)
        ) else (
            echo %name%: NOT RUNNING (stale PID file)
        )
    ) else (
        echo %name%: NOT RUNNING
    )
) else (
    echo %name%: NOT RUNNING
)
goto :eof

:end
