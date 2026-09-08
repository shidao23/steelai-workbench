@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "STEELAI_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%STEELAI_PYTHON%" (
  echo [失败] 找不到 SteelAI-Workbench 的独立 Python：%STEELAI_PYTHON%
  echo 请先按 README 的“首次环境准备”完成安装。
  pause
  exit /b 2
)

"%STEELAI_PYTHON%" -B -m steelai.flagship_demo --output "%~dp0outputs\flagship_demo"
set "STEELAI_EXIT=%ERRORLEVEL%"
if not "%STEELAI_EXIT%"=="0" (
  echo.
  echo [失败] T40 旗舰演示没有通过，请保留上方错误信息。
  pause
  exit /b %STEELAI_EXIT%
)

echo.
echo [完成] T40 旗舰演示已生成并通过完整性复核。
echo 结果目录：%~dp0outputs\flagship_demo
pause
exit /b 0
