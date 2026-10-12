<#
.SYNOPSIS
    SteelAI Workbench 的唯一测试入口。

.DESCRIPTION
    从脚本位置确定仓库根目录，解析解释器并检查 pytest，然后在仓库根目录运行
    <python> -B -m pytest -q
    pytest 的作用范围由仓库根目录的 pytest.ini 固定（testpaths = tests）。
    不安装或升级任何依赖；原样返回 pytest 的 exit code。

    解释器解析顺序（WO-28 迁移后虚拟环境仍原位保护，仓库内可能没有 .venv）：
    1. 环境变量 STEELAI_PYTHON；
    2. 仓库内 .venv\Scripts\python.exe；
    3. 被 Git 忽略的 config\local-tools.cmd 中登记的 STEELAI_PYTHON。
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot

function Get-LocalToolsPython {
    $localTools = Join-Path $repoRoot 'config\local-tools.cmd'
    if (-not (Test-Path -LiteralPath $localTools)) { return $null }
    $match = Select-String -LiteralPath $localTools -Pattern '^\s*set\s+"STEELAI_PYTHON=([^"]+)"' |
        Select-Object -First 1
    if (-not $match) { return $null }
    return $match.Matches[0].Groups[1].Value
}

$python = $null
if ($env:STEELAI_PYTHON -and (Test-Path -LiteralPath $env:STEELAI_PYTHON)) {
    $python = $env:STEELAI_PYTHON
}
if (-not $python) {
    $repoVenv = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $repoVenv) { $python = $repoVenv }
}
if (-not $python) {
    $configured = Get-LocalToolsPython
    if ($configured -and (Test-Path -LiteralPath $configured)) { $python = $configured }
}
if (-not $python) {
    Write-Error "未找到可用的解释器。请设置 STEELAI_PYTHON 或在 config\local-tools.cmd 登记 STEELAI_PYTHON，也可按 docs/DEVELOPMENT_BASELINE.md 在本仓库创建 .venv。"
    exit 2
}

& $python -c "import pytest"
if ($LASTEXITCODE -ne 0) {
    Write-Error "解释器无法导入 pytest：$python。请手动运行：$python -m pip install -r requirements-dev.txt（本脚本不会自动安装依赖）。"
    exit 2
}

Write-Host "repository: $repoRoot"
Write-Host "python: $python"
Write-Host "pytest scope: tests/ (pytest.ini)"

& $python -B -m pytest -q
exit $LASTEXITCODE
