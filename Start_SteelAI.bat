@echo off
setlocal
cd /d "%~dp0"

if not defined STEELAI_PORT set "STEELAI_PORT=8501"
set "STEELAI_URL=http://127.0.0.1:%STEELAI_PORT%"

powershell.exe -NoProfile -Command "try { $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%STEELAI_URL%/_stcore/health'; if ($response.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 (
  echo SteelAI Workbench is already running.
  echo Opening %STEELAI_URL%
  if defined STEELAI_NO_BROWSER exit /b 0
  start "" "%STEELAI_URL%"
  exit /b 0
)

if not exist ".venv\Scripts\python.exe" (
  echo Local Python environment was not found.
  echo Read README.md and install the requirements first.
  pause
  exit /b 1
)

echo Starting SteelAI Workbench at %STEELAI_URL%
echo Keep this window open while using the app.
".venv\Scripts\python.exe" -m streamlit run app.py --server.address=127.0.0.1 --server.port=%STEELAI_PORT% --server.headless=false

if errorlevel 1 (
  echo.
  echo SteelAI stopped with an error. If the port is busy, close the existing app or set STEELAI_PORT to another number.
  pause
)
