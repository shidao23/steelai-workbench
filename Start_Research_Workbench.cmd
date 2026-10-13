@echo off
setlocal EnableExtensions
rem ============================================================================
rem WO-31 - start the SteelAI research thin API (loopback only).
rem Serves the JSON API under /api and the built React app at /.
rem The interpreter comes from the repository-local .venv-web environment.
rem Usage:  Start_Research_Workbench.cmd [port]      (default port 8760)
rem ============================================================================
set "REPO=%~dp0"
set "PY=%REPO%.venv-web\Scripts\python.exe"
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8760"

if not exist "%PY%" (
  echo [ERROR] web environment not found: %PY%
  echo Create it with:
  echo     python -m venv .venv-web
  echo     .venv-web\Scripts\python.exe -m pip install -r requirements-web.txt
  exit /b 2
)

if not exist "%REPO%frontend\dist\index.html" (
  echo [WARN] frontend\dist is missing - only the JSON API will be available.
  echo        Build it with:  cd frontend ^&^& npm install ^&^& npm run build
)

pushd "%REPO%"
echo Starting research thin API on http://127.0.0.1:%PORT%/
"%PY%" -m steelai.web_api --host 127.0.0.1 --port %PORT%
set "RC=%ERRORLEVEL%"
popd
if not "%RC%"=="0" echo [ERROR] API exited with code %RC%
exit /b %RC%
