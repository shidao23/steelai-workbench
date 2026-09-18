@echo off
setlocal
set "STEELAI_PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%STEELAI_PYTHON%" (
  echo [FAILED] Missing .venv. Follow docs\INSTALL.md first.
  exit /b 2
)

echo [1/5] Validate the frozen release contract
"%STEELAI_PYTHON%" -B -m steelai.release_candidate || exit /b 2

echo [2/5] Run the deterministic quality gate
"%STEELAI_PYTHON%" -B -m steelai.quality_gate || exit /b 2

echo [3/5] Run the complete offline test suite
"%STEELAI_PYTHON%" -B -m unittest discover -s tests -v || exit /b 2

echo [4/5] Replay or verify the frozen T40 synthetic demo
"%STEELAI_PYTHON%" -B -m steelai.flagship_demo --output "%~dp0outputs\flagship_demo" || exit /b 2

echo [5/5] Audit the Git-tracked public candidate
"%STEELAI_PYTHON%" -B -m steelai.public_release_audit || exit /b 2

echo [PASSED] SteelAI Workbench v0.2.0-rc1 is reproducible on this checkout.
echo Git commit and tag remain explicit project-owner actions.
exit /b 0
