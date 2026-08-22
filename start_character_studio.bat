@echo off
setlocal
cd /d "%~dp0"
title Character Studio

set "PROJECT_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PROJECT_PYTHON%" set "PROJECT_PYTHON=%~dp0venv\Scripts\python.exe"
if not exist "%PROJECT_PYTHON%" set "PROJECT_PYTHON=python"

rem If it is already open, do not start a duplicate web server.
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 2; if($r.StatusCode -eq 200){exit 0} } catch {}; exit 1"
if not errorlevel 1 (
  echo Character Studio is already running.
  if not defined CHARACTER_STUDIO_NO_BROWSER start "" "http://127.0.0.1:8000/character-studio"
  exit /b 0
)

echo [1/3] Checking local image generator...
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8188/system_stats -TimeoutSec 2; if($r.StatusCode -eq 200){exit 0} } catch {}; exit 1"
if errorlevel 1 (
  echo [2/3] Starting ComfyUI. First startup can take several minutes...
  call "%~dp0start_local_ai.bat"
  if errorlevel 1 (echo ERROR: Local image generator could not start. & pause & exit /b 1)
) else (
  echo [2/3] ComfyUI is already running.
)

"%PROJECT_PYTHON%" -c "import fastapi, uvicorn, pydantic" >nul 2>&1
if errorlevel 1 (
  echo ERROR: The project Python packages are missing.
  echo Run this once: python -m pip install -r requirements.txt
  pause
  exit /b 1
)

echo [3/3] Opening Character Studio at http://127.0.0.1:8000/character-studio
if not defined CHARACTER_STUDIO_NO_BROWSER start "Character Studio Browser" powershell -NoProfile -WindowStyle Hidden -Command "$deadline=(Get-Date).AddMinutes(2); do { try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 2; if($r.StatusCode -eq 200){Start-Process 'http://127.0.0.1:8000/character-studio'; exit} } catch {}; Start-Sleep -Seconds 1 } while((Get-Date)-lt $deadline)"
"%PROJECT_PYTHON%" -m app.main api --host 127.0.0.1 --port 8000

echo Character Studio stopped.
pause
endlocal
