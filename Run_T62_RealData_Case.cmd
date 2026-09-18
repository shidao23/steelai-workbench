@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -B -m steelai.real_data_case
) else (
  python -B -m steelai.real_data_case
)
endlocal
