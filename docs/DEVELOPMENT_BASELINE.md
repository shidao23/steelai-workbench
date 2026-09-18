# SteelAI Workbench 开发基线（S0 绿色开发基线收口）

本文件记录 S0 阶段的开发环境、唯一测试入口、测试范围边界和最终真实验证结果。
任何新功能开工前，先确认本文件的验收命令仍然全绿。

## 1. 安装

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

- `requirements.txt` 只登记生产运行时依赖，不加入测试工具；测试依赖单独放在 `requirements-dev.txt`。
- `requirements-dev.txt` 通过 `-r requirements.txt` 复用生产钉版，再追加 `pytest==9.1.1`。
- 不要用 `pip freeze` 覆盖任一 requirements 文件。

## 2. 唯一验证入口

```powershell
.\scripts\test.ps1
```

`scripts/test.ps1` 的行为：

1. 从脚本自身位置推导仓库根目录（不依赖调用者的当前目录）；
2. 检查 `.venv\Scripts\python.exe` 是否存在；
3. 检查该解释器能否 `import pytest`；
4. 在仓库根目录执行 `.\.venv\Scripts\python.exe -B -m pytest -q`；
5. 原样返回 pytest 的 exit code；
6. 不安装、不升级任何依赖。

## 3. 测试范围边界

测试范围由仓库根目录的 `pytest.ini` 固定，不靠命令行拼接：

```ini
[pytest]
testpaths = tests
python_files = test_*.py
norecursedirs = .git .venv .venv-frictionless .pytest_cache outputs model_lab data dsh_workspace
addopts = -p no:cacheprovider
```

- `testpaths = tests`：`python -m pytest -q` 只收集 `tests/`。
- `norecursedirs` 排除 `outputs` 与 `model_lab`，冒烟脚本和备份副本不再进入主测试。
- `addopts = -p no:cacheprovider`：不写 `.pytest_cache`，避免受目录权限影响；因此 `--lf` / `--ff` 不可用，需要重跑就整体重跑。

### model_lab 是独立可选 runtime

`model_lab/`（含 `model_lab/micro_sam/run_smoke_test.py`）是独立可选 runtime 的手动冒烟入口，依赖 `torch` 等未安装的大体积包，不属于主测试范围。它的可用性请在对应 runtime 环境内单独验证，不要让它进入 `tests/` 集合。

### outputs 是备份与产物

`outputs/` 存放演示备份、集成快照和本地产物（`outputs/integration_backups/...` 内含同名测试文件副本），不是测试源。任何测试命令都不得扫描该目录；同名模块冲突会直接中断 pytest 收集。

## 4. 数据契约的唯一性规则

- 表的行唯一性**只**依据该表在 `config/research_data_contract_v1.0.json` 中声明的 `primary_key`。
- 同一个 `sample_id` 对应多行观测属于合法的一对多数据，不再视为错误；契约验证器不再按 `table_name` 硬编码一对多白名单。
- 仍然保留：未登记 `sample_id` 的外键/孤儿检查、`primary_key` 重复检查、数值字段可解析性检查、必需列检查。
- 判断“数据是否重复”时，以契约 `primary_key`（例如 `thermal_simulation_softening` 的 `experiment_run_id + softening_version`）为准，不以 `sample_id` 是否重复为准。
- 实测：`data/processed/thermal_simulation_softening.csv` 共 16 行，`sample_id` 为 `B-DQ` 8 行 / `R-DQ` 8 行，16 个 `experiment_run_id` 与 `acquisition_id` 各不相同，`softening_version` 单一，因此契约状态为 `passed`。

## 5. 本次最终真实验证结果（2026-09-17）

| 命令 | 结果 |
| --- | --- |
| `.\.venv\Scripts\python.exe -B -m pytest -q tests/test_research_data_contract.py tests/test_research_agent.py` | 16 passed |
| `.\.venv\Scripts\python.exe -B -m pytest -q tests/test_t75_softening_method_readiness.py` | 4 passed |
| `.\scripts\test.ps1` | 312 passed, 8 skipped, 38 subtests passed（139.26s），exit code 0 |
| `.\.venv\Scripts\python.exe -m pip check` | No broken requirements found. |

`requirements-dev.txt` 安装的 pytest 版本：`9.1.1`。

## 6. 已知环境限制

- 本仓库的数据文件、方法注册表和特征表在 S0 期间未被修改；验证仅读取它们。所有测试夹具写入系统临时目录，不写入 `data/processed/`。
- 若在受限沙箱中运行（例如仅允许写工作区、禁止写系统临时目录），`TemporaryDirectory` 夹具会因 `WinError 5` 失败，表现为“测试通过但 teardown 报权限错误”。此时请在普通用户终端或放宽文件访问后重跑 `.\scripts\test.ps1`，不要为了绕过权限去改写测试夹具路径。
