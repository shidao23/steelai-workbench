@echo off
setlocal
chcp 65001 >nul

set "APP_ROOT=%~dp0"
set "DSH_WORKSPACE=%APP_ROOT%dsh_workspace"
set "DSH_PATCH=%DSH_WORKSPACE%\.dsh\cordis.patch.yml"
set "DSH_PERMISSION_MODE=read-only"
if exist "%APP_ROOT%config\local-tools.cmd" call "%APP_ROOT%config\local-tools.cmd"

if not exist "%APP_ROOT%.venv\Scripts\python.exe" (
  echo SteelAI Python environment was not found:
  echo %APP_ROOT%.venv\Scripts\python.exe
  pause
  exit /b 1
)

"%APP_ROOT%.venv\Scripts\python.exe" -m steelai.dsh_mcp_server --self-test >nul
if errorlevel 1 (
  echo SteelAI DSH bridge self-test failed.
  echo Run: "%APP_ROOT%.venv\Scripts\python.exe" -m pip install -r "%APP_ROOT%requirements.txt"
  pause
  exit /b 1
)

if defined STEELAI_COMPOSITION_MCP (
  "%APP_ROOT%.venv\Scripts\python.exe" "%STEELAI_COMPOSITION_MCP%" --self-test >nul
  if errorlevel 1 (
    echo Optional composition intake self-test failed.
    pause
    exit /b 1
  )
)

if /i "%~1"=="--self-test" (
  echo SteelAI DSH self-test passed.
  exit /b 0
)

pushd "%DSH_WORKSPACE%"
if exist "%DSH_WORKSPACE%\node_modules\.bin\dsh.cmd" (
  call "%DSH_WORKSPACE%\node_modules\.bin\dsh.cmd" --profile web --patch "%DSH_PATCH%"
  set "EXIT_CODE=%ERRORLEVEL%"
  popd
  exit /b %EXIT_CODE%
)

where dsh >nul 2>nul
if not errorlevel 1 (
  dsh --profile web --patch "%DSH_PATCH%"
  set "EXIT_CODE=%ERRORLEVEL%"
  popd
  exit /b %EXIT_CODE%
)

where npx >nul 2>nul
if not errorlevel 1 (
  echo Local DSH runtime is missing; first launch may take several minutes.
  call npx --yes @deepseek-ai/dsh@0.1.1-rc.2 --profile web --patch "%DSH_PATCH%"
  set "EXIT_CODE=%ERRORLEVEL%"
  popd
  exit /b %EXIT_CODE%
)

popd
echo Neither dsh nor npx was found. Install the DSH CLI or Node.js first.
pause
exit /b 1
