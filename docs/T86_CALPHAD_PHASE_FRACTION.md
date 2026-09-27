# T86 · pycalphad CALPHAD 平衡相分数接入（可选、可关闭）

状态：第一阶段实现完成；第二阶段建立独立环境并取得授权数据库，但原始 `mc_fe v2.062` **兼容性门禁未通过**；第三阶段按负责人决定改用**第三方社区派生候选**（`mc_fe_v2062_clean`，提交 `19b1164…`，SHA-256 `7cf37dd4…`，未被修改）并完成差异审计与验证复现；第四阶段按负责人批准建立**固定缩减成分体系** `steel_matrix_equilibrium_v1`（12 组元）与**固定相集合** `steel_matrix_major_carbides_v1`（7 相，独立探针 7/7 验证通过）；第五阶段把正式路径改为**每个温度点独立进程求解**（`solver_mode=independent_single_point_process_v1`，批量热启动路径降级为仅诊断）。十步验证第 1–5、7、9 步通过，但**875/900 °C 附近的单点求解本身不确定**（全新进程重复调用随机无解），因此**仍无 `pilot_ready` 状态、无真实炉次结果可交付，T86 保持 `Blocked`**，数据库候选记为 `compatibility_candidate`。第五阶段详情见 [T86 第五阶段](T86_PHASE5_INDEPENDENT_POINTS.md)，第四阶段见 [T86 第四阶段：固定缩减成分体系与固定相范围](T86_PHASE4_REDUCED_SYSTEM.md)，第三阶段见 [T86 第三阶段](T86_PHASE3_COMMUNITY_COMPATIBILITY.md)，第二阶段见 [T86 第二阶段：环境与门禁](T86_PHASE2_ENVIRONMENT_AND_GATES.md)。

当前事实（2026-09-25）：

- `pycalphad==0.11.2` 已装入独立环境 `.venv-pycalphad`（34 个包哈希锁定），主应用仍不导入它。
- 数据库为 MatCalc `mc_fe v2.062`（TU Wien，ODbL 1.0 + DbCL 1.0，**不随仓库分发**），文件 SHA-256 `aa02077e…`。
- **pycalphad 0.11.2 无法解析该数据库**：平台编码打开失败，显式编码后在**第 180 行 `REFERENCE_ELEMENT`** 处语法失败；`ADD_COMPOSITION_SET`、`ATTACH_CONTRIBUTION` 等 MatCalc 扩展命令逐条验证同样不被支持。
- 未删除关键字、未改写数据库、未制作“兼容版 TDB”、未做真实计算。
- 结果限制声明（缩减成分体系 / 排除元素 / 待人工复核 / 不写回 / 非完整相图）已嵌入页面、Markdown、JSON 与 CSV；受控元素排除政策见 `config/calphad_exclusion_policy_v1.0.json`。

## 1. 任务定位与范围

把模型登记册里已有的 pycalphad 候选（`steelai/model_lab.py` 的 `MODEL_REGISTRY`，`readiness=database_required`）接入物理计算页，做成一个**可关闭的本地功能**。

第一阶段只做一件事：

> 在**固定样品成分**下，计算并展示**平衡相分数随温度变化**的截面曲线。

明确边界：

- 不是完整相图。曲线是固定成分、固定压力（101325 Pa）下的一维温度截面。
- 不是实验测量值。结果是热力学模型的预测，标为 `model_prediction_not_experimental_measurement`，复核状态 `pending_human_review`。
- 不写回 `data/processed/` 正式实验数据层；不参与 T52 治理结果包发布（该接入推迟到有授权 TDB 之后）。
- pycalphad 使用独立环境，**不是主应用依赖**；未配置环境或 TDB 时，既有经验公式物理计算照常运行。

## 2. 单位与输出基准（界面上逐项标注）

| 项目 | 约定 |
| --- | --- |
| 输入成分 | `wt.%`（样品登记成分） |
| 温度输入 | `°C` |
| 温度内部换算 | `T_K = T_degC + 273.15` |
| 压力 | `101325 Pa`（固定，不做压力扫描） |
| 模型内部成分基准 | 摩尔分数（由 wt.% 用登记原子量换算，再按纳入组元重新归一化） |
| **输出相分数基准** | **各相摩尔分数**：`X_phase = NP_phase / Σ NP`，其中 `NP` 是 pycalphad 给出的该相摩尔数 |
| 质量分数换算 | **未实现**。渲染说明中明确写出“不是质量分数” |

相成分集（例如 `FCC_A1` 与 `FCC_A1#2`）在隔离进程中按基相名合并求和；主应用会拒绝接受未聚合就返回的计算结果。

原子量表位于 `config/calphad_adapter_v1.0.json` 的 `method.atomic_weights`，带有 `source` 与 `source_status`：
来源标注为 CIAAW/IUPAC 标准原子量（节略常规值），状态为“本适配器本地登记，尚未针对当前 IUPAC 出版物逐值复核”。正式报告前需要复核该表。

## 3. 阻断规则（全部关闭式失败）

