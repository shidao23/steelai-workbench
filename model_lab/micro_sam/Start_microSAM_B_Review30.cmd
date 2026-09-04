@echo off
setlocal
set "LAB=%~dp0"
set "APP_ROOT=%LAB%..\..\"
set "MICROSAM_CACHEDIR=%LAB%cache"
if exist "%APP_ROOT%config\local-tools.cmd" call "%APP_ROOT%config\local-tools.cmd"
set "CONDA_PYTHON=%STEELAI_MICROSAM_PYTHON%"
set "ADAPTER=%LAB%start_conda_annotator.py"
set "INPUT=%APP_ROOT%outputs\model_lab\micro_sam_smoke\B-DQ-1-06_input.png"
set "EMBEDDING=%APP_ROOT%outputs\model_lab\micro_sam_annotations\B-DQ-1-06_embeddings.zarr"
set "CHECKPOINT=%LAB%weights\sam_vit_b_01ec64.pth"
set "SEED=%STEELAI_REVIEW30_ROOT%\B-DQ-1-06_review30_seed.tif"

if not exist "%CONDA_PYTHON%" (
  echo SteelAI micro-sam Python was not found. Configure config\local-tools.cmd.
  pause
  exit /b 1
)
if not exist "%SEED%" (
  echo Review30 seed was not found.
  pause
  exit /b 1
)

echo Starting the B-DQ Review30 workspace.
"%CONDA_PYTHON%" "%ADAPTER%" -i "%INPUT%" -e "%EMBEDDING%" -s "%SEED%" -m vit_b -c "%CHECKPOINT%" -d cuda
endlocal
