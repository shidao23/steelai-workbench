@echo off
setlocal
for %%I in ("%~dp0.") do set "APP_ROOT=%%~fI"
if exist "%APP_ROOT%\config\local-tools.cmd" call "%APP_ROOT%\config\local-tools.cmd"
set "CONDA_PYTHON=%STEELAI_MICROSAM_PYTHON%"
set "SCRIPT=%APP_ROOT%\model_lab\micro_sam\run_batch_autodimple.py"
set "MANIFEST=%APP_ROOT%\data\index\model_lab_pilot.csv"
set "STANDARD=%APP_ROOT%\config\micro_sam_auto_standard_v0.2.json"
set "CHECKPOINT=%APP_ROOT%\model_lab\micro_sam\weights\sam_vit_b_01ec64.pth"
set "OUTPUT=%APP_ROOT%\outputs\model_lab\auto_dimple\BR10_1000x_v0.1"

if not exist "%CONDA_PYTHON%" (
  echo SteelAI micro-sam Python was not found. Configure STEELAI_MICROSAM_PYTHON in config\local-tools.cmd.
  if not defined STEELAI_NO_PAUSE pause
  exit /b 1
)

"%CONDA_PYTHON%" "%SCRIPT%" --project-root "%APP_ROOT%" --manifest "%MANIFEST%" --standard "%STANDARD%" --checkpoint "%CHECKPOINT%" --output-root "%OUTPUT%"
if errorlevel 1 (
  echo AutoDimple batch failed. Keep this window open and report the message above.
) else (
  echo AutoDimple B/R batch completed successfully.
)
if not defined STEELAI_NO_PAUSE pause
endlocal
