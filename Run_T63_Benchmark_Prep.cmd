@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -B -m steelai.agent_workflow_benchmark
) else (
  python -B -m steelai.agent_workflow_benchmark
)
endlocal
