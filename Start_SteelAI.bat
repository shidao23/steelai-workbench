@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0config\local-tools.cmd" call "%~dp0config\local-tools.cmd"
if not defined STEELAI_PYTHON set "STEELAI_PYTHON=%~dp0.venv\Scripts\python.exe"

if not defined STEELAI_PORT set "STEELAI_PORT=8501"
set "STEELAI_URL=http://127.0.0.1:%STEELAI_PORT%"

rem Loopback instance probe. It runs in scripts\check_local_streamlit_health.ps1
rem because Windows PowerShell 5.1 has no -NoProxy switch on Invoke-WebRequest;
rem that helper clears the proxy on its own request only, so a user-configured
rem HTTP_PROXY/HTTPS_PROXY without a localhost exception can no longer make a
rem running instance look unreachable. No proxy variable is read, changed or
rem persisted. Exit code 0 means "this port already answers HTTP 200".
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "scripts\check_local_streamlit_health.ps1" -Port %STEELAI_PORT%
if not errorlevel 1 (
  echo SteelAI Workbench is already running.
  echo Opening %STEELAI_URL%
  if defined STEELAI_NO_BROWSER exit /b 0
  start "" "%STEELAI_URL%"
  exit /b 0
)

if not exist "%STEELAI_PYTHON%" (
  echo Local Python environment was not found.
  echo Read README.md and install the requirements first.
  pause
  exit /b 1
)

echo Starting SteelAI Workbench at %STEELAI_URL%
echo Keep this window open while using the app.
"%STEELAI_PYTHON%" -m streamlit run app.py --server.address=127.0.0.1 --server.port=%STEELAI_PORT% --server.headless=false

if errorlevel 1 (
  echo.
  echo SteelAI stopped with an error. If the port is busy, close the existing app or set STEELAI_PORT to another number.
  pause
)