| 代码 | 触发条件 |
| --- | --- |
| `CALPHAD-DISABLED-001` | `STEELAI_CALPHAD_ENABLED` 为 `0/false/no/off` |
| `CALPHAD-ENV-001` | 未配置隔离解释器，或配置的解释器文件不存在 |
| `CALPHAD-ENV-002` | 探测失败，或隔离环境未安装 pycalphad |
| `CALPHAD-ENV-003` | 隔离环境 pycalphad 版本与登记固定版本不一致 |
| `CALPHAD-TDB-000` | 没有本地 TDB 登记文件，或登记文件中没有条目 |
| `CALPHAD-TDB-001` | TDB 登记缺字段、文件缺失、SHA-256 不匹配、授权状态不符 |
| `CALPHAD-TDB-005` | TDB 登记没有声明覆盖元素 |
| `CALPHAD-TDB-006` | 指定的 `database_id` 不存在 |
| `CALPHAD-COMP-001` | 成分中“已声明但无值”的元素存在，且没有具名用户声明其按未检出排除（**绝不按 0 处理**） |
| `CALPHAD-COMP-002` | 成分中**非零**元素不在 TDB 覆盖范围内（**没有覆盖开关，不省略、不补零**） |
| `CALPHAD-COMP-003` | 成分没有 Fe 值，需要用户具名确认按余量计算 |
| `CALPHAD-COMP-004` | 成分值无效（负数/非数值） |
| `CALPHAD-COMP-005` | Fe 余量落在 `(0, 100]` 之外 |
| `CALPHAD-COMP-006` | 成分中已声明 Fe 但没有数值（不得用余量替代已声明的 Fe 列） |
| `CALPHAD-COMP-007` | wt.% → 摩尔分数换算不完整（缺原子量等） |
| `CALPHAD-COMP-008/009/010` | 计算体系缺少 Fe、只有单组元、或与 TDB 无共同组元 |
| `CALPHAD-RANGE-001` | 温度区间无效、逆向、越界、点数为 1，或超过 401 点上限 |
| `CALPHAD-RUN-001` | 隔离进程失败、超时、未产出结果，或 worker 返回 error |
| `CALPHAD-RUN-002` | worker 结果不可信：版本不一致、温度点不匹配、相分数合计不等于 1、返回未聚合相成分集 |

两条可以软化的规则：

- 成分中 `0 wt.%` 且不在 TDB 内的元素**不阻断**，但会记录为排除项（`declared_zero_wt_pct_and_not_in_database`），不参与模型体系，也不被静默补零。
- 请求温度区间超出 TDB 声明适用区间时给出“属于模型外推”的警告，不阻断。

## 4. 第三方登记（2026-09-24 核对）

| 项目 | 值 |
| --- | --- |
| 组件 | `pycalphad` |
| 拟固定版本 | `0.11.2`（登记状态 `proposed_pending_user_approval_before_install`） |
| 许可证 | MIT（OSI 已核准），`https://github.com/pycalphad/pycalphad/blob/0.11.2/LICENSE.txt` |
| 官方仓库 | `https://github.com/pycalphad/pycalphad` |
| 发布页 | `https://github.com/pycalphad/pycalphad/releases/tag/0.11.2` |
| 源码引用（tag 0.11.2 的提交） | `2d4c744ddb890e179542894d070150797e13b325` |
| sdist SHA-256 | `588ad2c0c207aa35d263c16283559eff566a8fcdf33ecdc77a9ec9176cde1378` |
| `cp312 win_amd64` wheel SHA-256 | `53f6547738d02abb7349606548cce11747e22fc8a1308a1b866fb627e713ac58` |
| `requires-python` | `>=3.11`（官方 classifier 覆盖 3.11 / 3.12 / 3.13；本机主应用为 CPython 3.12.14） |
| 直接依赖（13 项） | `matplotlib>=3.3`、`numpy>=1.13`、`pint`、`pyparsing>=3.0`、`pytest`、`pytest-cov`、`runtype`、`scipy`、`setuptools_scm[toml]>=6.0`、`symengine<0.14,>=0.9.2`、`tinydb>=3.8`、`typing_extensions`、`xarray>=0.11.2` |
| 代码复用 | 未复制任何第三方代码（`code_imported=false`），主 `requirements*.txt` 未修改 |

核对方法：读取官方 PyPI JSON 元数据（版本、`requires_dist`、`requires_python`、各文件 SHA-256）与固定 tag 上的 `LICENSE.txt`，并通过 GitHub REST API 解析 tag 提交。**没有下载任何文件、没有做完整传递依赖锁**（`source_check.not_yet_verified` 已记录）。

登记文件：`config/calphad_adapter_v1.0.json`（机器可读）+ `THIRD_PARTY.md`（人工登记）。

## 5. 启用步骤（需要用户批准后才能执行）

