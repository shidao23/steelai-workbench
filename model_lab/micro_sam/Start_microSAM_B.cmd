@echo off
setlocal
set "LAB=%~dp0"
set "APP_ROOT=%LAB%..\..\"
set "MICROSAM_CACHEDIR=%LAB%cache"
set "INPUT=%APP_ROOT%outputs\model_lab\micro_sam_smoke\B-DQ-1-06_input.png"
set "EMBEDDING=%APP_ROOT%outputs\model_lab\micro_sam_annotations\B-DQ-1-06_embeddings.zarr"
set "CHECKPOINT=%LAB%weights\sam_vit_b_01ec64.pth"
if exist "%APP_ROOT%config\local-tools.cmd" call "%APP_ROOT%config\local-tools.cmd"
set "CONDA_PYTHON=%STEELAI_MICROSAM_PYTHON%"
set "ADAPTER=%LAB%start_conda_annotator.py"

if not exist "%CONDA_PYTHON%" (
  echo SteelAI micro-sam Python was not found. Configure config\local-tools.cmd.
  pause
  exit /b 1
)
if not exist "%INPUT%" (
  echo Prepared B image was not found. Run the SteelAI smoke test first.
  pause
  exit /b 1
)
if not exist "%CHECKPOINT%" (
  echo SAM checkpoint was not found.
  pause
  exit /b 1
)

echo Starting micro-sam for B-DQ-1-06. The first window may take about 30 seconds.
"%CONDA_PYTHON%" "%ADAPTER%" -i "%INPUT%" -e "%EMBEDDING%" -m vit_b -c "%CHECKPOINT%" -d cuda
endlocal
