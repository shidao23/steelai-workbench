@echo off
setlocal
chcp 65001 >nul

set "APP_ROOT=%~dp0"
set "DSH_WORKSPACE=%APP_ROOT%dsh_workspace"
set "DSH_PERMISSION_MODE=read-only"
set "SHIDAO_PLATFORM=%APP_ROOT%..\_agent_platform"
set "SHARED_LAUNCHER=%SHIDAO_PLATFORM%\scripts\launch-operational-console.ps1"
set "SHIDAO_PWSH=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\powershell\pwsh.exe"
if exist "%APP_ROOT%config\local-tools.cmd" call "%APP_ROOT%config\local-tools.cmd"

if not exist "%SHARED_LAUNCHER%" (
  echo Shidao Workbench shared launcher was not found:
  echo %SHARED_LAUNCHER%
  echo No project-local, global, or network fallback will be attempted.
  exit /b 1
)
if not exist "%SHIDAO_PWSH%" (
  echo The registered Shidao Workbench PowerShell runtime was not found:
  echo %SHIDAO_PWSH%
  echo No fallback install will be attempted.
  exit /b 1
)

if not exist "%APP_ROOT%.venv\Scripts\python.exe" (
  echo SteelAI Python environment was not found:
  echo %APP_ROOT%.venv\Scripts\python.exe
  pause
  exit /b 1
)

"%APP_ROOT%.venv\Scripts\python.exe" -m steelai.dsh_mcp_server --self-test >nul
if errorlevel 1 (
  echo SteelAI DSH bridge self-test failed.
  echo Run the existing SteelAI diagnostics; startup will not install dependencies.
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
  "%SHIDAO_PWSH%" -NoProfile -File "%SHARED_LAUNCHER%" -Action Validate
  if errorlevel 1 exit /b 1
  echo SteelAI bridge and shared Shidao Workbench profile self-test passed.
  exit /b 0
)

echo Starting the shared Shidao Workbench. Create or open the Shidao SteelAI Research session for research tasks.
"%SHIDAO_PWSH%" -NoProfile -File "%SHARED_LAUNCHER%" -Action Web -OpenBrowser
exit /b %ERRORLEVEL%
