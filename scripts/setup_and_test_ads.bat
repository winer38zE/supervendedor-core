@echo off
setlocal
cd /d "%~dp0.."

echo === Creando venv si no existe ===
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
)

echo === Instalando facebook-business en .venv ===
.venv\Scripts\pip.exe install "facebook-business>=19.0.0"
if errorlevel 1 exit /b 1

echo === Instalando facebook-business en Python activo (uvicorn) ===
python -m pip install "facebook-business>=19.0.0"

echo === Ejecutando ciclo de prueba ===
set FOLLOWUP_SCHEDULER_ENABLED=false
.venv\Scripts\python.exe scripts\run_ads_cycle_test.py

echo.
echo === Opcional: POST /ads/run-cycle ===
curl -s -X POST "http://127.0.0.1:8000/ads/run-cycle" -H "Content-Type: application/json" -d "{\"launch_new_campaign\": false, \"notificar_whatsapp\": false}"

endlocal
