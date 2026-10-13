@echo off
setlocal EnableExtensions
rem ============================================================================
rem WO-31 - start the research-only Streamlit page on a fixed trusted port.
rem Uses the existing (frozen) scientific interpreter; no dependency is installed.
rem Interpreter resolution: STEELAI_PYTHON env, then config\local-tools.cmd.
rem Usage:  Start_Research_Streamlit.cmd [port]      (default port 8761)
rem ============================================================================
set "REPO=%~dp0"
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8761"
set "PY=%STEELAI_PYTHON%"

if "%PY%"=="" (
  if exist "%REPO%config\local-tools.cmd" (
    for /f "usebackq tokens=2 delims==" %%A in (`findstr /b /c:"set \"STEELAI_PYTHON=" "%REPO%config\local-tools.cmd"`) do (
      set "PY=%%~A"
    )
  )
)

if "%PY%"=="" (
  echo [ERROR] STEELAI_PYTHON is not set and config\local-tools.cmd has no STEELAI_PYTHON.
  exit /b 2
)
if not exist "%PY%" (
  echo [ERROR] interpreter not found: %PY%
  exit /b 2
)

pushd "%REPO%"
echo Starting research Streamlit page on http://127.0.0.1:%PORT%/
"%PY%" -m streamlit run research_app.py --server.address 127.0.0.1 --server.port %PORT% --server.headless true
set "RC=%ERRORLEVEL%"
popd
if not "%RC%"=="0" echo [ERROR] Streamlit exited with code %RC%
exit /b %RC%
