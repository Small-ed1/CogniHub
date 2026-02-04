param(
    [string]$Action = "start"
)

$AppDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$FastApiPidFile = Join-Path $AppDir "fastapi.pid"
$OllamaPidFile = Join-Path $AppDir "ollama.pid"
$FastApiLog = Join-Path $AppDir "logs\fastapi.log"
$OllamaLog = Join-Path $AppDir "logs\ollama.log"
$EnvFile = Join-Path $AppDir ".env"
$VenvPython = Join-Path $AppDir ".venv\Scripts\python.exe"
$PythonExe = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

New-Item -ItemType Directory -Force -Path (Join-Path $AppDir "logs") | Out-Null

function Kill-PidFile {
    param($PidFile, $Name)
    if (Test-Path $PidFile) {
        $processId = Get-Content $PidFile -ErrorAction SilentlyContinue
        if ($processId -and (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
            Write-Host "Stopping $Name (PID: $processId)"
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
            if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
                Stop-Process -Id $processId -Force
            }
        }
        Remove-Item $PidFile -ErrorAction SilentlyContinue
    }
}

function Kill-Existing {
    Kill-PidFile $FastApiPidFile "FastAPI"
    Kill-PidFile $OllamaPidFile "Ollama"
}

function Start-Ollama {
    Write-Host "Starting Ollama..."
    $process = Start-Process -WorkingDirectory $AppDir -FilePath "cmd" -ArgumentList "/c", "ollama serve >> $OllamaLog 2>&1" -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 2
    $ollamaPid = Get-Process -Name "ollama" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Id
    if ($ollamaPid) {
        $ollamaPid | Out-File $OllamaPidFile
        Write-Host "Ollama started (PID: $ollamaPid), logging to $OllamaLog"
    } else {
        Write-Host "Failed to find Ollama process"
    }
}

function Start-FastApi {
    Write-Host "Starting FastAPI..."
    $envArg = if (Test-Path $EnvFile) { "--env-file .env" } else { "" }
    $cmd = "\"$PythonExe\" -m uvicorn cognihub.app:app --host 0.0.0.0 --port 8000 $envArg >> $FastApiLog 2>&1"
    $process = Start-Process -WorkingDirectory $AppDir -FilePath "cmd" -ArgumentList "/c", $cmd -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 2
    $fastapiPid = Get-Process -Name "python" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Id
    if ($fastapiPid) {
        $fastapiPid | Out-File $FastApiPidFile
        Write-Host "FastAPI started (PID: $fastapiPid), logging to $FastApiLog"
    } else {
        Write-Host "Failed to find FastAPI process"
    }
}

function Wait-ForOllama {
    Write-Host "Waiting for Ollama to be ready..."
    for ($i = 1; $i -le 30; $i++) {
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:11434/api/version" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
            Write-Host "Ollama is ready!"
            return $true
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    Write-Host "Ollama failed to start in time. Check $OllamaLog"
    return $false
}

function Wait-ForFastApi {
    Write-Host "Waiting for FastAPI to be ready..."
    for ($i = 1; $i -le 30; $i++) {
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
            Write-Host "FastAPI is ready!"
            return $true
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    Write-Host "FastAPI failed to start in time. Check $FastApiLog"
    return $false
}

switch ($Action) {
    "start" {
        Write-Host "Starting all servers..."
        Kill-Existing
        Start-Ollama
        if (-not (Wait-ForOllama)) { exit 1 }
        Start-FastApi
        if (-not (Wait-ForFastApi)) { exit 1 }
        Write-Host ""
        Write-Host "All servers started successfully!"
        Write-Host "FastAPI: http://localhost:8000"
        Write-Host "Ollama: http://localhost:11434"
        Write-Host ""
        Write-Host "View logs:"
        Write-Host "  FastAPI: Get-Content logs\fastapi.log -Wait"
        Write-Host "  Ollama:  Get-Content logs\ollama.log -Wait"
    }
    "stop" {
        Write-Host "Stopping all servers..."
        Kill-Existing
        Write-Host "All servers stopped."
    }
    "restart" {
        & $PSCommandPath -Action stop
        Start-Sleep -Seconds 2
        & $PSCommandPath -Action start
    }
    "status" {
        Write-Host "Server status:"
        if (Test-Path $FastApiPidFile) {
            $processId = Get-Content $FastApiPidFile
            if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
                Write-Host "FastAPI: RUNNING (PID: $processId)"
            } else {
                Write-Host "FastAPI: NOT RUNNING (stale PID file)"
            }
        } else {
            Write-Host "FastAPI: NOT RUNNING"
        }

        if (Test-Path $OllamaPidFile) {
            $processId = Get-Content $OllamaPidFile
            if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
                Write-Host "Ollama: RUNNING (PID: $processId)"
            } else {
                Write-Host "Ollama: NOT RUNNING (stale PID file)"
            }
        } else {
            Write-Host "Ollama: NOT RUNNING"
        }
    }
    "logs" {
        if ($args[1] -eq "fastapi") {
            if (Test-Path $FastApiLog) {
                Get-Content $FastApiLog -Wait
            } else {
                Write-Host "No FastAPI log file found"
            }
        } elseif ($args[1] -eq "ollama") {
            if (Test-Path $OllamaLog) {
                Get-Content $OllamaLog -Wait
            } else {
                Write-Host "No Ollama log file found"
            }
        } else {
            Write-Host "Usage: $($PSCommandPath) logs {fastapi|ollama}"
        }
    }
    default {
        Write-Host "Usage: $($PSCommandPath) {start|stop|restart|status|logs}"
        Write-Host ""
        Write-Host "Commands:"
        Write-Host "  start    - Start all servers in background"
        Write-Host "  stop     - Stop all servers"
        Write-Host "  restart  - Restart all servers"
        Write-Host "  status   - Show server status"
        Write-Host "  logs     - View logs (fastapi|ollama)"
    }
}
