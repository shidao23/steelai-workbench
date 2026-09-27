# T86 第五阶段：每个温度点独立进程求解

结论先行：**`solver_mode=independent_single_point_process_v1` 已作为正式试点路径实现并版本化；旧的批量 Workspace 热启动路径降级为仅诊断用。** 但 324 个独立点验收只做到 **320 个首次成功**（失败集中在 875 °C 与 900 °C），且批量模式与独立点模式在 675 °C 存在 1.069×10⁻⁴ 的差异，因此 **T86 保持 `Blocked`**，不标记 `pilot_ready_pending_scientific_review`。

保持不变的科研输入：12 组元（`Fe, C, Mn, Si, Cr, Ni, Mo, Cu, Al, Nb, Ti, V`）加 `VA`、固定相集合 `steel_matrix_major_carbides_v1`、温度网格、排除元素与全部限制声明。

## 1. 独立单点求解模式

政策文件 `config/calphad_reduced_system_v1.0.json` 中的 `solver_modes`：

| 模式 | 状态 | 说明 |
| --- | --- | --- |
| `independent_single_point_process_v1` | `formal_pilot` | 正式试点路径；每个温度点一个全新 worker 进程 |
| `batch_workspace_warm_start` | `diagnostic_only` | 第四阶段的批量路径，仅保留为诊断与对照证据 |

每个温度点的强制规则（政策中逐条声明并由 `validate_reduced_system_policy` 校验）：

- 同一份规范化成分；相同的 12 组元加 `VA`；相同的固定相集合；相同压力、数据库 SHA-256、pycalphad 版本与配置；
- 启动**全新 worker 进程**，在新进程中重新创建 `Database`、模型与 `Workspace`；
- **只求解一个温度点**，退出后再处理下一个；
- **按温度顺序串行执行，禁止并行**（worker 侧 `CALPHAD-WORKER-MODE-001` 拒绝多温度请求，父进程侧测试断言最大并发为 1）。

## 2. 不得改变科学输入

政策 `forbidden` 列表逐条禁止：删除失败温度点、改变温度步长、相邻点插值、平滑相分数、动态删除组元或相、根据求解结果更改 `pdens`、从多次失败中挑选"看起来合理"的一次、用前一个温度点作为下一点的初始状态。

实现层面的对应保证：

- 每个点只改温度，其余字段逐点相同（测试 `test_every_point_uses_identical_inputs_except_temperature` 逐字段比对）；
- 没有任何按结果调整参数的代码路径；
- 失败点不会被跳过：父进程继续把该温度点记入清单，最终整体阻断。

## 3. 重试规则

- 正式验收要求每个温度点在**首次**独立进程调用中成功；
- 允许**一次**诊断重试（`DIAGNOSTIC_RETRY_LIMIT = 1`），用于刻画失败；
- 首次失败仍记为失败；诊断重试成功**不会**把运行改成通过，**不会**替换进正式曲线，正式结果**不含**选择性重试拼接的数据（测试 `test_a_diagnostic_retry_never_changes_the_formal_result` 断言：`first_attempt_success=false`、`diagnostic_retry_succeeded=true`、`points=[]`）。

## 4. 单点结果契约

每个温度点在 `point_manifest` 中保存：`request_hash`、`temperature_C/K`、`components`、`phases`、`va_present`、`database_sha256`、`worker_pid`、`worker_returncode`、`solve_status`、`active_phases`、`phase_fractions_mole`、`phase_fraction_sum`、`runtime_s`、`stderr_summary`（脱敏并截断，本地绝对路径替换为 `<repo>`）、`first_attempt_success`、`solver_mode`。

父进程只合并**全部首次成功且契约验证通过**的点；缺少任何点时不输出部分正式曲线（`partial_curve_returned=false`、`points=[]`、`curve=[]`），并给出失败点清单与首个失败原因。

运行清单完整性哈希：`manifest_digest = digest_value(point_manifest)`（与逐点 `request_hash` 一并记录）。

