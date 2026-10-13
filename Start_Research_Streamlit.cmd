@echo off
setlocal EnableExtensions
rem ============================================================================
rem WO-31 / WO-32 - start the research-only Streamlit page on a fixed trusted port.
rem Uses the existing (frozen) scientific interpreter; no dependency is installed.
rem
rem Interpreter resolution: STEELAI_PYTHON env, then config\local-tools.cmd.
rem
rem WO-32 fix note (the script used to fail with exit 1/255
rem "The syntax of the command is incorrect." when STEELAI_PYTHON was unset):
rem the culprit was this line -
rem     for /f "usebackq tokens=2 delims==" %%A in (`findstr /b /c:"set \"STEELAI_PYTHON=" file`)
rem cmd does not accept \" as an escape inside a backquoted for /f command, so the
rem whole for /f was a syntax error and the error branch never ran. That is why it
rem looked like "the launcher is broken" instead of "the quoting is broken".
rem Now the findstr pattern carries no escaped quotes, and the trailing quote left
rem on the token is stripped separately, outside any parenthesised block.
rem (Probes: Batch_WO32/synthetic/probe_for*.cmd; exit codes: e2e notes.)
rem
rem Port-in-use is detected with netstat + findstr and only reported:
rem nothing else is ever killed.
rem
rem Usage:  Start_Research_Streamlit.cmd [port]      (default port 8761)
rem Exit:   0 = streamlit exited on its own; 2 = interpreter/config missing;
rem         3 = port already in use; other = streamlit's own exit code
rem
rem NOTE: keep this file ASCII-only. cmd reads .cmd in the OEM codepage, so
rem non-ASCII comments can turn into stray bytes and break parsing.
rem ============================================================================
set "REPO=%~dp0"
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8761"
set "PY=%STEELAI_PYTHON%"

if "%PY%"=="" (
  if exist "%REPO%config\local-tools.cmd" (
  rem The findstr pattern inside backquotes must not contain escaped quotes
  rem (that escape is what broke the original script). Use a regex dot for the
  rem quote after "set" so the line stays anchored:
  rem     set "STEELAI_PYTHON=..."
  rem Pattern: /r /b /c:"set .STEELAI_PYTHON="  (verified in probe_findstr3.cmd)
    for /f "usebackq tokens=2 delims==" %%A in (`findstr /r /b /c:"set .STEELAI_PYTHON=" "%REPO%config\local-tools.cmd"`) do set "PY=%%A"
  )
)

rem A matched line looks like:  set "STEELAI_PYTHON=D:\...\python.exe"
rem tokens=2 delims== therefore yields D:\...\python.exe" with one trailing
rem quote; strip it here. This must happen OUTSIDE any parenthesised block:
rem inside a block %PY:"=% expands while the block is parsed, not per iteration.
if defined PY set "PY=%PY:"=%"

if "%PY%"=="" (
  echo [ERROR] STEELAI_PYTHON is not set and config\local-tools.cmd has no STEELAI_PYTHON.
  echo         Fix: set STEELAI_PYTHON to a real interpreter, or add it to config\local-tools.cmd
  echo         ^(that file is git-ignored, so it never carries a machine path into a commit^).
  exit /b 2
)
if not exist "%PY%" (
  echo [ERROR] interpreter not found: %PY%
  exit /b 2
)

rem ---- port in use: report only, never kill -----------------------------------
netstat -ano | findstr /r /c:":%PORT% " | findstr "LISTENING" >nul 2>&1
if "%ERRORLEVEL%"=="0" (
  echo [ERROR] port %PORT% is already in use; nothing was killed.
  echo         Stop the other process yourself, or pass another port:
  echo             Start_Research_Streamlit.cmd 8762
  netstat -ano | findstr /r /c:":%PORT% " | findstr "LISTENING"
  exit /b 3
)

pushd "%REPO%"
echo Starting research Streamlit page on http://127.0.0.1:%PORT%/
"%PY%" -m streamlit run research_app.py --server.address 127.0.0.1 --server.port %PORT% --server.headless true
set "RC=%ERRORLEVEL%"
popd
if not "%RC%"=="0" echo [ERROR] Streamlit exited with code %RC%
exit /b %RC%
