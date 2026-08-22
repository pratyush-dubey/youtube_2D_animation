@echo off
setlocal
set "AI_ROOT=D:\AI_VIDEO_GENERATOR"
set "COMFY_ROOT=%AI_ROOT%\ComfyUI"
set "PYTHON_EXE=%AI_ROOT%\venvs\comfyui\Scripts\python.exe"
set "MODEL=%AI_ROOT%\models\checkpoints\DreamShaper_8_pruned.safetensors"

if not exist "%PYTHON_EXE%" (echo ERROR: Python environment missing at %PYTHON_EXE% & exit /b 1)
if not exist "%COMFY_ROOT%\main.py" (echo ERROR: ComfyUI missing at %COMFY_ROOT% & exit /b 1)
if not exist "%MODEL%" (echo ERROR: model missing at %MODEL% & exit /b 1)

rem Do not launch a second copy when ComfyUI is already healthy.
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8188/system_stats -TimeoutSec 3; if($r.StatusCode -eq 200){exit 0} } catch {}; exit 1"
if not errorlevel 1 (
  echo ComfyUI is already healthy: http://127.0.0.1:8188
  exit /b 0
)

echo Starting local ComfyUI with the benchmarked CPU backend at http://127.0.0.1:8188
start "ComfyUI Local" /min "%PYTHON_EXE%" "%COMFY_ROOT%\main.py" --cpu --cpu-vae --listen 127.0.0.1 --port 8188 --extra-model-paths-config "%AI_ROOT%\extra_model_paths.yaml" --input-directory "%AI_ROOT%\input" --output-directory "%AI_ROOT%\output" --temp-directory "%AI_ROOT%\temp" --user-directory "%AI_ROOT%\user" --disable-auto-launch

powershell -NoProfile -Command "$deadline=(Get-Date).AddMinutes(5); do { try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8188/system_stats -TimeoutSec 3; if($r.StatusCode -eq 200){ exit 0 } } catch {}; Start-Sleep -Seconds 2 } while((Get-Date)-lt $deadline); exit 1"
if errorlevel 1 (echo ERROR: ComfyUI did not become healthy within 5 minutes. Review the ComfyUI Local window for the exact error. & exit /b 1)
echo ComfyUI is healthy: http://127.0.0.1:8188
endlocal