## 5. 验收结果

脚本：`scripts/calphad_phase5_acceptance.py`（重型验收，机器可读报告写入 Git 忽略的 `outputs/calphad_phase5_acceptance.json`）。

| 项目 | 结果 |
| --- | --- |
| 独立点总数 | **324**（B-DQ 3 轮 × 54 + R-DQ 3 轮 × 54） |
| 首次调用成功 | **320 / 324**（成功率 **0.9877**） |
| 首次调用失败 | **4** 个点 |
| 失败位置 | 全部为 **B-DQ 的 875 °C 与 900 °C**（run 1 各 1 个、run 3 各 1 个）；两处的诊断重试也都失败 |
| native abort / `MemoryError` / 超时 | **0** 个点 |
| 每轮首次成功率 | B-DQ 52/54、**54/54**、52/54；R-DQ **54/54、54/54、54/54** |
| 三轮最大重复差 | R-DQ **1.3×10⁻⁹**（容差 1×10⁻⁷，通过；稳定相组合逐点一致）；B-DQ run 1 与 run 3 未产出完整曲线，三轮一致性无法形成 |
| 批量 vs 独立模式（R-DQ） | 共同收敛点 54 个，**最大差 1.069×10⁻⁴（@675 °C）> 1×10⁻⁷ → 不通过** |
| 物理合理性守卫 | B-DQ / R-DQ 均通过（`VA` 已包含、无低温液相、1500 °C 以上出现液相） |
| 导出限制声明验证 | B-DQ / R-DQ 均通过（含 Markdown/CSV/记录、每行带 profile 与求解模式） |
| B/R 体系一致性（请求层） | 通过（组元、相集合、温度网格、profile、求解模式逐项一致） |
| 总运行时间 | **4013 秒（约 66.9 分钟）** |
| 最终状态 | **`blocked`** |

> 数值以 Git 忽略的 `outputs/calphad_phase5_acceptance.json` 与可提交证据 `config/calphad_phase5_evidence_v1.0.json` 为准。B/R 一致性在**请求层**评估（不依赖某次运行是否产出完整曲线）。

### 5.1 关键发现：单点求解本身不确定

第五阶段的**独立单点模式并没有消除失败**，这修正了第四阶段的假设（当时认为失败来自批量热启动）。在**全新进程**中重复求解同一条件：

| 条件 | 成功/总次数 |
| --- | --- |
| B-DQ 900 °C | 1 / 8 |
| B-DQ 875 °C | 2 / 4 |

失败的返回是"没有任何相摩尔数"（`phase_fraction_sum` 为 0 / 无稳定相），**不是** native abort、`MemoryError` 或超时。因此在同一温度点重复调用会随机得到"成功（FCC_A1 = 1.0）"或"无解"。

也就是说：这是 pycalphad 0.11.2 在本机对该体系（12 组元 + `VA`、固定 7 相）于 α/γ 相界附近的求解不确定性问题，与环境无关、与数据库无关、也与模式无关。第四阶段的批量路径只是把同一个问题暴露得更频繁。

按第五阶段的规则（"任何一个正式点首次失败……继续 Blocked"；"324 个独立点全部首次成功"），**验收不通过，T86 保持 `Blocked`**。

**未采取**任何规避：没有删除 875/900 °C、没有改步长、没有插值或平滑、没有挑选成功的那一次、没有把诊断重试结果拼进正式曲线。

### 5.2 第二个阻断项：批量模式与独立点模式存在无法解释的差异

按第五节要求，用 R-DQ 对旧批量模式（`batch_workspace_warm_start`）与新独立点模式做了逐点对照。54 个共同收敛温度点中，**1 个点超过 1×10⁻⁷ 容差**：

