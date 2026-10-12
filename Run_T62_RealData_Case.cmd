@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0config\local-tools.cmd" call "%~dp0config\local-tools.cmd"
if not defined STEELAI_PYTHON set "STEELAI_PYTHON=%~dp0.venv\Scripts\python.exe"
set "PYTHONPATH=%CD%"
if exist "%STEELAI_PYTHON%" (
  "%STEELAI_PYTHON%" -B -m steelai.real_data_case
) else (
  python -B -m steelai.real_data_case
)
endlocal
