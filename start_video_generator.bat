@echo off
setlocal
cd /d "%~dp0"
title AI Video Director

set "PROJECT_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PROJECT_PYTHON%" set "PROJECT_PYTHON=%~dp0venv\Scripts\python.exe"
if not exist "%PROJECT_PYTHON%" set "PROJECT_PYTHON=python"

rem Reuse only a server that actually exposes the AI Video Director routes.
powershell -NoProfile -Command "try { $api=Invoke-RestMethod http://127.0.0.1:8000/openapi.json -TimeoutSec 2; if($api.paths.PSObject.Properties.Name -contains '/api/director/videos'){exit 0} } catch {}; exit 1"
if not errorlevel 1 (
  echo AI Video Director is already running.
  start "" "http://127.0.0.1:8000/"
  exit /b 0
)

rem Do not silently open a stale/other application that owns the required port.
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if not errorlevel 1 (
  echo ERROR: Port 8000 is occupied by an older or different application.
  echo Close its terminal window, then run start_video_generator.bat again.
  pause
  exit /b 1
)

echo [1/4] Checking Ollama...
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:11434/api/tags -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 start "Ollama" /min ollama serve

echo [2/4] Checking local image generator...
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8188/system_stats -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 call "%~dp0start_local_ai.bat"
if errorlevel 1 (echo ERROR: Local image generation could not start. & pause & exit /b 1)

echo [3/4] Checking application dependencies...
"%PROJECT_PYTHON%" -c "import fastapi, uvicorn, pydantic" >nul 2>&1
if errorlevel 1 (echo ERROR: Run python -m pip install -r requirements.txt & pause & exit /b 1)

echo [4/4] Opening AI Video Director at http://127.0.0.1:8000/
start "AI Video Director Browser" powershell -NoProfile -WindowStyle Hidden -Command "$deadline=(Get-Date).AddMinutes(2); do { try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 2 | Out-Null; Start-Process 'http://127.0.0.1:8000/'; exit } catch {}; Start-Sleep -Seconds 1 } while((Get-Date)-lt $deadline)"
"%PROJECT_PYTHON%" -m app.main api --host 127.0.0.1 --port 8000

echo AI Video Director stopped.
pause
endlocal
