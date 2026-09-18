<#
.SYNOPSIS
    SteelAI Workbench 的唯一测试入口。

.DESCRIPTION
    从脚本位置确定仓库根目录，检查 .venv 与 pytest，然后在仓库根目录运行
    .\.venv\Scripts\python.exe -B -m pytest -q
    pytest 的作用范围由仓库根目录的 pytest.ini 固定（testpaths = tests）。
    不安装或升级任何依赖；原样返回 pytest 的 exit code。
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot

$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    Write-Error "未找到虚拟环境解释器：$python。请先按 docs/DEVELOPMENT_BASELINE.md 创建 .venv 并安装 requirements-dev.txt。"
    exit 2
}

& $python -c "import pytest"
if ($LASTEXITCODE -ne 0) {
    Write-Error "当前 .venv 无法导入 pytest。请手动运行：.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt（本脚本不会自动安装依赖）。"
    exit 2
}

Write-Host "repository: $repoRoot"
Write-Host "pytest scope: tests/ (pytest.ini)"

& $python -B -m pytest -q
exit $LASTEXITCODE
