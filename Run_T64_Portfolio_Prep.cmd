@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -B -m steelai.portfolio_release
) else (
  python -B -m steelai.portfolio_release
)
endlocal