| 温度 | BCC_A2 | CEMENTITE | FCC_A1 | 最大绝对差 |
| --- | ---: | ---: | ---: | ---: |
| 675 °C（独立点） | 0.9687085569 | 0.0286196329 | 0.0026718102 | — |
| 675 °C（批量） | 0.9686500344 | 0.0287265758 | 0.0026233898 | **1.069×10⁻⁴** |

两种模式在 675 °C 找到**相同的三相组合**，但相分数差到 1×10⁻⁴ 量级（远超 1×10⁻⁷，也远超 R-DQ 三轮之间的 1.3×10⁻⁹ 抖动）。差异出现在 BCC_A2+CEMENTITE+FCC_A1 三相区；其余 53 个点在容差内一致。

按规则"不得自行选择其中一条曲线"，因此**两条曲线都不发布**，该差异如实报告为阻断项，并保留在 `config/calphad_phase5_evidence_v1.0.json` 的 `batch_vs_independent` 中。判明哪一条（或都不可用）需要后续具名决定，本阶段不做取舍。

## 6. 状态

| 对象 | 状态 |
| --- | --- |
| 独立单点模式 `independent_single_point_process_v1` | 已实现并版本化为正式试点路径 |
| 批量模式 `batch_workspace_warm_start` | 降级为 `diagnostic_only` |
| 固定成分体系 / 固定相集合 | 不变（12 组元 + `VA`；7 相） |
| 数据库候选 | `compatibility_candidate` |
| T86 功能 | **`Blocked`** |

**未**声明 `pilot_ready_pending_scientific_review`、`validated`、`production_ready`。

输出命名**不变**：仍为 `12-component reduced-system matrix equilibrium prediction`；**不得**升级为完整相图、全组元结果或正式实验结论。

解除条件（需具名决定，任一都不得静默执行）：

1. 解决 875/900 °C 附近的求解不确定性（例如改用更稳健的求解器构建、调整初始点策略但不改变科学输入、或改用能稳定求解的 pycalphad 版本），并使 324 点全部首次成功；或
2. 具名批准把该温区排除并说明对目标窗口结论的影响；或
3. 进一步缩减成分体系或相集合，并同步新版本政策；或
4. 冻结为技术框架。

## 7. 工程约束

- **保留**第四阶段失败证据（`config/calphad_phase4_evidence_v1.0.json`）与旧批量路径，仅用于诊断与本次模式的对照。
- 新增独立点运行清单（`point_manifest`）与完整性哈希（`manifest_digest`）。
- **定向测试不启动重型求解**：`tests/test_t86_calphad_adapter.py` 中的第五阶段测试全部使用单点 worker 替身；重型验收由 `scripts/calphad_phase5_acceptance.py` 单独执行并保存机器可读报告。
- 文件读写统一使用显式 UTF-8（Python `open(..., encoding="utf-8")` / 编辑工具），不再使用依赖系统 ANSI 码页的 PowerShell 文本 cmdlet 批量改写源码或测试文件。

## 8. 复现命令

```powershell
# 定向测试（不启动重型求解）
.\.venv\Scripts\python.exe -B -m pytest -q tests\test_t86_calphad_adapter.py

# 重型验收（324 个独立点 + 模式对照；需显式具名批准）
.\.venv\Scripts\python.exe -X utf8 scripts\calphad_phase5_acceptance.py `
  --reviewer-id "<工作单中具名的批准人>" --approved-at 2026-09-25 `
  --approval-reason "<批准理由>" --json outputs\calphad_phase5_acceptance.json
```

## 相关文档

- [T86 第四阶段：固定缩减成分体系与固定相范围](T86_PHASE4_REDUCED_SYSTEM.md)
- [T86 第三阶段：社区兼容版数据库审查与兼容性验证](T86_PHASE3_COMMUNITY_COMPATIBILITY.md)
- [T86 第二阶段：隔离环境与兼容性门禁](T86_PHASE2_ENVIRONMENT_AND_GATES.md)
- [T86 CALPHAD 平衡相分数（阶段 1）](T86_CALPHAD_PHASE_FRACTION.md)