1. **安装依赖（必须由用户明确同意）**。项目当前没有安装 pycalphad：
   ```powershell
   py -3.12 -m venv .venv-pycalphad
   .\.venv-pycalphad\Scripts\python.exe -m pip install pycalphad==0.11.2
   ```
   该路径已被 `.gitignore` 覆盖（`.venv-pycalphad/`）。如果使用 Conda 等其他环境，设置
   `STEELAI_CALPHAD_PYTHON`（环境变量）或 `config/settings.toml` 的 `[tools] calphad_python`。
   安装前应确认 `symengine` 有对应解释器的可用 wheel。

2. **登记授权 TDB**。把 `config/calphad_tdb.example.json` 复制为 `config/calphad_tdb.local.json`（已被 Git 忽略），逐项填写：
   `database_id`、`path`、`sha256`、`format`、`provider`、`version_or_date`、`license_or_authorization`、
   `authorization_status=user_confirmed_authorized_for_this_steel_grade`、`authorized_by`、`authorized_at`、
   `applicable_steel_grades`、`covered_elements`、`declared_temperature_range_C`、`declared_pressure_Pa`、`citation`。
   SHA-256 可用 `Get-FileHash <tdb> -Algorithm SHA256` 生成。TDB 本体不进入仓库。

3. 打开应用 → **分析与报告 → 物理计算** → 页签 **“平衡相分数—温度（可选 · T86）”**：
   确认状态为“就绪”后设置温度区间与步长，勾选并填写 **Fe 余量确认人**（成分无 Fe 时），
   对“已声明但无值”的元素按需填写排除声明人，然后点击“计算平衡相分数—温度”。
   结果可下载 Markdown / JSON 记录（包含 TDB 来源与 SHA-256、模型输入摘要与结果摘要）。

关闭功能：设置 `STEELAI_CALPHAD_ENABLED=0`（或 `false`/`no`/`off`）。

## 6. 改动文件

| 文件 | 说明 |
| --- | --- |
| `steelai/calphad_adapter.py` | 新增。门禁、单位与基准声明、wt.%→摩尔分数换算、TDB 登记校验、请求构造、worker 调度与结果校验（主应用不导入 pycalphad） |
| `scripts/calphad_phase_fraction_worker.py` | 新增。在隔离解释器中运行；复核 pycalphad 版本与 TDB SHA-256 后求解平衡，按基相名聚合输出 |
| `config/calphad_adapter_v1.0.json` | 新增。第三方登记、方法/单位约定、原子量表、声明边界 |
| `config/calphad_tdb.example.json` | 新增。本地 TDB 登记模板（不含数据库内容） |
| `steelai/views/physics_view.py` | 物理计算页新增第 4 个页签；阻断时不显示计算入口 |
| `steelai/model_lab.py` | `model_statuses()` 为 pycalphad 行提供真实本地状态与说明 |
| `steelai/views/model_lab_view.py` | 模型登记册展开区显示 CALPHAD 状态与入口指引 |
| `tests/test_t86_calphad_adapter.py` | 新增。42 项测试 |
| `.gitignore` | 忽略 `config/calphad_tdb.local.json` |
| `docs/T86_CALPHAD_PHASE_FRACTION.md` | 本文件 |
| `THIRD_PARTY.md`、`TASKS.md`、`docs/CURRENT_CAPABILITIES.md`、`project_log/CHANGELOG.md` | 登记与看板更新 |

## 7. 验证

- 最小相关测试：`.\.venv\Scripts\python.exe -B -m pytest -q tests/test_t86_calphad_adapter.py` → 42 passed。
- 物理与页面回归：`tests/test_physics.py`、`tests/test_streamlit_pages.py` 通过（页面测试会实际渲染 `physics_view.py`，含未配置环境的阻断分支）。
- 项目测试入口：`.\scripts\test.ps1`。
- 详细结果与沙箱限制见 `project_log/CHANGELOG.md` 的 T86 条目。

## 8. 仍需用户提供

1. **有使用授权、适用于目标钢种的 TDB**（含来源、版本/日期、授权依据、覆盖元素、温度适用区间与 SHA-256）。
   当前项目没有任何 TDB，因此真实钢种计算验收尚未进行，也没有任何真实成分的相分数结果。
2. **安装依赖的明确同意**（`pycalphad==0.11.2` 到独立环境），以及是否要求额外固定传递依赖哈希。
3. 现有 `data/processed/composition.csv` 中 B-DQ/R-DQ 的 `O`、`W` 为空值。按当前规则这两个元素会触发
   `CALPHAD-COMP-001`：要么补值，要么由具名用户声明按未检出排除。即使补值，`P`、`S`、`N`、`B`、`As`、`Sn`、`Sb`
   等元素也需要被 TDB 覆盖，否则触发 `CALPHAD-COMP-002`。
4. 原子量表（CIAAW/IUPAC 节略值）是否需要按当前 IUPAC 出版物逐值复核后重新登记。

## 9. 明确“不是”

- 不是完整相图，也不是相图计算功能。
- 不是实验数据，不产生实验真值，不替代实验测量。
- 不是主应用依赖：没有它，物理计算、统计、治理与发布链路照常运行。
- 不是已验收的真实钢种结果：没有 TDB、没有安装依赖、没有任何真实成分的计算输出。
